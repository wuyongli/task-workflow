---
name: task-workflow
description: Use when the user mentions 新任务、多仓库任务、任务工作区、继续任务、恢复任务上下文、任务进度、任务完成, or needs to create, continue, pause, resume, complete, clean up, or inspect a multi-repo task under /Users/wuyongli/Documents/sg-project/_workspace.
---

# 任务工作流

## 概览

这个 skill 用于 `/Users/wuyongli/Documents/sg-project/_workspace` 下按任务隔离的多仓库 clone 工作流。

核心模型：
- 一个任务 = 一个文档目录 + 一个任务代码目录
- 任务文档放在 `_docs/<task-id>`
- 仓库真实 clone 放在 `_tasks/<task-id>/<repo>__<task-name>`
- 任务绑定以路径名为准，不以分支名为准

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
4. 基于远端默认分支创建或重置任务分支
5. 从主仓库或任务仓库模板补齐缺失的本地运行配置
6. 生成 `index.md`、`plan.md`、`progress.md`、`meta.yaml`

路径绑定规则：
- 优先通过当前路径 `_tasks/<task-id>/...` 识别任务
- 再从 `_docs/<task-id>` 加载文档
- 文档里记录的分支只作为一致性校验，不作为主绑定依据

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/create_task_workspace.py "原始任务名" --repo producer-backend --repo pf-mproducer-supplier
```

运行说明：
- `create_task_workspace.py` will only补齐缺失的本地运行配置，不会覆盖 task clone 里已有文件
- 不会自动安装依赖
- 对于 `producer-backend`，还会生成任务级 Docker 辅助文件，让每个任务都能只启动自己的 `app` 容器，同时复用共享基础设施
- 当 `repositories.yaml` 开启 `auto_start_on_prepare` 时，运行配置准备阶段也会执行配置里的自动启动步骤
- 如果主仓本地配置后续发生变化，可以重新执行：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/prepare_task_runtime.py "YYYY-MM-DD-原始任务名"
```

### 3. Load

用于在新会话里恢复任务上下文。

默认读取顺序：
1. `index.md`
2. 当需要任务目标或方案细节时读 `plan.md`
3. 当需要当前进展、自测结果或阻塞时读 `progress.md`

路径查找规则：
- 如果当前仓库路径匹配 `_tasks/<task-id>/<repo-dir>`，就直接从 `<task-id>` 反查任务
- 然后去 `_docs/<task-id>` 读取文档
- 如果当前分支和文档记录不一致，需要显式指出，并在合适时更新文档

### 4. Progress

用于任务已经推进，文档也需要同步更新的时候。

更新规则：
- `index.md` 只保留当前快照
- `plan.md` 只保留当前有效方案
- `progress.md` 记录实际进展、验证结果、阻塞与变更历史

任务状态固定为：
- `方案中`
- `开发中`
- `测试中`
- `暂停中`
- `已完成`

### 5. Pause

用于任务暂停一段时间，但不删除任务代码。

规则：
- allow pause only from `方案中` / `开发中` / `测试中`
- pause only changes task status and keeps all task repos in place

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/pause_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 6. Resume

用于暂停中的任务继续恢复开发。

规则：
- allow resume only from `暂停中`
- resume only restores task status; repos stay in the same task path

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/resume_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 7. Complete

用于编码和自测完成后标记任务完成。

规则：
- allow complete only from active statuses or `暂停中`
- require each recorded repo to be clean and pushed before marking complete
- keep task docs under `_docs/<task-id>`
- keep task code under `_tasks/<task-id>` until cleanup

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/complete_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 8. Cleanup

用于任务已完成，并且需要清理任务代码目录的时候。

规则：
- require task status = `已完成`
- require each recorded repo to be clean and pushed
- remove `_tasks/<task-id>`
- never delete `_docs/<task-id>`

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/cleanup_task_workspace.py "YYYY-MM-DD-原始任务名"
```

### 9. Status

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

## 文档模型

文档约束：
- task markdown files are fixed to `index.md`, `plan.md`, and `progress.md` by default
- do not create extra task markdown files unless the user explicitly asks for them
- if `plan.md` feels too large, reorganize headings inside `plan.md` instead of creating files like `implementation-plan.md`, `todo.md`, or `notes.md`
- if unexpected extra task markdown files already exist, merge valid content back into `plan.md` or `progress.md` when appropriate
- treat `plan.md` as the single source of truth for goals, solution decisions, execution plan, and validation plan
- treat `progress.md` as the single source of truth for actual work done, verification results, and blockers

### `index.md`

用途：
- AI 恢复上下文时的第一入口
- 只保留当前快照

必须包含：
- current status
- one-line goal
- current conclusion
- current blocker
- next step
- recorded repo paths and actual branches
- links to `plan.md` and `progress.md`

使用模板：[index.md](references/index.md)

### `plan.md`

用途：
- 产品方案和开发方案放在一个地方
- 只保留当前有效方案，不保留讨论过程

使用模板：[plan.md](references/plan.md)

### `progress.md`

用途：
- 实际执行状态
- 自测结果
- 供后续恢复上下文使用的最小历史

使用模板：[progress.md](references/progress.md)

### `meta.yaml`

用途：
- 通过路径把一个文档目录和一个任务代码目录绑定起来
- 记录最小的、可机器读取的仓库绑定与分支信息

规则：
- `meta.yaml` 是任务绑定的机器可读事实来源
- 优先记录 `repo_dir` 或相对任务路径；绝对路径只保留兼容用途
- `index.md` 保持可读，但其中的路径和分支必须和 `meta.yaml` 一致
- `meta.yaml` 尽量最小化，只保留 `task_id`、任务状态、以及每个仓库的 `key`、`repo_dir`、`branch`

## 运行配置

### `repositories.yaml`

用于保存可复用的仓库注册表。

每个仓库项应包含：
- `key`: stable repo key, usually the directory name
- `path`: main repo path under `/Users/wuyongli/Documents/sg-project`
- `remote`: clone URL when needed
- `notes`: optional brief remarks
- `runtime`: optional runtime bootstrap rules for task clones

`runtime` 支持：
- `mode`: optional runtime preset such as `shared-backend-app`
- `copy_missing_from_main`: copy listed relative paths from the main repo only when the task clone is missing them
  - useful for local-only startup files such as `.codex/environments/environment.toml`
- `copy_missing_from_template`: create missing files inside the task clone from repo-local templates such as `settings_local.py -> settings.py`
- `environment_toml`: optional task repo startup file path for frontend runtime patching
- `task_env_file` / `task_compose_file`: generated helper files for backend runtime presets
- `task_port_key`: optional env key name stored in the task runtime env file for frontend port pinning
- `task_app_image`: optional local image tag to reuse for backend task app containers before falling back to per-task builds
- `auto_start_on_prepare` / `auto_start_steps`: optional startup automation after runtime files are ready
- each auto-start step may optionally use `allow_failure: true` when a non-critical local service should not block later steps
- `install_commands`: commands to install dependencies
- `start_commands`: commands to start the repo locally
- `notes`: short runtime remarks for the agent

模板：[repositories.yaml.example](references/repositories.yaml.example)

### `workspace.yaml`

用于保存工作区级别规则。

应包含：
- workspace root
- tasks root
- docs root
- config root
- task naming rule
- repo directory naming rule
- branch sanitization rule
- clone source mode
- cleanup safety policy
- default document filenames

模板：[workspace.yaml.example](references/workspace.yaml.example)

## 输出约束

当用户要求创建或继续任务时，回复应聚焦于：
- what task was identified
- which repos are involved
- what the next action is

在工作流已经建立后，不要反复解释目录树结构或 Git 基础概念。
