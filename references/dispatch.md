# 自动开发总调度约束

本文件定义 Codex 总调度协议。`scripts/task_dispatch.py` 已提供持久化串行队列与进程锁；它不调用 Codex、Docker、数据库或钉钉，也不修改任务 meta。总调度会话负责实际工具动作与事实核验，定时唤醒单独配置。脚本初始化队列默认关闭；存在队列文件不表示调度已启用。

## 调度边界

- 总调度以任务空间为最小调度单元，每个任务独立读取 `meta.yaml`、当前阶段 plan、progress 和仓库状态；不以 BBS 编号、分支名或会话名替代任务空间。
- 一个总调度会话、每个任务空间一个独立执行会话，首版严格串行。运行占用未完成交接时不启动第二项，也不因会话没有新输出就判定失活。
- 调度前先读取 BBS 原始任务描述；有 `bbs_id` 时同步读取 `sg bbs demand view <id> --with-ai --json` 的 AI 分析。BBS 内容和 AI 分析都不是任务空间准入事实，仍需当前代码和文档核验。
- 本总调度的执行指令必须明确要求读取 `product-copilot-rules`，按其适用边界选择分析路径：产品目标、业务语义、范围或验收不清时按需展开产品分析；目标明确时走轻量路径；业务规则 Bug 精简明确业务口径、影响范围和验收；明确技术 Bug 直接诊断和最小修复，不强行展开完整产品流程。`task-workflow` 继续管理任务生命周期和开发准入。
- prepare 首次分析、dispatch 接续和阶段切换均核对当前阶段是否已有足够分析；复用有效结论与取证，只补缺口。使用路径及依据记入 progress，稳定结论归并当前阶段主 plan，不另建第二份主方案。自动授权范围内的决策记录为“AI 依据用户预授权确定”，不重复索要批准；缺少关键业务事实时报告阻塞，不凭模式或 BBS AI 分析放行。
- 只有任务空间 `execution_mode: auto`、方案和开发准入满足条件、且没有更窄的本轮限制时，才可派发代码开发。manual、暂停中、关键事实缺失或准入不成立的任务只能进入分析 / 等待队列。
- 派发指令必须明确：本地真实页面测试使用 Codex 内置浏览器，先检查并接管已有相关标签以复用登录态；无现成标签则在同一浏览器打开已核实的任务前端入口。必须核对本任务后端代理，不能以独立浏览器登录页、缺少 TEST_COOKIE 或无凭证请求401判定缺少登录。具体步骤、证据与有限重试按 [verification.md](verification.md) 执行；总调度核验登录阻塞时同时检查这些证据。

- 派发指令必须明确：按 [runtime.md](runtime.md) 在仓库规定的工作目录启动前端服务及后端 Docker 服务，不能只启动任务 app；先核对共享服务归属、挂载及健康，不匹配时不直接重建。页面流程待前后端和代理确认就绪后再测试；纯接口/数据库验证只启动实际依赖。运行附件保存启动与就绪证据，progress 保留结果摘要。

## 每日边界

- 本假期正式调度固定按北京时间 02:00 开始、13:30 停止新派发和新的长耗时步骤、14:00 汇总并请求安全收尾、15:00 仅核验收尾/资源及补发通知。今天已启动任务按既有临时执行指令收尾，不为今日单独配置定时检查。每 1 小时检查作为遗漏补偿；任务实际交接后仅在新派发截止前推进当天范围内下一项。
- 时间判断统一读取队列 plan.work_hours 的固定 start、last_start、end；未配置时兼容原 08:00—18:00。脚本返回 wind_down 表示不得新派发或开启长步骤，保留运行占用，执行者收尾后才能交接；若是 reserved，先核对原会话和送达事实，不趁收尾补发启动指令。
- 当天范围来自计划，不把三项当作必须完成的数量。当日范围处理完即停，释放资源并通知；不因尚有时间提前取后续日期任务。
- 用户在总调度会话说“继续处理后面的任务”，默认追加一项；指定数量按数量执行。将原用户消息标识用作 command_id，重复唤醒不得再追加。追加项受阻也算已使用本次追加范围，不自动补位。
- 已提前处理的任务从原日范围扣除；未完成项优先顺延、占用次日原有位置，不叠加两天工作。脚本按原日任务数限制候选范围，但不要求完成这些数量；实际是否启动下一项还需评估剩余时间。顺延结果回写总清单供用户查看。
- 正常日终保存保留实际业务阶段，以 progress 的检查点和队列 not_before 表示次日可接续；不要写成用户暂停。暂停或必须人工解除的阻塞则进入 human 等待，普通追加不能解除。
- 新派发截止后（13:30）只有用户明确要求窗口外继续时才登记 after_hours，并指定具体任务；普通追加不得绕过收尾期，不放开整队列。该授权仅当天有效，次日开工前不继续派发。假期结束后停止派发，不能把错过的时间点全部补跑。

## 脚本入口与记录

```bash
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/task_dispatch.py --state /absolute/path/state.json --init /absolute/path/plan.json
python3 /Users/wuyongli/Documents/sg-skill/task-workflow/scripts/task_dispatch.py --state /absolute/path/state.json --request /absolute/path/request.json
```

`--now` 只用于隔离演练；正式运行用系统北京时间，不能伪造时间绕过窗口。请求文件是 UTF-8 JSON；脚本输出 JSON，失败退出 2。初始化不能覆盖旧记录；损坏记录报错，不默默重置。变更通过独立文件锁及原子替换保存，不能手工重写 state 绕过占用。

plan 包含 start_date、end_date、timezone（Asia/Shanghai）和 tasks。可选 work_hours 保存固定 start、last_start、end；时间用 HH:MM，满足 start < last_start <= end。现有队列通过 schedule 命令修改固定时段，不改当前占用、日范围或任务身份。每项有 key、name、day、phase、docs，可带 bbs_id。key 是队列引用；真正执行前必须绑定唯一绝对 docs 路径、核对 meta 的 task_id/phase/BBS。未创建空间允许 docs 为 null，但只能走 prepare。

state 保存会话绑定、运行占用、派发历史、每日实际范围、追加指令、检查点和通知回执；不替代任务 meta、plan、progress。hold 仅表示队列是否可继续，不是新增业务阶段。

| command | 关键输入 | 用途 |
| --- | --- | --- |
| status | 无 | 只读状态，不派发 |
| replan | plan、instruction | 仅在关闭且从未派发/生成每日范围时调整日期，保留通知记录，禁止改变任务身份或范围 |
| move | command_id、instruction、keys、day | 按明确指令将尚未派发且未进入已生成每日范围的未来任务改至假期内未来日期；幂等，保留启用状态、历史及暂停，不适用于当日追加 |
| schedule | instruction、start、last_start、end | 调整队列固定时段，保留活跃任务、每日范围和历史 |
| enable / disable | instruction | 明确启停队列；disable 不会强行杀进程，活跃任务收到 stop_requested |
| tick | 无 | 计算当前动作，保存首次生成的当日范围；不占用任务 |
| claim | 无 | 锁内重新判断并持久化一次派发；只有本次返回 prepare / dispatch 才能首次发送 |
| creating | run_id、client_thread_id | 保存会话创建中的标识，仅供恢复查询，不等同实际 threadId 或送达回执 |
| attach | run_id、thread_id | 绑定已确认的实际会话，不能用 clientThreadId 代替 threadId |
| ack | run_id | 已核实指令送达后确认；不是测试通过或任务完成 |
| bind | run_id、docs | prepare 中绑定任务空间；不能替换已有绑定或让两个队列项指向同一空间 |
| handoff | run_id、outcome、checkpoint、resources、evidence | 核验后的交接；资源未释放保留全局占用 |
| recover | run_id、executor_ended、checkpoint、resources | 已查明执行者结束后的异常恢复；转人工等待，不自动重发旧指令 |
| add | command_id、instruction，可选 count（默认 1）、key、after_hours | 明确追加或指定任务窗口外继续；同一 command_id 内容不可变 |
| resume | key、instruction | 明确解除队列 human 等待；meta 仍暂停时拒绝，须先按工作流处理恢复 |
| notify | event_id、text | 保存固定正文与幂等 UUID；同一事件不能换正文 |
| notification_result | event_id、status、receipt | 保存 pending / unknown / failed / sent，成功必须有回执 |

handoff 的 outcome 为 verified、blocked、checkpoint、ready。resources 必须含 released 布尔值和 evidence 文本。verified 还必须有 checks、real_flow、review、remote 四项证据；不适用项说明理由。ready 仅结束准备并重新排入当前范围，元数据仍未准入则拒绝。checkpoint 延至次日，blocked 等明确恢复。

改期后日期以state.plan为准，同步总清单，不改写旧派发与通知。未生成的每日范围排除元数据暂停项，避免其占用实际候选位置；任务全移走的空白日期仍可承接此前未完成项，容量沿用最近一个有计划任务日期的数量，不自动补入未来任务。

脚本只能检查结构、状态和记录一致性，不能替用户判断业务授权，也不能证明 evidence 文本属实。总调度必须读进度、实际工具结果和会话状态后才能登记交接；资源释放核验不得用一句“已停止”替代。

## Codex 会话派发与恢复顺序

1. 总调度先读取总计划和 state，执行 tick。disabled、outside_window、wind_down、day_done 均不派发；day_done 有阻塞项时不能通知“全部任务完成”。
2. 有可执行项才 claim。run.id 是本次指令标识，必须出现在发给执行会话的正文中。prepare 仅允许任务空间准备、BBS 正文与 AI 分析、方案及准入，不允许直接开始业务编码；dispatch 仍需执行会话重新核对代码、授权与当前阶段。
3. 已有 thread_id 先用 read_thread / wait_threads 查状态，再 send_message_to_thread；未绑定会话时按已获授权使用 create_thread，返回实际 threadId 后 attach。准备中的 clientThreadId 用 creating 持久保存待核对，不能当成实际 threadId。
4. 首次 create_thread 的 prompt 就是执行指令，不再立即重复发送相同指令。首次发送成功或回读确认包含 run.id 后 ack；发送结果不明保持 reserved。
5. 遇 reconcile 或上次创建结果丢失，先查询原会话，必要时 list_threads 按任务空间和 run.id 核对，再 attach/ack。不因超时另建、不盲目重发。无法确认则报告不确定，保留占用。
6. 执行会话在每个较长步骤前、工具返回后检查实际时间及队列状态；到 last_start（13:30）且无指定任务窗口外授权时，不开始新任务或长步骤并准备收尾；到 end（14:00）或收到 stop_requested 时，不开始新步骤，在安全检查点保存和释放资源，不在事务或文件写入中强杀。有效窗口外授权仅覆盖队列 overtime 当日列出的任务。
7. 执行会话完成交接准备后，上报 run.id、任务名/阶段、outcome、checkpoint、代码/真实验收/审查/远程证据、资源释放证据；可给总调度发送一次交接提醒，不自行选下一项或直接群发重复通知。
8. 总调度用 wait_threads/read_thread 核对执行者已经结束或等待用户，回读任务事实，再 handoff。该命令既不停止容器也不结束会话，不能在执行者仍可能改代码时释放占用。
9. cleanup_required 先核对并释放明确归属的任务资源，再补交接。recover 必须已有执行者结束证据；查不到状态、无新输出或查询超时都不是结束证据。恢复默认人工等待，避免意外重做。

总调度的定时检查与执行会话提醒可同时到达，但只允许 claim 的新派发结果产生首次执行指令；reconcile/observe 不具有新的发送权限。单次读状态不能提供七天无人值守保证，必须先验证实际会话及定时唤醒链路。

## 统一进度事件

单任务会话向总调度报告结构化里程碑事件；总调度负责去重、排序和对外推送：

- `started`：开始接续任务
- `stage_changed`：阶段切换
- `admitted`：方案与开发准入完成
- `implemented`：代码开发完成
- `verified`：本任务必需的代码检查与真实流程自动测试均完成，附环境、版本、步骤/命令、页面/接口/数据库断言；不适用项附理由。只有单测通过时不得发送 verified
- `reviewed`：审查及明确缺陷修复完成
- `pushed`：提交和普通推送完成，附仓库与远程 SHA
- `blocked`：测试、环境、权限、数据或用户决策阻塞
- `closed`：必需自动测试、审查、远程核验均完成后收口；只列剩余用户业务验收，不把未执行的真实流程自动测试转交人工

## 钉钉推送格式

- 统一推送到群“国庆任务进度推送”；总调度发送前按群名查询当前 `openConversationId`，不固化历史群 ID。
- 每条消息必须先写**任务名称**，再写阶段；BBS ID 只作为辅助字段，不能只推送数字 ID。推荐格式：`【任务名称｜第 N 阶段｜状态】动作：...；验证：...；阻塞：...；下一步：...`。
- 任务名称以当前任务空间 `meta.yaml.current_task_name` / `current_stage.task_name` 为准，BBS 标题只用于交叉核对。多阶段任务必须带阶段名称。
- 只推送已发生事实。没有执行的测试、页面、接口、测试服数据库或客户验收必须明确写“未执行 / 待验收”。
- 同一任务、阶段、run.id、同一结果只推送一次；后续修复产生新结果仍需通知。普通命令、重复取证和内部重试不单独推送。每日开工、任务开始、准入、开发、自测、审查、推送、阻塞、交接、资源释放、提前收工、追加开始和每日收尾汇总（14:00）均须覆盖，可合并相邻节点。
- 发送前 notify 保存正文和 UUID，再由 dws 发送；有 openTaskId 先记录 unknown 和该 ID，查得 SUCCESS 后才登记 sent。响应丢失先查发送状态；在服务幂等有效期内重试复用同 UUID，不生成新的发送标识。长期不确定须人工核查，不能无限重试。
- 群消息发送失败不改变任务状态，不阻断代码流程；下一次检查或里程碑有限补发，包括当天已结束时的后续检查。不得因发送 API 受理就声称消息送达。钉钉当前仅是通知渠道，不把群聊内容自动作为开发指令。

## 收口

总调度最终按任务汇总：任务名称、当前阶段、状态、最近里程碑、提交 SHA、验证结果、阻塞和下一步。没有真实提交、验证或远程结果时，不得把任务标记为已完成。

- 已推送但必要真实流程测试未完成的任务，仍属于未完成自动开发闭环；总调度应继续安排测试，不按 pushed 或测试中状态跳过。具体阻塞先报告 blocked，保留已通过项和解除条件；不得把阻塞任务报为 verified/closed。

## 等待与资源释放

任务转入等待人工或阻塞队列前，执行 auto-mode 的任务资源释放规则，停止并核验该任务专属 Docker app；已暂停任务不得仅因定时唤醒自动重启。总调度记录实例释放结果再推进其他任务，恢复授权到达后按仓库指令重新启动。正在自动自测的 `测试中` 任务不因状态名称而被提前停止。

正常日终同样释放本次专属 app 和前端。停止前核对 meta 绑定仓库、compose project、实际挂载以及前端进程 cwd；复用 stop_task_runtime 或任务 compose stop app，不用 docker pause，不全局 stop/down，不影响共享数据库及其他任务。归属不明先保留占用并报告；Codex 或机器退出期间不能保证即时回收，下一次恢复检查补做核验。
