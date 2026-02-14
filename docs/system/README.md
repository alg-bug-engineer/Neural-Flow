# Neural-Flow System 文档总览

本目录提供当前代码实现的系统性文档，按“飞书契约 -> 模块设计 -> 运行操作 -> 功能回顾”组织。

## 文档索引

1. `01-feishu-bitable-doc-spec.md`
   - 飞书多维表格字段、类型、值域、触发规则、回调规则
   - 飞书云文档标题/目录/写入规则
   - 群消息通知格式与链接策略

2. `02-modules-and-logic.md`
   - 各模块职责、接口、输入输出、关键逻辑与数据流
   - 公共库（RSS/Memory/Feishu/Archive）行为说明

3. `03-runbook-and-operations.md`
   - 启动、验证、排障、重置与重建
   - 一键脚本使用说明（run-action / clean-restart / nuke-rebuild）

4. `04-current-capabilities-chain-and-requirements.md`
   - 已有功能清单
   - 完整执行链路
   - 需求满足度对照与当前边界

## 约定

- 该文档描述的是“当前仓库代码行为”（不是 PRD 理想态）。
- 字段别名、状态触发、回调解析均以实际代码为准。
- 若后续修改字段名/状态值，请同步更新本目录文档。
