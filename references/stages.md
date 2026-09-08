# 阶段与子任务

## 核心判断

- 阶段化由用户的产品推进口径触发，不由 `next` 指令独占触发
- 用户一开始就说“一期 / 二期 / 分阶段 / 先做 A 再做 B / 本阶段只做 X / 后续再做 Y”时，从创建任务开始就按阶段化文档模型处理
- `next` 只表示在已有工作空间里开启下一阶段；不是阶段化的唯一入口
- 如果用户没有表达阶段化，也没有明确拆产品子任务，默认保持单阶段、单主 plan

## 三层模型

1. 长期工作空间
   - 由同一个 `_docs/<task-id>` 和 `_tasks/<task-id>` 承载
   - 保存同一长期主题下的历史阶段、当前阶段和仓库绑定
   - 不等于一个永远膨胀的总方案文档

2. 阶段任务
   - 是当前要推进和验收的执行单位
   - 单阶段任务使用 `plan.md`
   - 多阶段任务使用 `plan-<阶段任务名>.md` 或用户明确认可的阶段 plan 文件
   - 当前阶段 plan 是当前阶段方案、开发方案、数据变更和上线方案的主入口
   - 阶段状态相互独立；当前阶段状态写入顶层 `status` 和 `current_stage.status`，历史阶段状态写入 `previous_phases[].status`
   - 阶段可以带自己的 `bbs_id`；开启新阶段时不默认沿用上一阶段编号

3. 产品子任务 / 模块子方案
   - 只有用户明确按产品口径拆分，或阶段 plan 已明显过大影响阅读和维护时才创建
   - 文件名使用 `<module>-plan.md`
   - 前端、后端、PC、手机端只是实现涉及面，不作为默认拆分依据

## 默认轻量规则

- 没有阶段化、没有子任务时：`plan.md` 是唯一方案来源
- 有阶段化、没有子任务时：当前阶段 plan 是当前阶段唯一方案来源
- 有阶段化且有子任务时：子文档承接对应模块详细方案，阶段 plan 只保留摘要、依赖、风险和入口
- 不要为了遵守分层规则，把简单任务拆成多个文档

## 子文档单一来源

- 一旦明确拆出产品子任务 / 模块子方案，子文档是该子任务详细方案的单一来源
- 主 plan 或阶段 plan 只保留：子任务清单、摘要、当前状态、依赖关系、风险、链接入口
- 子文档里的详细需求、字段/索引明细、接口草案、上线审批 SQL 或脚本清单，不复制到主 plan
- 如果任务开始没拆文档，后续才拆出子文档，应把主 plan 中对应详细内容迁移到子文档，并删除主 plan 里的重复细节

## `next` 规则

- `next` 不是“继续原任务”，而是在原工作空间内开启一个新的阶段任务
- 用户明确调用 `next` 时，表示先暂停当前阶段并开启下一阶段；不等于确认上一阶段已经完成或已上线
- `next` 允许从 `方案中` / `开发中` / `测试中` / `暂停中` / `已完成` 进入下一阶段
- 如果当前阶段已是 `已完成`，历史阶段保留为 `已完成`；否则历史阶段记录为 `暂停中`，并用 `resume_status` 保存原状态
- 默认要求当前记录仓库工作区干净，避免把上一阶段的未收敛状态带入下一阶段
- 不要求上一阶段本地分支仍保留 upstream；任务上线后原远程任务分支已删除属于正常场景
- 默认复用原 task id、原 `_tasks/<task-id>` 代码目录、原 `_docs/<task-id>` 文档目录；不要因为开启下一阶段就新建任务工作空间
- 新阶段分支默认基于远程 `master` 最新代码创建，不承接当前本地任务分支
- 新阶段可以指定新的 `bbs_id`；如果不指定，当前阶段不记录 `bbs_id`，避免误把上一阶段需求编号带到新阶段
- 如果本阶段只涉及当前任务绑定仓库中的部分仓库，允许只切这些仓库到新阶段分支；未选中的仓库继续保留原分支
- `next --repo` 同时支持 repo key 和自然目标名称，例如 `pf-mproducer-supplier`、`手机前端`、`PC前端`、`后端`
- 新阶段 plan 文件名优先使用新任务名、分支语义或当前任务描述，不使用 `plan-phase-2.md` 这类抽象命名
- 开启新阶段后，当前阶段状态为 `方案中`、`coding_allowed: false`，等待本阶段方案确认和明确开发指令

## 文档同步

- `index.md` 必须说明当前阶段任务、前置阶段任务、阶段关系、当前 plan、历史阶段文档入口和可选需求编号
- `progress.md` 保留历史阶段执行记录，并追加“下一阶段开启”记录，不清空旧进展
- `meta.yaml` 需要更新当前阶段、当前阶段状态、当前任务名、当前记录分支、当前 plan、可选 `bbs_id`，并保留历史阶段链路
- `next` 归档上一阶段时必须记录该阶段每个绑定仓库的本地分支；后续 `stage` 切换只能依赖这些已记录分支
- 新阶段的方案讨论过程可写到 `decision-log-<阶段任务名>.md`；当前有效取舍结论写到阶段 plan

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --bbs-id 53850
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo pf-mproducer-supplier
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/next_task_workspace.py "YYYY-MM-DD-原始任务名" "新任务名" --repo 手机前端
```

## `stage` 规则

- `stage` 用于在已有多阶段工作空间内切换当前阶段，不创建新阶段
- 典型场景：已经 `next` 到二期后，用户要求临时切回一期分支处理问题
- 阶段切换必须同时切换仓库分支、`meta.yaml` 当前阶段、`active_plan` 和 `index.md`，不要只手动 `git checkout`
- 切换前要求当前仓库工作区干净，且当前分支与 `meta.yaml` 记录分支一致
- 目标阶段必须在 `current_stage` 或 `previous_phases` 中存在，并记录全部绑定仓库的本地分支
- 如果目标阶段缺少任一绑定仓库分支，直接阻断，不允许切成“部分仓库属于一期、部分仓库属于二期”的混合阶段
- 如果目标阶段的本地分支不存在，直接阻断并说明缺失分支；不要从远程分支、`master` 或阶段名自动重建
- 如果多仓 checkout 中途失败，停止写入 `meta.yaml` 和文档，明确展示已切和未切仓库，待用户确认后再恢复一致状态
- 切换成功后，原当前阶段进入 `previous_phases`，目标阶段成为 `current_stage`
- 切出未完成阶段时，历史阶段记录为 `暂停中`，并用 `resume_status` 保存切出前状态
- 切入 `暂停中` 阶段时，恢复到 `resume_status`；如果目标本地分支不存在，直接阻断，不重建分支

推荐命令：

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_stage.py "YYYY-MM-DD-原始任务名" "1"
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/switch_task_stage.py "YYYY-MM-DD-原始任务名" "一期任务名"
```
