---
name: task-workflow
description: "当处理 /Users/wuyongli/Documents/sg-project/_workspace 下的多仓任务创建、恢复、自动开发模式、BBS 关联 Bug 处理、代码审查、钉钉审查意见复核修复与回复、提交推送、PR、发布、同步、阶段切换或生成公示文档时使用。"
---

# 任务工作流

用于 `_workspace` 下按任务隔离的多仓 clone 工作流。先识别本轮动作与授权，再按指令导航读取所需参考；不默认加载全部参考文档。

## 任务模型与事实入口

工作区根目录：`/Users/wuyongli/Documents/sg-project/_workspace`。

| 内容 | 位置 / 规则 |
| --- | --- |
| 任务文档 | `_docs/<task-id>` |
| 任务代码 | `_tasks/<task-id>/<repo-key>__<原始任务名>`，是真实 clone |
| 运行配置 | `config` |
| task id | `YYYY-MM-DD-<原始任务名>` |
| 默认分支名 | 不带日期前缀的原始任务名 |
| 工作流脚本 | `/Users/wuyongli/Documents/sg-skill/task-workflow/scripts` |

- 任务优先按当前 `_tasks/<task-id>/...` 路径绑定，分支名只用于一致性校验。
- `meta.yaml` 是状态、仓库、记录分支、当前阶段、当前主计划和可选 `bbs_id` 的机器事实入口；`index.md` 只展示摘要。
- 恢复任务上下文时按 [Load](references/docs-model.md#load) 读取 `meta.yaml`、`index.md` 和所需材料。单独执行操作指令时，按该指令的章节确定读取范围。
- Code Only 例外：仅用 meta 定位仓库和分支，不读取任务方案或进度；执行方式见下方 Review 规则。
- 同一工作空间可承载多个阶段，任一时刻只有一个当前阶段。顶层状态表示当前阶段状态，历史状态保存在 `previous_phases`。
- `plan.md` / 当前阶段 plan 保存当前有效方案与决策原因；`progress.md` 保存执行、验证和阻塞；`decision-log.md` 保存讨论与取舍过程。详细职责见 [docs-model.md](references/docs-model.md)。
- 文档归并更新，避免堆叠多个有效版本。机器事实变化先更新 meta，再同步摘要；具体更新协议见 [docs-model.md](references/docs-model.md#progress)。

## 指令导航

显式指令以 `/task-workflow` 开头，也接受表中列出的自然语言意图。先读表中链接的对应章节，再按本轮操作读取适用的共用、输出与文档同步规则。涉及验证或运行环境时，分别读取 [验证规则](references/verification.md) 或 [运行环境](references/runtime.md) 的相关章节。

满足指令前置条件时，按参考命令调用现有脚本，由脚本完成其已有检查。参数不明时看 `--help`，出现异常或需要修改脚本时再读相关源码。一次调用包含多个动作时，各自按所需范围取证。

| 指令 / 意图 | 用途 | 执行前必读 |
| --- | --- | --- |
| `init` | 初始化工作区目录和运行配置 | [生命周期：Init](references/lifecycle.md#init) |
| `create` | 按选定仓库创建任务 clone 和文档，可带 BBS 编号 | [生命周期：Create](references/lifecycle.md#create) |
| `load` | 恢复当前任务上下文 | [文档：Load](references/docs-model.md#load) |
| `progress` | 更新机器事实、当前摘要、方案与执行记录 | [文档：Progress](references/docs-model.md#progress) |
| `mode auto` / `mode manual` | 切换当前任务空间执行模式 | [自动模式](references/auto-mode.md) |
| `publish [目标...]` | 发布指定仓库到测试服 | [发布：Publish](references/publish-sync.md#publish) |
| `sync [目标...]` | 同步各仓库远程主线 | [发布：Sync](references/publish-sync.md#sync) |
| `pr [目标...]` | 自动提交、推送选中仓库的本任务改动，再创建或复用 PR；参数见参考 | [发布：PR](references/publish-sync.md#pr) |
| 保存 / 提交 / 推送到远程 | 只保存当前任务改动 | [Save / Push](references/publish-sync.md#save--push)、[保存边界](references/verification.md#save-only-边界) |
| `clean-develop [目标...]` | 删除指定仓库的本地 develop | [Clean Develop](references/publish-sync.md#clean-develop) |
| `mysql <目标后端>` | 显式切换本地共享 MySQL 数据目录 | [运行环境：MySQL](references/runtime.md#mysql) |
| `review [目标...]` / `codeview [目标...]` | 默认完整 Review | [审查](references/review.md) |
| `review --code-only [目标...]` | 隔离任务文档，只按代码证据审查 | [审查：模式选择](references/review.md#模式选择) |
| `fix <姓名> [目标...] [最近N条]` | 读取该人的 PR 意见、复核、修复明确问题、推送并按每个 PR 单独钉钉回复；也接受只发送现有处理结果（不重新修复），只读消息时不发送；默认最近 10 条单聊消息 | [外部审查意见](references/review-feedback.md) |
| `complete` | 标记当前阶段完成并停止任务 runtime | [生命周期：Complete](references/lifecycle.md#complete) |
| `next <新任务名>` | 在原空间开启下一阶段，可带 BBS / repo 参数 | [阶段：next](references/stages.md#next-规则) |
| `stage <阶段编号或阶段任务名>` | 切回已记录阶段及其分支 | [阶段：stage](references/stages.md#stage-规则) |
| `cleanup` | 删除已完成或不再开发任务的代码及专属 app，保留文档 | [生命周期：Cleanup](references/lifecycle.md#cleanup) |
| `status` | 查看任务状态、仓库路径和路径存在性 | [生命周期：Status](references/lifecycle.md#status) |
| `portal` | 生成静态入口页或启动刷新即最新的本地页 | [运行环境：Portal](references/runtime.md#portal) |
| `doc [任务名]` | 生成并投递当前阶段公示文档 | [公示文档](references/doc.md) |
| `bug [BBS编号]` / `bug fix [BBS编号]` | 复核、修复、验证、提交推送、发布测试服、回写并钉钉回复测试人员 | [Bug 处理](references/bugs.md) |
| `bug list/show/create [BBS编号]` | 查看列表、详情或提交问题 | [Bug 处理](references/bugs.md) |
| 多任务假期安排 / 总调度 | 持久化串行派发、人工追加、交接和通知记录 | [总调度](references/dispatch.md) |

同一轮同时要求多个动作时，分别遵守各自边界。只执行用户要求或既有授权覆盖的动作，不因执行一项自动触发下一项。

## 执行模式与开发准入

`meta.yaml.execution_mode` 为任务空间级 `manual` / `auto`，缺省为 `manual`；`next`、`stage` 与会话切换保持模式，新阶段仍需自己的方案和准入。

- 用户开启或要求继续自动开发，以及恢复到 auto 且本轮要求继续任务时，按 [auto-mode.md](references/auto-mode.md) 连续推进已授权范围。
- `mode manual` 关闭自主连续推进，不撤销已经成立的开发授权。暂停与 manual 不同；暂停任务需明确继续，不能因 auto 自动恢复。
- 本轮“只分析 / 只审查 / 只保存 / 不改代码”等更窄限制优先。单独 load 或状态查询不触发开发。
- auto 的方案、开发、自测、审查修复和提交推送授权，以及钉钉里程碑推送、资源释放和数据库范围，均按自动模式参考执行，不扩大到 PR、发布或阶段完成。
- 自动模式本身不创建定时器、会话或后台调度。多任务安排按总调度参考执行，定时唤醒另行配置，队列初始化默认关闭。

### 开发准入闸门

新任务默认处于 `方案中`。

方案中可以分析需求、读取代码 / 配置 / 文档、讨论和完善方案、更新任务文档、给出实现与验证建议。

尚未满足准入时，不得修改业务代码、配置、SQL、脚本，或安装依赖、执行迁移、启动正式实现；“先看下 / 先分析 / 先给方案 / 先评估”不构成开发授权。

从 `方案中` 进入 `开发中` 必须同时满足：

1. 当前 plan 的方案由用户确认，或由 AI 在已启用自动模式及其明确授权范围内确定。明确调用 `bug` 修复、预期行为已明确且无需新增产品决策的技术 Bug，也可由 AI 基于复现及代码证据确定最小修复方案并写入 plan；业务口径不明时仍不能开工。
2. 当前 plan 中开发方案可执行，影响开工的关键待确认项已收敛。
3. 用户已明确允许代码工作，或已有包含开发的自动模式授权；本轮无更窄限制。Bug 修复调用的范围内授权见 [bugs.md](references/bugs.md)。

方案采用依据必须如实区分，不把 AI 依据预授权确定的方案写成“用户已确认”。有效的既有授权不重复索取；满足准入后，先同步 `status`、`current_stage.status`（有则同步）及 `coding_allowed: true` 再编码，不能只凭 auto 放行。

恢复既有任务时：

- `方案中` 默认继续分析、补方案和文档；已有自动授权且满足准入后可继续开发。
- `开发中` / `测试中` 可以继续既有实现与验证，除非用户明确要求回到方案讨论。
- 固定任务状态为 `方案中`、`开发中`、`测试中`、`暂停中`、`已完成`；多阶段同步维护当前阶段与顶层状态。

## 操作中的关键边界

以下是选择动作时必须保留的边界，具体步骤、命令、异常处理及输出字段以对应参考为准。

### 目标与阶段

- 发布、同步、PR、清理 develop 和保存共用动态目标识别：从当前任务绑定仓库匹配后端、手机端、PC 端等；无法唯一匹配时才补问，不要求用户重复提供已知路径与分支。
- 用户一开始明确“一期 / 二期 / 分阶段 / 先做 A 再做 B”时，即从创建起读取阶段参考，按阶段化文档模型处理；不按前端 / 后端等技术面拆产品子任务。
- `next` 不代表上一阶段已完成；`stage` 必须同步代码分支与任务文档，目标阶段缺分支时阻断，不重建分支。
- `complete` 只停止 runtime 并保留代码、容器和文档；`cleanup` 可直接清理未完成或暂停的任务，不必先 complete；丢弃本地成果需明确授权。只删除任务代码及专属 app，不影响共享资源或任务文档，细则见生命周期参考。

### 保存、PR、发布与同步

- 独立要求“提交到远程 / 推送一下 / 保存代码”按 save-only 处理：不顺带测试、准备依赖、审查、创建 PR、发布或标记完成；同时明确要求验证或审查时执行相应动作。
- 明确创建 PR 即包含选中仓库本任务改动的必要验证、提交与普通推送授权，不因尚未 commit 重复询问；查看状态仍只读。默认 WIP、配套端标题、日期和 BBS 关联按 PR 参考执行，不自动合并或关闭 PR；无关改动和失败边界按参考处理。
- 普通 publish 先对相同目标调用 clean-develop，只处理本地 develop；develop 发布冲突 / 重试现场按发布参考保留并处理，不删除现场。前端和后端成功都需明确成功信号或匹配本次执行的成功日志，证据不足为 `UNCERTAIN`，不盲目重发。普通 publish 只发布并逐仓报告结果，不自动流转 Bug 状态，也不发送钉钉通知；Bug 交测只在 `bug` 流程或用户同轮明确要求“发布并交测 / 通知测试人员”时执行，本轮只发布等更窄限制优先。
- 独立 sync 的冲突或异常只报告事实，保留现场，不自动修代码或解决冲突。它与发布中的 develop 冲突处理规则不同。

### 审查

- 默认完整 Review 同时覆盖通用代码审查、对抗式审查和测试代码收敛，并检查代码质量优化；默认只读，获得修复授权或处于已授权自动开发内循环时才修改。
- `review --code-only` 不读取 index / plan / progress / decision-log，不复用历史需求判断，仅用 meta 定位仓库和记录分支；结论不代表需求完整性或上线验收。
- 审查对象固定为 `meta.yaml` 记录的本地任务分支；已提交改动使用三点比较 `origin/<远程主分支>...<本地任务分支>`，工作区改动补充检查。远程同名任务分支只提示落后或分叉，不替代审查对象。
- `fix` 是独立的外部审查意见处理指令，包含当前范围内明确问题的修复、验证、普通推送，以及按每个收件人、每个 PR 一条消息的钉钉回复；一次调用完成全流程。本轮明确“先不发消息 / 只复核 / 不改代码 / 不推送”时按限制执行。姓名与目标仅约束本轮，不保存仓库审查人配置。PR 标题与链接按[阶段 PR 记录](references/publish-sync.md#pr-记录与复用)优先复用。
- 不凭泛泛建议或猜测认定缺陷；基于真实 diff、项目规则和代码路径，区分明确问题、风险与待确认项。输出格式由审查参考统一维护。

### Bug 与公示文档

- Bug 指令的编号始终是 BBS ID，省略时读取当前阶段 `bbs_id`；平台 task ID 和 Bug key 由 AI 查询，不要求用户记忆或提供。
- `bug` 默认按批次处理：逐项复核；确认真实 Bug 后自动修复、必要验证，本批修复按仓库统一提交推送，再对受影响仓库统一发布测试服，按批次回写平台并按测试人员合并钉钉回复。不明确、待讨论或受阻的项只挂起该项，不阻塞其它真实 Bug 的修复、发布和回复。发布前记录待发布，发布成功且回读确认测试服包含完整修复后，按平台权限转为 `pending_verify`（待验证）；发布失败或结果不确定时保留实际状态并如实回复。`list` / `show` 只查看，`create` 提交上下文中明确的问题。PR、关闭 Bug 或完成阶段仍按各自指令执行。
- `doc` 由用户主动调用，生成并校验后只将公示记录写入对应阶段的 `publications`；不改任务代码、状态、开发许可或方案。“改动前”按涉及仓库远程 master 的实际功能，不用阶段方案替代；跨会话查回和继续编辑见公示参考。

## 运行与验证

- 配置为 `shared-backend-app` 的后端测试在当前任务专属 Docker app 中执行，从任务后端仓库根目录发起，容器内也从仓库根目录运行。Docker 阻断时记录事实，不回退宿主机或其他任务容器。
- 配置为 `patch-node-frontend-environment` 的前端使用项目 Node 直接运行最小相关验证；仅缺 node_modules 或实际报 native binding 缺失时 prepare。发布前只准备当前平台原生 optional 依赖，不运行完整 runtime prepare。
- 小程序 / 微信开发者工具前端按项目既有编译、预览或上传流程验证，不因未执行上述前端 prepare 阻断审查。
- 当前任务 Docker 日志可在 manual 和 auto 下只读取证，容器定位及读取方法见 [verification.md](references/verification.md#当前任务-docker-日志排障)。
- 真实页面、接口、数据库验证、历史证据复用与失败停止条件按验证参考执行。单测通过、提交推送、测试服发布和业务验收分别陈述，不相互替代。
- MySQL 数据目录只在用户明确调用 mysql 时切换，不把切库、补字段、导数据或迁移混入普通 runtime 启动。

## 输出

聚焦本轮动作的任务 / 阶段、实际目标、已执行结果、验证或阻塞及下一步；各操作的详细输出要求在对应参考维护。

成功、已推送、已发布、已验收等结论分别以相应证据为准；部分失败逐项说明，不把“开始执行”表述成“已完成”。
