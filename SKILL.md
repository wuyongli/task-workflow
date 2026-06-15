---
name: task-workflow
description: Use when the user mentions 新任务、多仓库任务、任务工作区、继续任务、恢复任务上下文、任务进度、任务完成、发布测试服、publish、同步远程主线、sync、任务地址、端口导航、本地开发地址、下一阶段、二期、next, or needs to create, continue, publish, sync, inspect, open task dev URLs, start the next stage in the same workspace, complete, or clean up a multi-repo task under /Users/wuyongli/Documents/sg-project/_workspace.
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
4. 基于远端默认分支最新提交创建或重置任务分支
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
- 任务分支只以远端默认分支作为起点，不自动跟踪 `origin/master` 或其他默认分支；首次推送任务分支时再建立自己的 upstream
- 对于 `producer-backend`，还会生成任务级 Docker 辅助文件，让每个任务都能只启动自己的 `app` 容器，同时复用共享基础设施
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
4. 再更新 `progress.md` 的过程记录
5. `plan.md` 只在方案发生变化时更新

更新原则：
- `index.md` 只保留当前快照
- `plan.md` 只保留当前有效方案
- `progress.md` 记录实际进展、验证结果、阻塞与变更历史
- `meta.yaml` 保存最小机器事实
- 不允许让 `index.md` 比 `meta.yaml` 更“新”
- 更新文档时，优先整段重写当前章节并归并重复内容，不要只在原文后面继续追加碎片信息
- 如果某个结论、方案或进展已经被新内容替代，应直接覆盖旧表述，而不是保留多个版本并列
- `plan.md` 和 `index.md` 默认维护“当前有效版本”；只有 `progress.md` 的“变更记录”适合追加历史条目

任务状态固定为：
- `方案中`
- `开发中`
- `测试中`
- `已完成`

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
- 某个目标发布失败时，不应阻断其它目标；应继续完成其它目标，并明确展示失败仓库的错误信息
- 发布失败后，默认停在“展示失败信息”这一步，不自动进入修代码、解冲突、补提交或重试发布
- 如果失败原因是代码冲突、工作区不干净、分支异常或发布命令本身报错，默认只反馈事实，不自行修复，除非用户明确要求继续处理

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

### 7. Complete

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

### 8. Next

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

### 9. Cleanup

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

### 10. Status

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

### 11. Portal

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

## 文档模型

文档约束：
- task markdown files are fixed to `index.md`, `plan.md`, and `progress.md` by default
- 复杂任务允许受控拆分，但不允许自由散生文档
- 如果用户明确要求拆文档，直接按受控方式拆，不必坚持单文件
- 同一工作空间进入新阶段时，允许新增一个按新任务名命名的阶段 plan 文档
- 当 `plan.md` 已同时承载多个相对独立模块方案，或正文已经明显影响阅读、归并更新与恢复上下文稳定性时，才允许拆出扩展文档
- 允许的扩展文档只有两类：
  - `appendix-<topic>.md`：承接背景推导、备选方案、远期预留、影响地图等不应长期压在正文里的内容
  - `<module>-plan.md`：承接一个独立模块、页面组或子域的详细方案
- 不要创建 `notes.md`、`todo.md`、`draft.md`、`plan-v2.md`、`tmp-*.md` 这类漂移文件
- 如果 unexpected extra task markdown files already exist，优先归并到 `plan.md`、`progress.md` 或受控扩展文档，而不是继续沿用散乱命名
- treat `plan.md` as the single source of truth for goals, solution decisions, implementation design, and validation plan
- treat `progress.md` as the single source of truth for actual work done, verification results, and blockers
- `plan.md` 只保留当前阶段的主阅读路径；远期阶段、展开推导和非当前主攻模块细节应下沉
- 当更新任务文档时，默认做“归并更新”，不要做“追加式更新”
- 如果目标章节本身已经存在重复、冲突或过期碎片，应先归并清理该章节，再写入新的当前版本
- 对同一章节，如果出现旧结论和新结论冲突，应保留当前有效版本并删除旧碎片
- 除“变更记录”外，不要让同一文件里出现多个并列的状态、多个并列的下一步、多个并列的方案版本
- 只要拆出扩展文档，必须同时回写 `plan.md` 和 `index.md` 的导航；不能只新建文件不登记入口
- `plan.md` 永远是主入口：当前范围、当前结论、当前开发方案和开工判断必须能在 `plan.md` 找到，不能完全下沉到子文档
- 扩展文档中的当前有效结论，如果已经进入执行依据，必须回写归并到 `plan.md`
- `appendix-*.md` 不是当前执行主依据；如果某个附录内容已转为当前方案，应归并回正文并从附录移除或降为补充说明

### `index.md`

用途：
- AI 恢复上下文时的人类可读摘要入口
- 只保留当前快照

必须包含：
- current status
- one-line goal
- current conclusion
- current blocker
- next step
- links to `meta.yaml`、`plan.md` and `progress.md`

同步要求：
- `index.md` 中的状态和下一步是给人读的摘要，不是机器事实定义
- 仓库路径、记录分支、恢复状态等机器事实优先放在 `meta.yaml`
- 如果摘要中引用了机器事实，必须与 `meta.yaml` 保持一致
- 更新 `index.md` 时应直接重写“任务摘要”到当前版本，不要在下方追加新的状态说明段落
- 如果任务已经拆出模块子方案或附录，只在 `index.md` 中保留当前仍有效、仍需导航的文档，不要把过期子文档继续挂在导航里
- 如果任务已经进入多阶段模式，`index.md` 不能只写当前生效 plan；还必须写清当前阶段任务、前置阶段任务、阶段关系、当前 plan、历史阶段文档入口

使用模板：[index.md](references/index.md)

### `plan.md`

用途：
- 产品方案和开发方案放在一个地方
- 只保留当前有效方案，不保留讨论过程
- 同时作为“是否允许开始代码工作”的判断依据和说明记录
- 当产品方案已确认但开发方案未完成时，仍然属于 `方案中`
- 如果某个领域型 skill 产出了当前采用的复用结论或项目惯例判断，也应在 `plan.md` 收口，而不是只留在对话里
- 在单阶段任务中，`plan.md` 默认仍是主方案文档；当同一工作空间开启新阶段时，当前阶段主方案文档可以切换为按新任务名命名的阶段 plan

说明：
- `plan.md` 负责记录为什么可以或不可以开工
- 最终机器状态应写入 `meta.yaml`，不要让 `plan.md` 独自承担机器事实
- 更新 `plan.md` 时，应把新方案归并到现有结构中，删除被替代的旧表述，不要把多轮讨论结果并列堆在同一章节下
- `当前有效方案` 只写当前成立的产品/业务方案结论
- `项目惯例与复用结论` 只写当前已经采用或待确认的项目惯例判断，不写完整搜索过程
- `开发方案` 只写实现设计与改动面，不重复产品结论
- 当前要推进的动作放在 `index.md` 的“下一步”和 `progress.md` 的“当前进展”，不要再在 `plan.md` 里重复维护一份动作清单
- `plan.md` 应优先收口：当前阶段目标、当前明确范围、当前推荐路径、当前风险与待确认项
- 如果某个模块的详细设计已经明显撑大主文档，应拆到 `<module>-plan.md`，主文档只保留结论摘要和入口
- 如果某些内容属于远期路线、历史推导、备选方案或展开影响地图，应拆到 `appendix-<topic>.md`
- 如果任务进入复杂阶段，`plan.md` 应增加“阅读导航”，把模块子方案和附录挂在固定入口下
- 模块子方案用于承接单个模块的详细设计、代码锚点、接口草案和验证清单；不要在多个子方案里重复背景结论
- 附录用于承接背景推导、旧方案对照、远期预留、展开影响地图；不要把它写成当前执行主文档
- 如果同一工作空间开启新阶段，新的阶段 plan 应按新任务名、分支语义或当前任务描述命名，例如 `plan-新任务名.md`；不要使用 `plan-phase-2.md` 这类抽象命名
- 上一阶段 plan 保留为历史上下文，不再继续覆盖；当前阶段 plan 负责当前方案

使用模板：[plan.md](references/plan.md)

### 受控扩展文档

#### `<module>-plan.md`

用途：
- 当某个模块、页面组或子域的详细方案已经明显撑大 `plan.md` 时，承接该模块的细化设计

规则：
- 文件名保持 `<module>-plan.md`
- 必须回链 `plan.md`
- 只写该模块自己的范围、当前结论、实现设计、验证与风险
- 不重复完整背景、全局范围和总方案结论

使用模板：[module-plan.md](references/module-plan.md)

#### `appendix-<topic>.md`

用途：
- 当背景分析、备选方案、历史推导、远期路线或展开影响地图会干扰正文主阅读路径时，承接这些补充内容

规则：
- 文件名保持 `appendix-<topic>.md`
- 必须回链 `plan.md`
- 默认不作为当前执行主依据
- 如果附录中的某个结论已成为当前方案的一部分，先回写 `plan.md`，再决定是否保留附录作为补充

使用模板：[appendix.md](references/appendix.md)

### `progress.md`

用途：
- 实际执行状态
- 自测结果
- 供后续恢复上下文使用的最小历史

说明：
- `progress.md` 的“当前进展”“实际改动”“自测记录”“问题与阻塞”应始终整理为当前版本
- 只有“变更记录”是天然追加区；其他章节如果反复追加，会导致内容零散、重复、难以恢复上下文

使用模板：[progress.md](references/progress.md)

### `meta.yaml`

用途：
- 通过路径把一个文档目录和一个任务代码目录绑定起来
- 记录最小的、可机器读取的仓库绑定与分支信息
- AI 恢复任务上下文时的第一事实入口

规则：
- `meta.yaml` 是任务绑定的机器可读事实来源
- `meta.yaml` 也是 AI 恢复任务上下文时的第一事实入口
- 优先记录 `repo_dir` 或相对任务路径；绝对路径只保留兼容用途
- `index.md` 保持可读，但只做摘要展示，不应重复承担完整机器事实记录
- `meta.yaml` 尽量最小化，但应完整承载任务机器事实
- 最低字段应包含：`task_id`、`status`、`resume_status`、`coding_allowed`、以及每个仓库的 `key`、`repo_dir`、`branch`
- 只要任务状态、`resume_status`、仓库路径或记录分支发生变化，必须优先更新 `meta.yaml`，再确保 `index.md` 与之对齐
- 当一次更新同时涉及 `index.md` 与 `meta.yaml` 时，视 `meta.yaml` 为最终机器事实，不要反过来只根据 `index.md` 推断
- 除非 `meta.yaml` 缺失或损坏，否则恢复上下文时必须先读它，再读其他任务文档
- 项目惯例判断、复用结论、方案取舍理由默认不写入 `meta.yaml`；这些内容应写在 `plan.md`
- 如果任务进入多阶段模式，`meta.yaml` 应额外记录当前阶段和阶段链路，例如：当前阶段编号或名称、当前任务名、当前 plan、历史阶段列表

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

发布约定：
- `shared-backend-app` 默认视为后端仓库，发布命令为 `sg publish jenkins`
- `patch-node-frontend-environment` 默认视为前端仓库，发布命令为 `sg publish local`

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
- 当前识别到的任务
- 涉及哪些仓库
- 下一步动作是什么

当用户要求发布时，回复应聚焦于：
- 当前识别到的任务
- 将发布哪些目标
- 每个目标对应的仓库目录和发布命令
- 发布结果，以及失败仓库的错误信息

当用户要求同步远程主线时，回复应聚焦于：
- 当前识别到的任务
- 将同步哪些仓库
- 每个仓库的当前分支和同步动作
- 成功结果，以及失败仓库的错误信息或冲突信息

发布场景下的协作约束：
- 不要把内部脚本实现、通用化改造、命名抽象这类 agent 内部设计过程再次抛给用户确认
- 如果用户已经明确表达发布意图，应直接按当前 task-workflow 规则识别任务、匹配目标并执行
- 对用户优先说明“识别到什么任务、将发布什么、为什么这样执行”，而不是说明“准备怎么改脚本”
- 只有在发布目标无法匹配、任务上下文不明确、或存在真实执行风险时，才向用户补充提问
- 除非用户明确在讨论 workflow/skill 设计本身，否则不要把实现层 tradeoff 当作当前对话主问题
- 发布失败后，默认不延伸到代码修复流程；先把失败点和错误信息交给用户决定下一步

同步场景下的协作约束：
- 不要把“准备怎么 merge、怎么解冲突、要不要顺手修代码”这类后续动作自动串进去
- 如果同步失败，默认停在“展示失败仓库和错误信息”这一步，等用户确认后再继续处理

在工作流已经建立后，不要反复解释目录树结构或 Git 基础概念。
