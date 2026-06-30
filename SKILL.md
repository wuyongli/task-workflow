---
name: task-workflow
description: "Use when the user works with /Users/wuyongli/Documents/sg-project/_workspace task workspaces: create/load/continue tasks, update progress, review/codeview changes, consolidate tests, publish, sync remote master, inspect task dev URLs or ports, open next-stage work, complete, or clean up."
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

文档分层：
- `meta.yaml`：机器事实，只记录状态、分支、当前阶段、当前主计划等可恢复信息
- `index.md`：人读快照，只保留当前状态、当前结论、当前阻塞、下一步和导航
- `plan.md`：当前有效方案，只保留已经成立的方案结论、核心决策原因、开发方案、数据变更和上线方案
- `progress.md`：执行记录，只记录实际做了什么、验证了什么、发布了什么、阻塞和下一步
- `decision-log.md`：可选历史推导附录；只在候选方案很多、口径反复变化、未来需要回看“为什么没选另一条路”时再拆出
- `*-plan.md` / `appendix-*.md`：仅承接稳定的模块子方案或参考资料，不承接讨论流水

文档职责边界：
- 当前应该按什么方案做，写入 `plan.md`
- 实际推进到了哪一步，写入 `progress.md`
- 当时为什么这样取舍，先用 `plan.md` 的“核心决策与原因”收口；只有历史推导太长时才拆 `decision-log.md`
- 当前状态和下一步入口摘要，写入 `index.md`
- 脚本和 AI 恢复上下文所需的机器事实，写入 `meta.yaml`

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
```

运行说明：
- `create_task_workspace.py` will only补齐缺失的本地运行配置，不会覆盖 task clone 里已有文件
- 不会自动安装项目业务依赖；`producer-backend` 仅会为任务 app 容器补齐必要测试工具
- 任务分支只以远端默认分支作为起点，不自动跟踪 `origin/master` 或其他默认分支；首次推送任务分支时再建立自己的 upstream
- 对于 `producer-backend`，还会生成任务级 Docker 辅助文件，让每个任务都能只启动自己的 `app` 容器，同时复用共享基础设施
- 对于 `producer-backend`，任务 app 启动后会检查容器内是否可用 `pytest`；缺失时自动安装 `pytest==7.4.4`
- 当 `repositories.yaml` 开启 `auto_start_on_prepare` 时，运行配置准备阶段也会执行配置里的自动启动步骤
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
6. 当需要理解“为什么这样定”时，先读 `plan.md` 的核心决策与原因；只有存在独立 `decision-log.md` 时再读历史推导

恢复任务时的协作原则：
- `meta.yaml` 是 AI 恢复上下文时的第一事实入口，不是补充校验文件
- `index.md` 是给人读的摘要页，不负责定义机器事实
- 如果 `index.md` 与 `meta.yaml` 不一致，优先以 `meta.yaml` 为准，再在同一轮把摘要文档修正到一致
- 如果没有先读 `meta.yaml`，就不要声称已经完成任务状态核对、仓库绑定核对或记录分支核对
- 如果任务已经进入多阶段模式，先用 `meta.yaml` 确认当前阶段、当前分支、当前 plan，再用 `index.md` 理解当前阶段与历史阶段的关系

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
6. 如果候选方案、反复改口或历史推导明显过长，再拆或更新 `decision-log.md`，并把当前有效结论回写到 `plan.md`

更新原则：
- `index.md` 只保留当前快照
- `plan.md` 只保留当前有效方案、核心决策原因和执行依据
- `progress.md` 只记录实际进展、验证结果、发布记录、阻塞与变更历史
- `decision-log.md` 只在必要时作为可选附录保留关键讨论、候选方案和取舍原因
- `meta.yaml` 保存最小机器事实
- 不允许让 `index.md` 比 `meta.yaml` 更“新”
- 更新文档时，优先整段重写当前章节并归并重复内容，不要只在原文后面继续追加碎片信息
- 如果某个结论、方案或进展已经被新内容替代，应直接覆盖旧表述，而不是保留多个版本并列
- `plan.md` 和 `index.md` 默认维护“当前有效版本”；只有 `progress.md` 的“变更记录”和可选 `decision-log.md` 适合追加历史条目
- 不要把多轮讨论细节、搜索过程、候选方案并列长期保留在 `plan.md`
- 不要把当前有效的方案判断长期放在 `progress.md`；如果某个判断会指导开发或上线，应回写到 `plan.md`
- 不要为了“怕丢”就默认新建 `decision-log.md`；多数任务只需要把当前结论和原因收敛到 `plan.md`
- 如果目标章节已有同义内容，先归并并重写原章节，再写新的当前口径；不要在原文后追加一个平行版本
- 不要把运维噪音、启动端口、白屏排查等运行细节写进 `progress.md`
- 如果任务只是初始讨论阶段，`plan.md` 默认使用种子版结构，只保留已有内容，不保留大量空骨架
- 只有当任务真的进入深入方案阶段，才把种子版 `plan.md` 扩展为正式版结构

任务状态固定为：
- `方案中`
- `开发中`
- `测试中`
- `已完成`

`plan.md` 两段式规则：
- 种子版：适用于新任务或仅做了初步讨论的任务，只保留“当前阶段收口 / 当前目标 / 当前初步判断 / 当前系统现状评估 / 影响范围与数据判断 / 开发准入确认 / 待确认事项 / 参考信息”
- 正式版：适用于已经进入深入方案阶段的任务，扩展出“当前有效方案 / 核心决策与原因 / 项目惯例与复用结论 / 开发方案 / 数据变更与上线方案 / 验证与风险”等章节
- 从种子版转正式版，至少要满足：需求成立性已确认、主改仓已明确、范围边界基本稳定、数据变更与上线判断已有初稿，并且已准备进入开发方案或用户要求完整方案
- 从种子版扩为正式版时，优先直接重写结构，不保留原有大段空骨架
- 如果任务涉及后端表 / 字段 / 索引调整，正式版 `plan.md` 的数据变更与上线方案优先沿用 `product-copilot-rules` 定义的统一格式，不再按任务临时发明新写法

### 5. Publish

用于本地开发和验收完成后，把当前任务的指定仓库发布到测试服。

显式命令：

```text
/task-workflow publish <目标1> [目标2] [目标3...]
```

用户可以直接用自然语言描述发布目标。

常见说法示例：
- `后端`
- `手机前端`
- `PC前端`
- `前端`

`publish` / `sync` 共用目标识别规则：
- 默认从当前任务上下文识别当前要操作的任务，不额外要求用户重复提供 task 标识
- 如果当前上下文无法唯一识别任务，才向用户补充确认
- 目标表达的核心是“目标分类”，不是固定仓库名；执行时需要在当前任务绑定仓库里动态匹配对应的后端、手机前端、PC 前端仓库
- 如果用户只说“前端”，且当前任务里只有一个前端仓库，可以直接匹配；如果同时存在手机前端和 PC 前端，则应要求用户明确

`publish` 规则：
- 用户显式输入 `/task-workflow publish ...` 时，视为已授权直接执行发布动作
- 一次可以传多个目标
- 一次多个目标时，先统一识别并校验目标，再并行发布
- 发布前先校验任务绑定仓库是否存在，以及当前分支是否与 `meta.yaml` 记录分支一致
- 如果上一次发布已把仓库停在 `develop` 冲突处理或冲突解决后的重试状态，允许从 `develop` 继续发布，不要强制切回任务分支
- 前端发布不能只看 `sg publish local` 的退出码；应优先以终端输出里的 `发布成功` 作为成功信号，CLI 日志只作为失败证据和辅助判断；如果没有明确成功信号，或 CLI 日志记录为失败，就不能汇报为 `OK`
- 某个目标发布失败时，不应阻断其它目标；应继续完成其它目标，并明确展示失败仓库的错误信息
- 普通发布失败后，默认停在“展示失败信息”这一步，不自动进入修代码、补提交或重试发布
- `sg publish` 在合入 `develop` 发布阶段留下本地合并冲突时，不按普通发布失败处理
- `develop` 发布冲突必须保留冲突现场：不要 `merge --abort`，不要切回任务分支，不要尝试在任务分支解决这个冲突
- `develop` 发布冲突优先由 AI 在当前 `develop` 工作区自动解决；只有冲突语义、业务口径或保留策略不明确时，才停下来问用户
- 解决 `develop` 冲突后，先运行与冲突文件相关的最小验证；验证通过后，从当前 `develop` 状态重新发布
- 如果失败原因是工作区不干净、分支异常或发布命令本身报错，默认只反馈事实，不自行修复，除非用户明确要求继续处理

发布命令固定为：
- 后端仓库：`sg publish jenkins`
- 前端仓库：`sg publish local`

### 6. Sync

用于任务周期较长时，把当前任务下的仓库同步远程主线代码，避免和主线落后太多。

显式命令：

```text
/task-workflow sync [目标1] [目标2] [...]
```

目标表达方式与 publish 相同：
- 默认不指定目标时，同步当前任务下全部绑定仓库
- 指定目标时，继续使用和 publish 一样的自然语言目标识别方式，例如 `后端`、`前端`、`手机前端`、`PC前端`

`sync` 规则：
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

### 7. Review

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

### 8. Complete

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

### 9. Next

用于在同一个任务工作空间内开启下一阶段任务，例如一期上线后继续做二期。

显式命令：

```text
/task-workflow next <新任务名>
/task-workflow next <新任务名> --repo <repo-key> [--repo <repo-key> ...]
```

规则：
- `next` 不是“继续原任务”，而是在原工作空间内开启一个新的阶段任务
- 默认只在当前阶段已经完成或已上线后使用
- 默认要求当前记录仓库工作区干净，避免把上一阶段的未收敛状态带入下一阶段
- 不要求上一阶段本地分支仍保留 upstream；任务上线后原远程任务分支已删除属于正常场景
- 默认为新阶段新建 `plan-<阶段任务名>.md`
- 新阶段的当前有效取舍结论写到阶段 plan；只有当前阶段讨论明显过长时，再额外拆 `decision-log-<阶段任务名>.md`
- `index.md` 只指向当前生效的阶段计划；历史阶段信息保留在 `meta.yaml.previous_phases`
- 默认复用原 task id、原 `_tasks/<task-id>` 代码目录、原 `_docs/<task-id>` 文档目录；不要因为开启下一阶段就新建任务工作空间
- 新阶段分支默认一律基于远程 `master` 最新代码创建，不承接当前本地任务分支
- 如果本阶段只涉及当前任务绑定仓库中的部分仓库，允许只切这些仓库到新阶段分支；未选中的仓库继续保留原分支
- 当用户明确说“只需要手机前端/PC 前端/后端中的一部分仓库”时，优先使用 `next` 的部分仓库模式，而不是退回 `create`
- `next --repo` 同时支持 repo key 和自然目标名称；例如 `pf-mproducer-supplier`、`手机前端`、`PC前端`、`后端`
- 新阶段应新建独立 plan 文档，不继续在上一阶段 plan 上叠加
- 新阶段 plan 文件名应优先使用新任务名、分支语义或当前任务描述，不使用抽象命名如 `plan-phase-2.md`
- `index.md` 必须同时说明：当前阶段任务、前置阶段任务、阶段关系、当前使用的 plan，以及历史阶段文档入口
- `progress.md` 保留历史阶段执行记录，并追加“下一阶段开启”记录，不清空旧进展
- `meta.yaml` 需要更新当前阶段、当前任务名、当前记录分支、当前 plan，并保留历史阶段链路
- 开启新阶段后，默认把状态重置为 `方案中`

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo pf-mproducer-supplier
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo 手机前端
```

### 10. Cleanup

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

### 11. Status

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

### 12. Portal

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

- 默认只读取本文件即可创建、恢复、发布、同步、审查和收口任务
- 当需要更新任务文档、拆分方案、处理 `meta.yaml` 或判断文档职责时，读取 [docs-model.md](references/docs-model.md)
- 当需要准备 runtime、解释 `repositories.yaml` / `workspace.yaml` 字段、处理后端测试环境时，读取 [runtime.md](references/runtime.md)

## 输出约束

当用户要求创建或继续任务时，回复应聚焦于：
- 当前识别到的任务
- 涉及哪些仓库
- 下一步动作是什么

当用户要求发布时，回复应聚焦于：
- 当前识别到的任务
- 将发布哪些目标
- 每个目标对应的仓库目录和发布命令
- 发布结果，以及失败仓库的错误信息
- 如果发布停在 `develop` 合并冲突，说明当前分支、冲突文件、已自动解决的内容、最小验证结果、重试发布结果，或需要用户确认的问题

当用户要求同步远程主线时，回复应聚焦于：
- 当前识别到的任务
- 将同步哪些仓库
- 每个仓库的当前分支和同步动作
- 成功结果，以及失败仓库的错误信息或冲突信息

当用户要求代码审查时，回复应聚焦于：
- 当前识别到的任务、目标仓库和 review 基线
- 是否发现并应用项目级 review 规则
- findings 优先，按严重程度排序，包含文件/行号、问题、影响和建议
- 对抗式审查发现的风险或无发现结论
- 测试代码收敛结论：建议保留、建议删除/合并、需要用户确认的测试
- 是否阻塞上线或进入发布

发布场景下的协作约束：
- 不要把内部脚本实现、通用化改造、命名抽象这类 agent 内部设计过程再次抛给用户确认
- 如果用户已经明确表达发布意图，应直接按当前 task-workflow 规则识别任务、匹配目标并执行
- 对用户优先说明“识别到什么任务、将发布什么、为什么这样执行”，而不是说明“准备怎么改脚本”
- 只有在发布目标无法匹配、任务上下文不明确、或存在真实执行风险时，才向用户补充提问
- 除非用户明确在讨论 workflow/skill 设计本身，否则不要把实现层 tradeoff 当作当前对话主问题
- 普通发布失败后，默认不延伸到代码修复流程；先把失败点和错误信息交给用户决定下一步
- `sg publish` 留下 `develop` 合并冲突时，不要清理现场或切回任务分支；优先在 `develop` 上解决明确冲突，验证后重新发布
- 不要把 `develop` 发布冲突当作“回到任务分支继续开发”的问题；冲突发生在哪里，就在当前 `develop` 合并现场处理

同步场景下的协作约束：
- 不要把“准备怎么 merge、怎么解冲突、要不要顺手修代码”这类后续动作自动串进去
- 如果同步失败，默认停在“展示失败仓库和错误信息”这一步，等用户确认后再继续处理

审查场景下的协作约束：
- 不要只输出泛泛建议；必须基于真实 diff、真实项目规则和真实代码路径给结论
- 不要把大 diff 从头线性扫完当作认真；先收敛到任务相关路径和当前 patch，再决定是否扩散
- 不要因为没有发现阻塞问题就省略测试收敛 pass；测试代码价值判断是 review 的固定组成部分
- 不要把“可能有问题”包装成明确 bug；明确 bug、风险、待确认项要分开
- 如果用户只要求 review，默认不改代码；如果用户授权修明确问题，仍然只修明确问题

在工作流已经建立后，不要反复解释目录树结构或 Git 基础概念。
