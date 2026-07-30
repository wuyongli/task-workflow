# 发布与同步

## 目标识别

`publish` / `sync` / `clean-develop` 共用目标识别规则：
- 默认从当前任务上下文识别当前要操作的任务，不额外要求用户重复提供 task 标识
- 如果当前上下文无法唯一识别任务，才向用户补充确认
- 目标表达的核心是“目标分类”，不是固定仓库名；执行时需要在当前任务绑定仓库里动态匹配对应的后端、手机前端、PC 前端仓库
- 常见说法包括 `后端`、`手机前端`、`PC前端`、`前端`
- 如果用户只说“前端”，且当前任务里只有一个前端仓库，可以直接匹配；如果同时存在手机前端和 PC 前端，则应要求用户明确

## Publish

显式命令：

```text
/task-workflow publish [目标1] [目标2] [目标3...]
```

规则：
- 用户显式输入 `/task-workflow publish ...` 时，视为已授权直接执行发布动作
- 默认不指定目标时，发布当前任务下全部绑定仓库
- 一次可以传多个目标
- 一次多个目标时，先统一识别并校验目标，再并行发布
- 发布前先校验任务绑定仓库是否存在，以及当前分支是否与 `meta.yaml` 记录分支一致
- 如果上一次发布已把仓库停在 `develop` 冲突处理或冲突解决后的重试状态，允许从 `develop` 继续发布，不要强制切回任务分支
- 前端发布不能只看 `sg publish local` 的退出码；应优先以终端输出里的 `发布成功` 作为成功信号，CLI 日志只作为失败证据和辅助判断
- 后端发布也应优先看终端中的明确成功信号；如果没有明确成功信号，或 CLI 日志记录为失败，就不能汇报为 `OK`
- 某个目标发布失败时，不应阻断其它目标；应继续完成其它目标，并明确展示失败仓库的错误信息
- 普通发布失败后，默认停在“展示失败信息”这一步，不自动进入修代码、补提交或重试发布
- 如果失败原因是工作区不干净、分支异常或发布命令本身报错，默认只反馈事实，不自行修复，除非用户明确要求继续处理

固定命令：
- 后端仓库：`sg publish jenkins`
- 前端仓库：`sg publish local`

### `develop` 冲突

- `sg publish` 在合入 `develop` 发布阶段留下本地合并冲突时，不按普通发布失败处理
- `develop` 发布冲突必须保留冲突现场：不要 `merge --abort`，不要切回任务分支，不要尝试在任务分支解决这个冲突
- `develop` 发布冲突优先由 AI 在当前 `develop` 工作区自动解决；只有冲突语义、业务口径或保留策略不明确时，才停下来问用户
- 解决 `develop` 冲突后，先运行与冲突文件相关的最小验证；验证通过后，从当前 `develop` 状态重新发布
- 从 `develop` 重试发布成功后，必须切回 `meta.yaml` 记录的任务分支，避免后续开发误改 `develop`
- 如果发布成功但切回任务分支失败，应明确报错并停止，不要把任务汇报为完全完成

## Sync

显式命令：

```text
/task-workflow sync [目标1] [目标2] [...]
```

规则：
- 默认不指定目标时，同步当前任务下全部绑定仓库
- 指定目标时，继续使用和 publish 一样的自然语言目标识别方式
- 多仓库同步默认并行执行，不强调顺序
- 每个仓库同步前先检查当前分支是否与 `meta.yaml` 记录分支一致
- 如果某个仓库有未提交的本地改动，不继续同步该仓库，应直接展示该仓库的 `git status --short` 结果
- 同步过程默认先 `fetch origin --prune`，再把远程默认分支合入当前任务分支
- 如果同步过程中出现冲突、工作区异常、分支异常或 git 命令报错，只反馈事实和错误信息，不自动修代码、不自动解冲突、不自动继续处理
- 某个仓库同步失败时，不阻断其它仓库；其它仓库继续执行，最后统一汇总成功和失败

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/sync_task_workspace.py "YYYY-MM-DD-原始任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/sync_task_workspace.py "YYYY-MM-DD-原始任务名" 后端 手机前端
```

## Clean Develop

用于发布前删除任务仓库里的本地 `develop` 分支，避免后续 `sg publish` 合入远程 `develop` 前受到落后的本地 `develop` 影响。

显式命令：

```text
/task-workflow clean-develop [目标1] [目标2] [...]
```

规则：
- 只删除本地 `develop` 分支，不删除、不推送、不改动远程 `origin/develop`
- 默认不指定目标时，处理当前任务下全部绑定仓库
- 指定目标时，继续使用和 publish / sync 一样的自然语言目标识别方式
- 多仓库默认并行执行，不强调顺序
- 某个仓库没有本地 `develop` 分支时，视为 no-op，不影响其它仓库
- 如果某个仓库当前分支就是 `develop`，不删除该仓库的本地 `develop`；先输出当前分支状态，等待用户或 AI 切走后再重试
- 删除失败时，只展示失败仓库和 git 错误信息，不自动切分支、不自动修复工作区

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/clean_develop_task_workspace.py "YYYY-MM-DD-原始任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/clean_develop_task_workspace.py "YYYY-MM-DD-原始任务名" 后端 手机前端
```

## 输出要求

发布时聚焦：
- 当前识别到的任务
- 将发布哪些目标
- 每个目标对应的仓库目录和发布命令
- 发布结果，以及失败仓库的错误信息
- 如果发布停在 `develop` 合并冲突，说明当前分支、冲突文件、已自动解决的内容、最小验证结果、重试发布结果，或需要用户确认的问题
- 如果从 `develop` 重试发布成功，说明是否已经切回任务分支；若切回失败，说明当前分支、目标分支和 `git status`

同步时聚焦：
- 当前识别到的任务
- 将同步哪些仓库
- 每个仓库的当前分支和同步动作
- 成功结果，以及失败仓库的错误信息或冲突信息

清理本地 `develop` 时聚焦：
- 当前识别到的任务
- 将处理哪些仓库
- 已删除本地 `develop` 的仓库
- 本来就没有本地 `develop` 的仓库
- 因当前正在 `develop` 或 git 错误导致失败的仓库
