---
name: task-workflow
description: "用于 /Users/wuyongli/Documents/sg-project/_workspace 任务工作区相关场景：创建/恢复/继续任务、更新进度、代码审查/codeview、创建合并请求、收敛测试代码、发布、同步远程主线、删除本地 develop 分支、切换本地 MySQL 数据目录、查看任务开发地址或端口、开启下一阶段、切换阶段、完成或清理任务。"
---

# 任务工作流

## 概览

这个 skill 用于 `/Users/wuyongli/Documents/sg-project/_workspace` 下按任务隔离的多仓库 clone 工作流。

核心模型：
- 一个任务 = 一个文档目录 + 一个任务代码目录
- 任务文档放在 `_docs/<task-id>`
- 仓库真实 clone 放在 `_tasks/<task-id>/<repo>__<task-name>`
- 任务绑定以路径名为准，不以分支名为准
- 一个工作空间可以承载同一长期主题下的多个阶段任务，但任一时刻只应有一个“当前阶段任务”
- 多阶段任务必须区分每个阶段自己的状态；顶层 `status` 表示当前阶段状态，历史阶段状态记录在 `previous_phases`
- 任务或阶段可以带可选 `bbs_id`，用于记录内部需求反馈编号

文档分层：
- `meta.yaml`：机器事实，只记录状态、分支、当前阶段、当前主计划、可选 `bbs_id` 等可恢复信息
- `index.md`：人读任务摘要，只保留当前状态、当前主线、当前阻塞、下一步和当前入口
- `plan.md`：当前有效方案，只保留已经成立的方案结论、核心决策原因、开发方案、数据变更和上线方案
- `progress.md`：执行记录，只记录实际做了什么、验证了什么、发布了什么、阻塞和下一步
- `decision-log.md`：方案讨论过程容器；用于承接候选方案、取舍推演、被否方案、口径变化原因等不适合长期塞进 `plan.md` 的讨论细节
- `*-plan.md` / `appendix-*.md`：仅承接稳定的模块子方案或参考资料，不承接讨论流水
- `sql/`、`assets/`：承接上线 SQL 和截图、原型、数据样本等过程文件，避免非正式文档散落在任务根目录

文档职责边界：
- 当前应该按什么方案做，写入 `plan.md`
- 实际推进到了哪一步，写入 `progress.md`
- 方案讨论过程、候选路径和取舍推演，写入 `decision-log.md`
- 当前稳定结论和核心决策原因，提炼回 `plan.md`
- 当前状态、当前主线和下一步入口摘要，写入 `index.md`
- 脚本和 AI 恢复上下文所需的机器事实，写入 `meta.yaml`
- 任务过程中产生的不确定材料，先按文件形态放入 `assets/`，不要为了内容不确定而新建零散 markdown

固定路径：
- workspace root: `/Users/wuyongli/Documents/sg-project/_workspace`
- task docs: `/Users/wuyongli/Documents/sg-project/_workspace/_docs/<task-id>`
- task code: `/Users/wuyongli/Documents/sg-project/_workspace/_tasks/<task-id>`
- runtime config: `/Users/wuyongli/Documents/sg-project/_workspace/config`

任务命名规则：
- task id 使用 `YYYY-MM-DD-<原始任务名>`
- 仓库目录名使用 `<repo-key>__<原始任务名>`
- 分支名默认使用不带日期前缀的原始任务名

## 工作流

细节按需读取：
- Review / codeview 细则见 [review.md](references/review.md)
- 文档模型与模板规则见 [docs-model.md](references/docs-model.md)
- 阶段化、`next`、产品子任务拆分规则见 [stages.md](references/stages.md)
- 发布、同步和目标识别规则见 [publish-sync.md](references/publish-sync.md)
- runtime、后端测试环境和配置字段见 [runtime.md](references/runtime.md)

### 1. Init

用于 `_workspace` 还没有初始化的时候。

预期结果：
- 创建 `_workspace/config`
- 创建 `_workspace/_tasks`
- 创建 `_workspace/_docs`
- 从 `references/` 补齐缺失的运行配置

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/init_workspace.py
```

### 2. Create

用于创建新任务工作区。

默认流程：
1. 规范化 task id 为 `YYYY-MM-DD-<任务名>`
2. 创建 `_tasks/<task-id>` 和 `_docs/<task-id>`
3. 把每个选中的仓库 clone 到 `_tasks/<task-id>/<repo>__<task-name>`
4. 基于远端默认分支最新提交创建或重置任务分支
5. 从主仓库或任务仓库模板补齐缺失的本地运行配置
6. 生成 `index.md`、种子版 `plan.md`、`progress.md`、`meta.yaml`

路径绑定规则：
- 优先通过当前路径 `_tasks/<task-id>/...` 识别任务
- 再从 `_docs/<task-id>` 加载文档
- 文档里记录的分支只作为一致性校验，不作为主绑定依据

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/create_task_workspace.py "原始任务名" --repo producer-backend --repo pf-mproducer-supplier
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/create_task_workspace.py "原始任务名" --bbs-id 53850 --repo producer-backend
```

运行说明：
- `create_task_workspace.py` will only补齐缺失的本地运行配置，不会覆盖 task clone 里已有文件
- `--bbs-id` 是选填；用户提供内部需求反馈编号时才写入 `meta.yaml` 和初始文档，不提供时不生成空编号占位
- 不会自动安装项目业务依赖；`producer-backend` 仅会为任务 app 容器补齐必要测试工具
- 任务分支只以远端默认分支作为起点，不自动跟踪 `origin/master` 或其他默认分支；首次推送任务分支时再建立自己的 upstream
- 如果用户一开始就明确“一期 / 二期 / 分阶段 / 先做 A 再做 B”，从创建任务开始读取 [stages.md](references/stages.md)，按阶段化文档模型处理
- 对于配置为 `shared-backend-app` 的后端，会生成任务及仓库级 Docker 辅助文件；同一任务的多个后端各自启动独立 `app` 容器，同时复用共享基础设施
- 对于配置为 `shared-backend-app` 的后端，任务 app 启动后会检查容器内是否可用 `pytest`；缺失时自动安装 `pytest==7.4.4`
- 当 `repositories.yaml` 开启 `auto_start_on_prepare` 时，运行配置准备阶段也会执行配置里的自动启动步骤
- 对于配置为 `patch-node-frontend-environment` 的前端，运行配置准备阶段会检查并修复当前 Node 平台缺失的原生 optional 依赖；这是本地环境准备，不是业务代码改动
- 如果主仓本地配置后续发生变化，可以重新执行：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/prepare_task_runtime.py "YYYY-MM-DD-原始任务名"
```

### 3. Load

用于在新会话里恢复任务上下文。

默认恢复协议：
1. 先读 `meta.yaml`
2. 用 `meta.yaml` 确认任务状态、仓库绑定、记录分支、恢复状态等机器事实
3. 再读 `index.md` 获取给人看的当前摘要
4. 当需要任务目标或方案细节时读 `plan.md`
5. 当需要当前进展、自测结果或阻塞时读 `progress.md`
6. 当需要理解“为什么这样定”时，先读 `plan.md` 的核心决策与原因；如果存在 `decision-log.md`，再读讨论过程和历史推导

恢复任务时的协作原则：
- `meta.yaml` 是 AI 恢复上下文时的第一事实入口，不是补充校验文件
- `index.md` 是给人读的摘要页，不负责定义机器事实
- 如果 `index.md` 与 `meta.yaml` 不一致，优先以 `meta.yaml` 为准，再在同一轮把摘要文档修正到一致
- 如果没有先读 `meta.yaml`，就不要声称已经完成任务状态核对、仓库绑定核对或记录分支核对
- 如果任务已经进入多阶段模式，先用 `meta.yaml` 确认当前阶段、当前阶段状态、当前分支、当前 plan 和可选 `bbs_id`，再用 `index.md` 理解当前阶段与历史阶段的关系

路径查找规则：
- 如果当前仓库路径匹配 `_tasks/<task-id>/<repo-dir>`，就直接从 `<task-id>` 反查任务
- 然后去 `_docs/<task-id>` 读取文档
- 如果当前分支和文档记录不一致，需要显式指出，并在合适时更新文档

### 4. Progress

用于任务已经推进，文档也需要同步更新的时候。

默认更新协议：
1. 先判断这次更新是否影响机器事实
2. 如果影响了任务状态、`resume_status`、仓库绑定、记录分支，先更新 `meta.yaml`
3. 再更新 `index.md` 的当前摘要
4. 如果这次推进改变了方案结论、核心决策原因、开发方案或上线口径，再更新 `plan.md`
5. 如果这次推进只是执行、验证、发布、阻塞或下一步变化，再更新 `progress.md`
6. 如果这次推进处于方案讨论阶段，且出现候选方案、取舍推演、被否方案或口径变化，更新 `decision-log.md`
7. 如果讨论已经形成稳定结论，把当前有效结论和核心原因回写到 `plan.md`

更新原则：
- `index.md` 只保留当前快照
- `index.md` 不承载方案摘要，超过一屏时应先瘦身
- `plan.md` 只保留当前有效方案、核心决策原因和执行依据
- `progress.md` 只记录实际进展、验证结果、发布记录、阻塞与变更历史
- `decision-log.md` 承接方案讨论过程；简单任务可不创建，复杂方案讨论应主动创建或更新
- `meta.yaml` 保存最小机器事实
- 不允许让 `index.md` 比 `meta.yaml` 更“新”
- 更新文档时，优先整段重写当前章节并归并重复内容，不要只在原文后面继续追加碎片信息
- 如果某个结论、方案或进展已经被新内容替代，应直接覆盖旧表述，而不是保留多个版本并列
- 不要把运维噪音、启动端口、白屏排查等运行细节写进 `progress.md`
- 文档拆分、`decision-log.md`、种子版 / 正式版 plan、子文档单一来源等细则见 [docs-model.md](references/docs-model.md)
- 阶段化和产品子任务拆分细则见 [stages.md](references/stages.md)

任务状态固定为：
- `方案中`
- `开发中`
- `测试中`
- `暂停中`
- `已完成`

`plan.md` 默认先用种子版结构；任务进入深入方案阶段后再扩为正式版。涉及后端表 / 字段 / 索引调整时，数据变更与上线方案优先沿用 `product-copilot-rules` 定义的统一格式。

### 5. Publish

用于本地开发和验收完成后，把当前任务的指定仓库发布到测试服。

显式命令：

```text
/task-workflow publish [目标1] [目标2] [目标3...]
```

用户可以直接用自然语言描述发布目标。执行前必须读取 [publish-sync.md](references/publish-sync.md)。

关键边界：
- 用户显式输入 `/task-workflow publish ...` 时，视为已授权直接执行发布动作
- 默认不指定目标时，发布当前任务下全部绑定仓库
- 发布目标按当前任务绑定仓库动态识别，不依赖固定中文名称
- 多目标发布默认并行；单个目标失败不阻断其它目标
- 配置为 `patch-node-frontend-environment` 的前端，执行 `sg publish local` 前只自动准备当前 Node 平台缺失的原生 optional 依赖；不要执行完整 runtime prepare，避免改写端口、代理或 `environment.toml`
- 不能只看退出码；必须看终端明确成功信号和错误信息
- `sg publish` 停在 `develop` 合并冲突时，保留冲突现场并优先在 `develop` 自动解决明确冲突
- 从 `develop` 重试发布成功后，必须切回 `meta.yaml` 记录的任务分支

### 6. Sync

用于任务周期较长时，把当前任务下的仓库同步远程主线代码，避免和主线落后太多。

显式命令：

```text
/task-workflow sync [目标1] [目标2] [...]
```

执行前必须读取 [publish-sync.md](references/publish-sync.md)。

关键边界：
- 默认不指定目标时，同步当前任务下全部绑定仓库
- 多仓库同步默认并行
- 有未提交本地改动的仓库不继续同步，只展示 `git status --short`
- 同步冲突、工作区异常、分支异常或 git 报错时，只反馈事实，不自动修代码、不自动解冲突

### 7. PR

用于为当前任务的指定仓库创建合并请求。

显式命令：

```text
/task-workflow pr [目标1] [目标2] [...] [--title <标题>] [--desc <描述>] [--reviewer <用户>]... [--task-link <BBS链接>] [--no-wip]
```

执行前必须读取 [publish-sync.md](references/publish-sync.md)。

关键边界：
- 用户显式输入 `/task-workflow pr ...` 或明确要求为指定任务仓库创建合并请求时，视为已授权创建 PR；不把“查看 PR”“检查 PR 状态”视为创建授权
- 默认不指定目标时，为当前任务下全部绑定仓库创建 PR；指定目标时，目标表达方式与 publish / sync 相同
- 目标仓库按当前任务绑定仓库动态识别；多目标默认并行，单个仓库失败不阻断其它仓库
- 创建前要在候选绑定仓库基础上多做一次实际改动检查：相对远程默认分支没有 diff 的仓库跳过创建，并在结果里说明“无本次 PR 改动”
- 源分支直接使用 `meta.yaml` 记录的任务分支；目标分支使用各仓库远程默认分支，用户明确指定目标分支时才覆盖
- 未指定 `--title` 时，PR 标题默认按 `任务名（是否有前端/后端）` 生成；括号只基于实际有 diff、准备创建 PR 的仓库集合判断，不基于任务曾经绑定过的全部仓库判断
- 日期和 BBS 编号由 `sg pr create` 按创建当天和 `--task-link` 自动拼接，task-workflow 不重复加入
- 创建前先确认仓库存在、当前分支与 `meta.yaml` 记录分支一致、工作区干净，并用 `sg pr status` 检查当前分支没有已存在的开放 PR
- 源分支尚未推送时，允许先执行普通 `git push -u origin <当前分支>`；不自动提交、不 force-push、不改写历史
- 默认创建 WIP PR：`sg pr create --target <远程默认分支> --wip`
- 用户传 `--no-wip`，或明确说“取消 WIP / 不要 WIP / 创建正式 PR”时，调用 `sg pr create` 时省略 `--wip`
- `--reviewer` 可重复；取消 WIP 只影响是否追加 `--wip`，不改变目标分支、标题、描述、reviewer 或授权边界
- 若已有开放 PR、仓库状态异常、分支不一致、推送失败或 CLI 返回错误，只反馈事实，不自动关闭、编辑、合并或重试已有 PR

### 8. Clean Develop

用于发布前清理当前任务仓库里的本地 `develop` 分支，避免后续 `sg publish` 合入远程 `develop` 前误用落后的本地分支。

显式命令：

```text
/task-workflow clean-develop [目标1] [目标2] [...]
```

执行前必须读取 [publish-sync.md](references/publish-sync.md)。

关键边界：
- 只删除本地 `develop` 分支，不删除、不推送、不改动远程 `origin/develop`
- 默认不指定目标时，处理当前任务下全部绑定仓库
- 指定目标时，目标表达方式与 publish / sync 相同
- 多仓库默认并行处理
- 某个仓库没有本地 `develop` 分支时视为 no-op，不影响整体结果
- 如果某个仓库当前正停在 `develop`，不删除该仓库的分支，输出当前状态并停止该仓库

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/clean_develop_task_workspace.py "YYYY-MM-DD-原始任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/clean_develop_task_workspace.py "YYYY-MM-DD-原始任务名" 后端 手机前端
```

### 9. MySQL

用于在产地后端和批发后端本地开发之间，显式切换共享 MySQL 容器的数据目录。

显式命令：

```text
/task-workflow mysql <目标后端>
```

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_mysql.py "批发后端"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_mysql.py "产地后端"
```

关键边界：
- 只处理本地 `pf-mysql-1` 的 `/var/lib/mysql` 数据目录切换
- 不切换 Redis、Mongo、RabbitMQ、Nginx
- 不补字段、不导数据、不执行迁移
- 当前数据目录已经匹配目标后端时，直接 no-op
- 当前数据目录不匹配时，只重建 MySQL 容器，输出切换前后目录
- 切换会让正在连接 MySQL 的任务 app 短暂断开，必要时重启对应后端 app

### 10. Review

用于任务开发完成或准备上线前，对当前任务改动做代码审查、项目规则审查、对抗式审查，并收敛测试代码。

显式命令：

```text
/task-workflow review [目标1] [目标2] [...]
/task-workflow codeview [目标1] [目标2] [...]
```

目标表达方式与 publish / sync 相同：
- 默认不指定目标时，审查当前任务下全部绑定仓库
- 指定目标时，继续使用和 publish 一样的自然语言目标识别方式，例如 `后端`、`前端`、`手机前端`、`PC前端`

执行规则：
- 用户说“代码审查”“检查代码改动”“收敛测试代码”“一次性测试可以去掉”时，按 `review` 处理
- 先恢复任务上下文，再基于真实 diff、真实项目规则和真实代码路径审查
- 如果 review 目标是配置为 `patch-node-frontend-environment` 的前端，跑 Vitest / `npm run typecheck` / `npm run build:*` 前先自动执行 `prepare_task_runtime.py <task-id> --repo <目标前端>`；小程序等未配置该 runtime 的前端不强制 prepare
- 默认做三轮：通用 code review、对抗式审查、测试代码收敛审查
- 默认只输出结论，不改代码；用户明确授权“明确问题直接修”“测试代码可以收敛/删除”时才修改
- 详细流程和判断标准见 [review.md](references/review.md)

### 开发准入闸门

默认情况下，新任务创建后状态为 `方案中`。

当任务处于 `方案中` 时，AI 可以做：
- 需求分析与方案讨论
- 读取代码、配置、文档，评估当前系统现状
- 输出和完善开发方案
- 更新 `index.md`、`plan.md`、`progress.md`、`meta.yaml`
- 给出实现建议、改动清单、验证建议、风险提示

当任务处于 `方案中` 时，AI 不可以做：
- 直接修改业务代码、配置、SQL、脚本
- 安装依赖、执行迁移、启动正式实现
- 把“先看下/先分析/先给方案/先评估”理解为允许开始开发

只有同时满足以下条件，才允许从 `方案中` 进入 `开发中`：
1. `plan.md` 中的产品方案已经确认
2. `plan.md` 中已经补齐明确的开发方案，达到可执行状态，关键待确认项已经收敛到不影响开工
3. 用户明确表达允许开始代码工作，例如“可以开始开发”“开始改代码”“按这个方案做”

如果用户没有明确授权开始代码工作，即使 AI 已经完成方案分析，也必须停留在 `方案中`。

如果恢复的是一个已存在任务：
- 当状态是 `方案中`，默认继续分析、补方案、补文档，不直接开工编码
- 当状态是 `开发中` 或 `测试中`，可以继续既有实现与验证工作，除非用户明确要求回到方案讨论

### 后端测试环境

适用于 `producer-backend` 任务工作区。优先在当前任务自己的后端仓库根目录运行测试；宿主机依赖不完整时切换到当前任务 Docker app 容器，不要误用共享主仓容器。详细命令见 [runtime.md](references/runtime.md)。

### 前端验证环境

配置为 `patch-node-frontend-environment` 的前端，在 Vitest / `npm run typecheck` / `npm run build:*` 前，先按 [runtime.md](references/runtime.md) 准备项目声明的 Node 版本和当前平台原生 optional 依赖；`sg publish local` 前只做原生 optional 依赖准备，不做完整 runtime prepare。小程序 / 微信开发者工具类前端按项目现有编译、预览或上传流程验证，不因为未执行 runtime prepare 就阻断 review。`@rolldown/binding-darwin-*`、`@typescript/typescript-darwin-*` 缺失默认按本地设备 / Node 架构问题处理，不当成业务代码失败。

### 11. Complete

用于编码和自测完成后标记任务完成。

规则：
- allow complete only from `方案中` / `开发中` / `测试中`
- require each recorded repo to be clean and pushed before marking complete
- before marking complete, try to stop the current task runtime for each bound repo to release occupied local ports or task containers
- if some repo runtime is already not running, just report it and continue; do not block complete only because there is nothing to stop
- keep task docs under `_docs/<task-id>`
- keep task code under `_tasks/<task-id>` until cleanup
- `已完成` 表示当前阶段任务已完成，不等于这个工作空间永久结束；如果后续还要在同一长期主题下做二期，应进入 `next`

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/complete_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 12. Next

用于在同一个任务工作空间内开启下一阶段任务，例如一期上线后继续做二期。

显式命令：

```text
/task-workflow next <新任务名>
/task-workflow next <新任务名> [--bbs-id <编号>] [--repo <repo-key> ...]
```

执行前必须读取 [stages.md](references/stages.md)。

关键边界：
- `next` 是在原工作空间内开启新的阶段任务，不新建任务工作空间
- 用户明确调用 `next` 时，表示先暂停当前阶段并开启下一阶段；不等于确认上一阶段已经完成或已上线
- 允许从 `方案中` / `开发中` / `测试中` / `暂停中` / `已完成` 开启下一阶段
- 当前阶段如果已是 `已完成`，历史阶段保留为 `已完成`；否则历史阶段记录为 `暂停中`，并用 `resume_status` 保存原状态
- 新阶段分支默认基于远程 `master` 最新代码创建，不承接当前本地任务分支
- `--bbs-id` 是选填；新阶段可以指定新的 `bbs_id`，如果不指定，不默认沿用上一阶段的 `bbs_id`
- 阶段化和子任务拆分按用户产品口径判断，不按前端/后端/PC/手机端技术面机械拆分
- 没有子任务时，当前阶段 plan 是当前阶段唯一方案来源；有子任务时，子文档才承接详细方案
- 开启新阶段后，当前阶段状态为 `方案中`、`coding_allowed: false`，等待本阶段方案确认和明确开发指令

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --bbs-id 53850
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo pf-mproducer-supplier
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo 手机前端
```

### 13. Stage

用于在多阶段任务中切回或切换到某个已记录阶段，例如进入二期后临时回到一期分支处理问题。

显式命令：

```text
/task-workflow stage <阶段编号或阶段任务名>
```

执行前必须读取 [stages.md](references/stages.md)。

关键边界：
- `stage` 是阶段切换，不是新建阶段；新建下一阶段仍使用 `next`
- 切换阶段必须同步仓库分支、`meta.yaml` 当前阶段、`active_plan` 和 `index.md`，不要只手动 `git checkout`
- 切换前要求当前仓库工作区干净，且当前分支与 `meta.yaml` 记录分支一致
- 目标阶段必须已经记录全部绑定仓库分支；缺少任一绑定仓库分支时直接阻断
- 目标本地分支不存在时直接阻断，不基于远程分支、`master` 或阶段名重建
- 如果多仓 checkout 中途失败，停止写入 `meta.yaml` 和文档，明确提示已切/未切仓库，让用户确认后再恢复一致状态
- 切换成功后，原当前阶段会进入 `previous_phases`；未完成的原当前阶段记录为 `暂停中`，并保留 `resume_status`
- 如果目标阶段记录为 `暂停中`，切入时恢复到 `resume_status`，例如恢复为 `方案中` / `开发中` / `测试中`

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_stage.py "YYYY-MM-DD-原始任务名" "1"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_stage.py "YYYY-MM-DD-原始任务名" "一期任务名"
```

### 14. Cleanup

用于任务已完成，并且需要清理任务代码目录的时候。

规则：
- require task status = `已完成`
- require each recorded repo to be clean and pushed
- before removing task code, try to stop the current task runtime for each bound repo to avoid leaving old ports or task containers behind
- if some repo runtime is already not running, just report it and continue cleanup
- remove `_tasks/<task-id>`
- never delete `_docs/<task-id>`
- 如果后续仍可能在同一工作空间上进入 `next`，不要急于 cleanup

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/cleanup_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 15. Status

用于用户想快速查看任务状态和任务仓库路径。

状态输出应包含：
- all known tasks and their current status
- each repo bound to each task
- each repo path and recorded branch
- whether the repo path still exists

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/status_task_workspace.py
```

### 16. Portal

用于在浏览器里快速查看当前开发中任务对应的手机端、PC 端和后端端口，不再手工记忆任务与端口的映射关系。

常用入口：

1. 静态快照页

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/render_task_dev_portal.py
```

默认输出：
- `/Users/wuyongli/Documents/sg-project/_workspace/task-dev-portal.html`

2. 刷新即最新的本地页

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/serve_task_dev_portal.py
```

默认地址：
- `http://127.0.0.1:8765/`

关键规则：
- 页面数据来自 `_docs/*/meta.yaml`、前端 `.codex/task-runtime.env`、后端 `docker/.task.env`
- 手机端地址默认展示为 `http://pfzone.senguo.me:<port>/mproducer/`
- PC 端地址默认展示为 `http://pfzone.senguo.me:<port>/producer/`
- 如果你只想手动刷新页面拿到最新状态，用本地页即可；浏览器每次刷新都会重新读取最新任务、分支和端口
- 如果只需要一个可分享或临时保存的快照页，再使用静态导出脚本

## 文档模型与运行配置

- 本文件用于路由任务和确认关键边界；涉及细节时按场景读取 reference
- 当需要更新任务文档、拆分方案、处理 `meta.yaml` 或判断文档职责时，读取 [docs-model.md](references/docs-model.md)
- 当用户表达分阶段、一二期、开启下一阶段或拆产品子任务时，读取 [stages.md](references/stages.md)
- 当用户表达切回上一阶段、切到某一期、回到历史阶段处理问题时，使用 `switch_task_stage.py`，不要只手动 `git checkout`
- 当需要发布或同步远程主线时，读取 [publish-sync.md](references/publish-sync.md)
- 当需要创建合并请求时，读取 [publish-sync.md](references/publish-sync.md)，先确认当前 `sg pr` 支持所需能力，再使用 `sg pr`，不改用其他 PR 客户端
- 当需要清理任务仓库的本地 `develop` 分支时，使用 `clean_develop_task_workspace.py`，不要操作远程 `origin/develop`
- 当需要准备 runtime、解释 `repositories.yaml` / `workspace.yaml` 字段、处理后端测试环境时，读取 [runtime.md](references/runtime.md)
- 当需要切换本地共享 MySQL 数据目录时，使用 `switch_task_mysql.py`，不要把切库动作混入普通后端启动

## 输出约束

当用户要求创建或继续任务时，回复应聚焦于：
- 当前识别到的任务
- 涉及哪些仓库
- 下一步动作是什么

当用户要求发布时，回复应聚焦于：
- 按 [publish-sync.md](references/publish-sync.md) 输出任务、目标、仓库、命令、成功信号、失败错误和分支状态

当用户要求同步远程主线时，回复应聚焦于：
- 按 [publish-sync.md](references/publish-sync.md) 输出任务、目标、仓库、同步动作、成功结果、失败错误或冲突信息

当用户要求创建合并请求时，回复应聚焦于：
- 当前识别到的任务、目标仓库、`meta.yaml` 记录的源分支和远程默认目标分支
- 已有 PR 检查、工作区和分支核验结果
- 是否执行了源分支首次推送，以及 `sg pr create` 的结果、PR 编号和链接

当用户要求删除本地 `develop` 分支时，回复应聚焦于：
- 当前识别到的任务和目标仓库
- 哪些仓库已删除本地 `develop`
- 哪些仓库本来就没有本地 `develop`
- 哪些仓库因为当前正在 `develop` 或 git 错误而失败

当用户要求切换本地 MySQL 时，回复应聚焦于：
- 目标后端、当前数据目录、目标数据目录
- 是否 no-op 或已执行 `docker compose up -d --force-recreate mysql`
- 是否需要重启当前任务后端 app

当用户要求代码审查时，回复应聚焦于：
- 当前识别到的任务、目标仓库和 review 基线
- 是否发现并应用项目级 review 规则
- 按 `阻塞问题 / 明确缺陷`、`非阻塞风险`、`代码质量优化`、`测试代码收敛`、`验证建议` 分层输出
- 先输出 `审查总览：🔴 阻塞`、`审查总览：🟡 有注意项` 或 `审查总览：🟢 完全通过`；绿色只表示完全没有问题或验证已通过，有建议/风险/未验证项时必须用黄色
- 各层级标题使用聚合状态点，每条明细也单独使用红 / 黄 / 绿状态点标记
- 未发现阻塞问题不等于没有优化空间；不要把“未发现阻塞问题”简写成“没有问题”
- 没有内容的层级可以用一行 `🟢 未发现` 收起，但不能省略代码质量优化和测试收敛 pass
- findings 按严重程度排序，包含文件/行号、问题、影响和建议
- 是否阻塞上线或进入发布

发布场景下的协作约束：
- 不要把内部脚本实现、通用化改造、命名抽象这类 agent 内部设计过程再次抛给用户确认
- 如果用户已经明确表达发布意图，应直接按 [publish-sync.md](references/publish-sync.md) 识别任务、匹配目标并执行
- 只有在发布目标无法匹配、任务上下文不明确、或存在真实执行风险时，才向用户补充提问

同步场景下的协作约束：
- 不要把“准备怎么 merge、怎么解冲突、要不要顺手修代码”这类后续动作自动串进去
- 如果同步失败，默认停在“展示失败仓库和错误信息”这一步，等用户确认后再继续处理

创建合并请求场景下的协作约束：
- 不要把 `sg pr create` 改为 `glab`、`gitlab` 或未知的第三方客户端
- 没有明确创建授权时，只能用 `sg pr status`、`list` 或 `view` 查询，不创建 PR
- 不要因为创建 PR 而自动提交、修改现有 PR、合并 PR 或删除分支

审查场景下的协作约束：
- 不要只输出泛泛建议；必须基于真实 diff、真实项目规则和真实代码路径给结论
- 不要把大 diff 从头线性扫完当作认真；先收敛到任务相关路径和当前 patch，再决定是否扩散
- 不要因为没有发现阻塞问题就省略测试收敛 pass；测试代码价值判断是 review 的固定组成部分
- 不要因为没有发现阻塞问题就省略代码质量优化 pass；只列有明确维护成本、容易误用、低成本可修的优化点，不列纯风格偏好
- 不要把“可能有问题”包装成明确 bug；明确 bug、风险、待确认项要分开
- 如果用户只要求 review，默认不改代码；如果用户授权修明确问题，仍然只修明确问题

在工作流已经建立后，不要反复解释目录树结构或 Git 基础概念。
