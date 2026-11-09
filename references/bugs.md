# Test Hub Bug 处理

通过 `sg testhub` 复用现有平台能力。本指令由 AI 编排 CLI、当前任务修复和验证，不新增另一套 Bug 状态库。

## 动作与范围

| 调用 | 行为 |
| --- | --- |
| `bug [BBS编号]` / `bug fix [BBS编号]` | 拉取该 BBS 关联 Bug，逐项分析、修复、验证并回写结果 |
| `bug list [BBS编号]` | 查看关联 Bug 的标题、状态、严重程度和负责人 |
| `bug show [BBS编号]` | 读取关联 Bug 的描述、复现步骤、评论及附件 |
| `bug create [BBS编号]` | 将当前明确的问题提交到该 BBS 关联的 Test Hub 任务 |

所有可选编号都表示 BBS ID，省略时自动读取当前阶段的 `bbs_id`。用户无需知道平台 task ID 或 Bug key；AI 按 `BBS ID -> Test Hub 任务 -> 关联 Bug` 查询后，将平台 ID 用于内部 CLI 调用和结果追踪。下文命令中的 `<testhub-task-id>`、`<key>` 均由查询结果填入，不是要向用户索取的参数。

```text
/task-workflow bug                  # 自动处理当前阶段 BBS 关联的 Bug
/task-workflow bug 57381            # 处理 BBS 57381 关联的 Bug
/task-workflow bug list 57381       # 查看该 BBS 的 Bug 列表
/task-workflow bug show 57381       # 查看该 BBS 的 Bug 详情和证据
/task-workflow bug create 57381     # 将上下文中明确的问题提交到该 BBS 关联任务
```

用户只想处理其中一项时，可描述标题或现象，例如“只修销售单保存失败那个问题”。先查询该 BBS 的关联 Bug，再按描述定位；仍有歧义时展示问题标题和现象让用户选择，不要求用户回平台查 Bug key。

自然语言“处理当前任务的 Bug”按默认修复流程执行；“看看 Bug / 分析一下”只读取证和分析。修复调用授权该范围内的代码修复、必要测试、处理评论及允许的开发状态流转，不要求先开启 auto。提交推送复用用户已有授权或 auto 规则；没有相应授权时保留本地改动并如实回写。PR、发布、关闭 Bug、完成阶段不由本指令自动触发。

截图、提单 JSON 和请求 ID 等材料，有本地任务时保存在任务文档 `assets/testhub/` 下；仅持 BBS 编号查看或提单、尚无本地任务时，使用用户目录下的普通绝对目录，例如 `/Users/wuyongli/Downloads/testhub/bbs-<bbs-id>/`。这只是过程材料目录，不创建替代任务 meta 或 Bug 状态库。以下 `<key>` 子目录在查询到平台 Bug 后再使用。

## 定位当前阶段与平台任务

1. 先取用户在本次调用或明确上下文中给出的 BBS 编号。没有显式编号时，从当前任务 `meta.yaml` 自动读取：多阶段只取 `current_stage.bbs_id`，缺失时不得回退到顶层或历史阶段编号；非阶段化任务取顶层 `bbs_id`。仍无法确定时只询问 BBS 编号，不索取平台任务 ID 或 Bug key。
2. 已有本地任务时按 Load 协议读取 `meta.yaml -> index.md -> 当前 active_plan -> progress.md`，核对 BBS、绑定仓库、实际分支和已有改动。显式 BBS 与当前阶段不同，或尚无本地任务上下文时，先按 BBS 在 `_workspace/_docs` 的任务 meta 中定位正确任务或阶段；多个本地匹配时按任务名/阶段消歧。`list` / `show` / `create` 可直接对明确的 BBS 做平台查询或提单；修复必须先恢复正确的本地任务与分支，历史阶段切换仍遵循 [stages.md](stages.md)，不在当前分支修复其他阶段。未找到本地任务时说明需先绑定开发仓库，不因有 BBS 就自动创建工作空间。分支不一致或存在来源不明的改动时，保留现场并明确受影响范围。
3. 先核实当前 CLI：`sg testhub --help`、所需子命令的 `--help`。已有登录态直接复用；认证失败时按 `sg testhub auth login` 的设备授权流程处理，不读取或输出令牌。不要把 CLI 不可用或无权限解释为“没有 Bug”。
4. 用 `sg testhub project list --all-pages --max-items 200 --json` 获取可访问项目，有明确仓库和业务上下文时缩小到产地、批发等相关项目，不固定项目 ID。只有 BBS 编号、无法预先确定项目时，在可访问的候选项目中逐一执行下一步的精确关联查询，由结果确定项目；不能只选第一个项目，也不先要求用户补平台项目 ID。
5. 用下列命令检索候选。`--q` 是搜索线索，必须回读并核对 `bbs_number` 与本次目标 BBS 编号精确相同；字段为空的旧任务，才可用 `bbs_link` 中明确的反馈编号及业务类型核对。标题含有编号只能作为候选线索。字段与链接冲突时停止认领。

```bash
sg testhub task list --project <project-id> --q <bbs-id> --all-pages --max-items 200 --json
sg testhub task show <testhub-task-id> --json
```

搜索未命中时，去掉 `--q` 检查相关项目的任务分页，兼容仅在链接中保留编号的旧任务。多个精确匹配项时展示项目、任务 ID、名称及 BBS 关联让用户消歧；没有匹配项时报告缺少关联，不自动新建任务或修改平台关联。`--all-pages` 必须配合 `--max-items`，示例每批最多 200 项；列表有 `next_cursor` 或 `truncated` 时用返回的 `--cursor` 接续下一批，无法读完则报告查询不完整，不能断言唯一或为空。

6. 确定唯一匹配后，用平台 task ID 查 Bug，不能将 BBS 编号直接传给 `--task`：

```bash
sg testhub bug list --project <project-id> --task <testhub-task-id> --all-pages --max-items 200 --json
```

从返回列表提取每项 Bug key，后续内部 `sg testhub bug show <key>` 核对其 `project_id`、`task_id` 与上述关联一致；不一致时只报告实际归属，不修改代码或回写。用户按标题或现象限定范围时，只处理列表中匹配的项；没有限定时按默认状态规则处理全部待修项。没有待修 Bug 时输出查询结果，不制造空修复。`list` / `show` 到查看结果为止，不更新任务文档、平台状态或代码。

## 逐项修复与验证

- 默认修复 `new`、`assigned`、`in_progress` 的关联 Bug；`closed` 跳过，`pending_verify` 列为待测试人员验证，避免重复处理。用户明确要求复查指定项时可重新取证；发现待验证版本仍有缺陷时继续修复，状态操作仍按下节规则。已关闭项需要重新打开时说明证据，不擅自重开。
- 接续仍在 `in_progress` 的 Bug 时，先核对已有修复、验证及测试服发布证据。修复已验证但仍待发布时，复用现有记录并继续处理其他项。测试服已包含完整修复且仅缺状态流转时，直接补齐待验证流转，复用已经回写的评论。
- 每项先读取详情及完整上下文：

```bash
sg testhub bug show <key> --json
sg testhub bug context <key> --all-pages --max-items 200 --json
```

- 查看复现步骤、实际与预期结果、环境、关联任务、评论、截图与其他附件。按上下文的附件、评论、采集记录各自游标，用 `--attachment-cursor`、`--comment-cursor`、`--capture-cursor` 补齐对应分页；需要图片时用 `context --images-dir <绝对目录>`，按 `images.next_image_offset` / `remaining_ids` 配合 `--image-offset` 继续下载，并实际查看下载图片。文件放本次材料目录的 `<key>/` 下，目录使用用户目录下的普通绝对路径，避免 macOS `/tmp` 符号链接路径。未能读取的附件明确标为证据缺口，不声称已检查。
- 按严重程度、依赖和影响范围安排顺序；共享根因可合并修复，但每个 key 保留单独的复现、验证和回写结果。一项受阻时继续不依赖它的项，不扩展到未绑定仓库或其他阶段。
- 先复现或取得代码、日志等足以定位的证据，在当前 plan 收口预期行为、最小修复与验收条件；明确技术 Bug 直接诊断，业务口径不明确才按需使用 `product-copilot-rules`。修复调用提供范围内开工授权：明确技术 Bug 的最小方案由 AI 基于证据写入 plan，不再逐项索要开工确认；关键业务事实不明则暂停该项并补问。满足开发准入后同步 `status`、`current_stage.status`（有则同步）及 `coding_allowed` 再修改。暂停任务仍须明确恢复，不因检测到 Bug 自动解除暂停。
- 沿用当前任务记录分支和绑定仓库，不为每个 Bug 自动新建任务或 `next`。保留无关本地改动，按项目模式最小修复，有长期回归价值时补测试。
- 按 [verification.md](verification.md) 验证原始复现路径和受影响的关键回归，页面、接口、数据库证据按缺陷实际涉及的层面选择；按 [runtime.md](runtime.md) 使用当前任务环境，后端测试在当前任务专属 Docker app 中执行。不能只凭单测通过就声称原始页面问题已修复。
- 验证失败则在当前范围修复并重测；同一问题连续修复验证最多 3 轮，仍失败或关键环境/数据缺失时记录具体阻塞、未覆盖项及解除条件，不降低验收标准。

## 回写处理结果与状态

每项在 `progress.md` 记录 key、平台项目/任务 ID、根因、涉及仓库、修复及验证证据、阻塞和下一步；`index.md` 保留摘要，稳定方案归并当前 plan。平台关联每次执行仍需回读核对，不以本地历史记录替代。

修复完成且必要验证通过后，若完整修复尚未发布到测试服，在 `progress.md` 标记“已修复，待发布测试服”，按 Bug 记录所需仓库及各自修复提交。修复还未提交时记录改动范围，后续接续或发布时核对实际提交并补齐。已发布部分保留对应发布记录，供分批发布时继续核对。“待发布”仅用于本地进度，平台保留实际处理状态。多个 Bug 和优化可以集中发布，按 [publish-sync.md](publish-sync.md#发布后的-bug-交测) 接续。

1. 回写前重新 `bug show`，核对归属、当前状态、`version`、`capabilities.can_comment` 和 `capabilities.allowed_transitions`。允许的目标及必填字段以返回值为准，同时检查 `conditional_required_fields`，不写死角色权限或补造负责人、修复版本等信息。
2. 修复调用包含处理结果评论授权。评论说明根因、修复范围、真实验证结果、代码是否提交/推送、部署情况及待验证步骤；受阻时说明已完成部分和阻塞。使用 `--input <绝对JSON文件路径>` 传入 `{"body": "处理结果正文"}`，保存在本次材料目录的 `<key>/` 中，避免多行文本的 shell 转义问题。
3. 每次评论操作生成并记录独立的 `--request-id`，同一操作恢复或重试时复用，内容改变则使用新 ID。超时或结果不明先重新读取上下文核对；确认已成功不重复追加评论。无法核实则报告“回写结果不确定”，不盲目重放。
4. 开始修复时，仅在平台允许且所需字段已确定时进入 `in_progress`。保留现有负责人，按平台允许的路径流转。
5. **测试服包含完整修复后转待验证。** 复核确认缺陷存在、修复完成、必要验证通过，并确认测试服已成功发布该 Bug 所需的全部修复后，在平台权限允许的范围内执行 `transition ... pending_verify`，附上实际测试服版本和复测说明。仅完成提交、推送、PR、评论，或仅部分仓库的修复已发布时，保留实际状态并记录剩余发布项。

状态迁移与评论分别核对。即使评论已成功，仍须完成待验证迁移；评论权限不足或提交失败时单独报告，已具备交测证据且允许迁移的 Bug 仍可在迁移备注中附上验证说明。迁移前重新 `bug show` 获取最新 `version`。按目标的 `required_fields` 和 `conditional_required_fields` 填参数，目标允许填写解决结果时使用 `fixed`，需要 `fix_version` 时填写实际交测版本。

```bash
sg testhub bug transition <key> pending_verify --version <fresh-version> --note '<修复摘要、交测版本和复测步骤>' --json
```

根据返回的迁移要求和当前 `--help` 补齐参数，例如 `--resolution fixed` 或 `--fix-version <实际版本>`。平台只允许先进入 `in_progress` 时，按允许的迁移路径执行并回读，再以新版本号提交待验证。版本冲突时重新读取状态、权限和他人的更新，重新判断原动作是否仍适用。普通网络失败先核对结果，最多再尝试 1 次。非幂等状态操作结果不明且无法核实时停止。

6. 以 `bug show` 回读到 `status: pending_verify` 作为交测流转成功证据。已是待验证时跳过重复迁移。若回读仍为 `in_progress`，逐项报告实际状态和原因，例如权限不足、缺少实际交测版本或迁移失败，记录为流转未完成。用 `bug context` 核实评论结果，分别写入本地进度。测试人员最终验收、关闭 Bug 和任务阶段完成各按其独立授权处理。

### 钉钉通知测试人员

- 回读确认本轮交测 Bug 已为 `pending_verify` 后，按已授权的交测通知，通过 DWS 钉钉单聊通知复测人。本轮“只发布”或“不要通知”等限制优先。接续时可补发该交测轮次已记录为未发送的通知，先核对状态与测试服版本仍适用。
- 用 `sg testhub task show <testhub-task-id> --json` 回读 Bug 关联任务的 `tester`，用户明确指定复测人时以本轮指令为准。按 `dws` 的通讯录和单聊参考核对同一人的钉钉收件 ID。以真实人员身份匹配，Test Hub 的 `tester_id` 只用于平台内关联。缺少测试人员、身份无法唯一核实或需要跨组织发送时，按 DWS 规则保留待通知并说明原因。
- 同一批次同一测试人员合并一条消息，写明任务及阶段、BBS 编号、待验证 Bug 的编号与标题、已核实的测试服版本及复测要点。有已核实的 Bug 链接时附上链接。
- 发送前在 `progress.md` 保存本次通知的收件人、交测轮次及 Bug 范围、发送 UUID。确认发送后登记结果和可用回执。已成功的交测轮次跳过重复通知。发送超时先核对单聊结果，确需在 DWS 去重期限内重试时复用同一 UUID。结果仍不明则标记“通知结果不确定”，等待核实。通知失败单独汇报，保留已确认的 Test Hub 状态。

按 DWS 当前命令帮助发送，已核对的单聊形式如下。

```bash
dws chat message send --open-dingtalk-id '<已核对的钉钉收件 ID>' \
  --title '测试服 Bug 待验证' --text '<交测说明>' --uuid '<已记录的通知 UUID>' --format json
```

## 提交新 Bug

`bug create` 表示授权创建该问题。先按上述规则定位平台任务，检索相同任务下的已有 Bug，核对复现与环境避免重复；已有同一问题时返回其 key，未获补充评论授权时不自动发评论。

根据当前 `sg testhub bug create --help` 整理项目、平台 task ID、标题、复现步骤、实际结果、预期结果、环境和严重程度等必需信息。已观察到的事实直接填入，未复现不写成“已复现”；缺少影响提单的必要信息时只补问缺项。描述中带当前 BBS 关联与受影响端，不把口令或个人敏感数据放入附件。

通过 `sg testhub bug create --input <绝对JSON文件路径> --request-id <已记录的操作ID> --json` 提交。JSON 使用接口字段 `project_id`、`task_id`、`title`、`severity`、`reproduce_steps`、`actual_result`、`expected_result`、`environment_type`、`environment_detail` 等；不要将 CLI 的 `--project` / `--task` 直接写成 JSON 的 `project` / `task`。枚举值以当前 CLI/客户端声明为准，不从中文标签猜值。创建后 `bug show` 回读项目、任务归属及关键内容，记录返回 key。结果不明按评论相同的幂等与有限重试规则处理，不重复建单；附件上传仅在用户要求或提单所需证据的授权范围内执行。

## 输出

以 BBS 编号和任务名说明处理范围，逐项按问题标题说明根因或阻塞、修复与验证结果、平台回写后的真实状态；平台 Bug key 可作辅助追踪，不作为用户后续调用的必填信息。代码提交推送、发布和业务验收分别陈述；只读查询、无待修项或部分失败时直接说明事实。
