# 任务生命周期

用于工作区初始化、任务创建、完成、清理和状态查询。按实际动作读取对应章节；恢复与进度更新见 [docs-model.md](docs-model.md)，开发准入由 [SKILL.md](../SKILL.md) 定义。

## Init

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

## Create

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
- `create_task_workspace.py` 只补齐缺失的本地运行配置，不会覆盖任务 clone 里已有文件
- `--bbs-id` 是选填；用户提供内部需求反馈编号时才写入 `meta.yaml` 和初始文档，不提供时不生成空编号占位
- 不会自动安装项目业务依赖；`producer-backend` 仅会为任务 app 容器补齐必要测试工具
- 任务分支只以远端默认分支作为起点，不自动跟踪 `origin/master` 或其他默认分支；首次推送任务分支时再建立自己的 upstream
- 如果用户一开始就明确“一期 / 二期 / 分阶段 / 先做 A 再做 B”，从创建任务开始读取 [stages.md](stages.md)，按阶段化文档模型处理
- 对于配置为 `shared-backend-app` 的后端，会生成任务及仓库级 Docker 辅助文件；同一任务的多个后端各自启动独立 `app` 容器，同时复用共享基础设施
- 对于配置为 `shared-backend-app` 的后端，任务 app 启动后会检查容器内是否可用 `pytest`；缺失时自动安装 `pytest==7.4.4`
- 当 `repositories.yaml` 开启 `auto_start_on_prepare` 时，运行配置准备阶段也会执行配置里的自动启动步骤
- 对于配置为 `patch-node-frontend-environment` 的前端，运行配置准备阶段会检查并修复当前 Node 平台缺失的原生 optional 依赖；这是本地环境准备，不是业务代码改动
- 如果主仓本地配置后续发生变化，可以重新执行：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/prepare_task_runtime.py "YYYY-MM-DD-原始任务名"
```

## Complete

用于编码和自测完成后标记任务完成。

规则：
- 只允许从 `方案中` / `开发中` / `测试中` 标记完成
- 标记完成前，每个记录仓库都必须工作区干净，并且已推送到远程
- 标记完成前，尝试停止每个绑定仓库的当前任务 runtime，释放本地端口或任务容器
- 如果某个仓库的 runtime 已经没有运行，只说明现状并继续；不要因为无可停止内容阻断完成
- `complete` 只停止任务 runtime，不删除任务代码目录，也不删除 Docker 容器
- 保留 `_docs/<task-id>` 下的任务文档
- 保留 `_tasks/<task-id>` 下的任务代码，直到显式执行 `cleanup`
- `已完成` 表示当前阶段任务已完成，不等于这个工作空间永久结束；如果后续还要在同一长期主题下做二期，应进入 `next`

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/complete_task_workspace.py "YYYY-MM-DD-原始任务名"
```

## Cleanup

用于任务已完成，或用户决定不再继续开发，需要清理任务代码目录的时候。

规则：
- 允许从 `方案中` / `开发中` / `测试中` / `暂停中` / `已完成` 直接执行；不恢复暂停状态、不调用 `complete`，也不把放弃开发写成已完成。仓库预检通过后，未完成任务及当前阶段转为 `暂停中`，用 `resume_status` 保留原状态并置 `coding_allowed: false`，同步 index，避免自动调度继续派发。原本暂停的任务保留恢复状态，已完成任务保持已完成；不改变执行模式或历史阶段状态。
- 默认每个记录仓库都必须工作区干净，且当前分支与 `meta.yaml` 记录分支一致。
- `cleanup` 不要求 upstream 或远程任务分支仍然存在；上线后远程任务分支被删除属于正常场景。
- 默认检查 clone 内所有本地分支（包括历史阶段分支）；分支仍有可比较的 upstream，且本地存在未推送提交时，阻断 cleanup，避免删除唯一代码副本。没有 upstream 或远程分支已删除时延续既有规则，不以此阻断；这不代表已证实全部代码推送。
- 用户明确“放弃这个任务并清理 / 本地改动也不要了”等丢弃意图时，可直接使用 `--discard-local-changes`，允许删除未提交、未跟踪、被忽略的文件及未推送提交，无需先提交或推送，也不重复确认既有授权。只有一般“cleanup / 清理”且发现受保护改动时，列出受影响仓库并确认是否丢弃；未完成或暂停本身不构成再次确认的理由。
- `--discard-local-changes` 仅放宽本地成果保护，不放宽任务路径、仓库存在性和记录分支校验。所有仓库预检通过后才开始清理 runtime 和代码；预检失败保留现场，不 reset、切分支或伪造状态绕过。
- 删除任务代码前，先清理每个绑定仓库的当前任务 runtime，避免遗留旧端口或已无法使用的任务 `app` 容器
- 对于 `shared-backend-app`，`cleanup` 只删除当前任务专属的后端 `app` 容器
- `cleanup` 不得删除共享 Docker 服务、Docker volume、MySQL 数据目录、镜像、任务文档、远程分支或源仓库
- 如果某个仓库的 runtime 已经没有运行，只说明现状并继续清理
- 删除整个 `_tasks/<task-id>`，包括该任务各阶段在本地 clone 中的全部分支和文件；不是只删除当前阶段。涉及历史阶段仍需保留的本地成果时，先保留所需成果，或取得覆盖这些成果的明确丢弃授权。
- 不删除 `_docs/<task-id>`
- 如果后续仍可能在同一工作空间上进入 `next`，不要急于 cleanup

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/cleanup_task_workspace.py "YYYY-MM-DD-原始任务名"
```

明确放弃本地成果时：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/cleanup_task_workspace.py "YYYY-MM-DD-原始任务名" --discard-local-changes
```

添加 `--dry-run` 仅预览检查及清理动作，不删除文件或容器。输出应说明实际清理范围、是否丢弃本地成果和文档保留位置；清理成功不代表任务完成或验收通过。放弃任务的原因及清理结果可按真实情况记入 `progress.md`；恢复上下文时应先说明代码已清理，不自动重建或继续开发。

## Status

用于用户想快速查看任务状态和任务仓库路径。

状态输出应包含：
- 所有已知任务及当前状态
- 每个任务绑定的仓库
- 每个仓库路径和记录分支
- 仓库路径是否仍然存在

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/status_task_workspace.py
```

## 输出

创建或继续任务时，聚焦当前识别到的任务、涉及仓库和下一步动作。在工作流已经建立后，不反复解释目录树或 Git 基础概念。
