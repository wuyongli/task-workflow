# 钉钉收件人核对

`fix` 的 PR 审查人回复和 `bug` 的测试人员交测通知使用同一套“姓名 → 钉钉收件 ID”核对规则。两者的区别只在姓名来源，不在找人方式。

## 姓名来源

- `fix`：用户本轮点名的完整姓名。`前端`、`手机端`、`后端` 等是目标范围，不是姓名的一部分，不能带进人员搜索。
- `bug`：`sg testhub task show <testhub-task-id> --json` 回读的 `tester` 完整姓名；用户本轮明确指定复测人时以用户指定为准。`tester_id` 是 Test Hub 平台内关联 ID，不能直接当钉钉收件 ID。
- 同一场景内的姓名可能来自多个对象，但每次只按本轮实际收件人逐个核对，不把一个场景的姓名复用给另一个场景。

## 核对规则

1. 用完整姓名搜索，不拆分、不省略姓氏，不带任务名或端标签。
2. 命中多人时先澄清，不默认取第一项；组织、部门、头像等只能作辅助证据，不能替代唯一身份确认。
3. 多组织查找及跨组织发送遵守 DWS 当前规则，不持久切换组织，也不根据历史回执推断本轮收件人；已核对组织后需要指定时，使用一次性 `--profile`。
4. 优先取 `userId`；只有拿不到 `userId` 时才用 `openDingTalkId`。`--user` / `--open-dingtalk-id` / `--group` 三选一，不能同时传。
5. 记录本轮核对依据、真实收件人姓名和收件 ID，与发送 UUID、回执一起保存，供重试和去重；不把本地推断值当成远程 ID。

## 搜索与发送

人员搜索示例：

```bash
dws aisearch person --keyword '<完整姓名>' --dimension name --format json
```

单聊发送示例：

```bash
dws chat message send --user '<已核对的 userId>' --title '<标题>' --text '<正文>' --uuid '<操作 UUID>' --format json
```

只有 `openDingTalkId` 时用 `--open-dingtalk-id` 替换 `--user`，两者互斥。发送前确认收件人属于本轮场景：`fix` 只发给本轮点名的 PR 审查人，`bug` 只发给本轮核对的测试人员，不交叉复用。
