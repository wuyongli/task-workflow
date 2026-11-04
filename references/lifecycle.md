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

用于任务已完成，并且需要清理任务代码目录的时候。

规则：
- 任务状态必须是 `已完成`
- 每个记录仓库都必须工作区干净，且当前分支与 `meta.yaml` 记录分支一致
- `cleanup` 不校验 upstream，也不关心远程任务分支是否仍存在；上线后远程任务分支被删除属于正常场景
- 如果仓库仍有可比较的 upstream，且本地存在未推送提交，阻断 cleanup，避免删除唯一代码副本
- 删除任务代码前，先清理每个绑定仓库的当前任务 runtime，避免遗留旧端口或已无法使用的任务 `app` 容器
- 对于 `shared-backend-app`，`cleanup` 只删除当前任务专属的后端 `app` 容器
- `cleanup` 不得删除共享 Docker 服务、Docker volume、MySQL 数据目录、镜像、任务文档、远程分支或源仓库
- 如果某个仓库的 runtime 已经没有运行，只说明现状并继续清理
- 删除 `_tasks/<task-id>`
- 不删除 `_docs/<task-id>`
- 如果后续仍可能在同一工作空间上进入 `next`，不要急于 cleanup

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/cleanup_task_workspace.py "YYYY-MM-DD-原始任务名"
```

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
