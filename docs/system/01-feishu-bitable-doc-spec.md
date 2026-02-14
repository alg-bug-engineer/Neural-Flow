# 01. 飞书多维表格与飞书文档规范（当前实现）

## 1. 总体说明

当前系统使用 **1 个飞书多维表格**（单 table_id）承载选题与草稿记录；通过 `record_type` 区分：

- `topic`：选题记录（来源信息、原始摘要）
- `draft`：平台草稿记录（模型生成内容）

飞书相关核心行为在以下模块：

- `services/archivist/main.py`
- `libs/neural_flow/feishu.py`

---

## 2. 多维表格字段映射（写入）

> 说明：系统通过“字段别名”自动识别列。只要你的飞书列名命中任一别名即可。

| 业务字段 | 飞书列别名（任一） | 建议类型 | topic写入 | draft写入 | 值来源 |
|---|---|---|---|---|---|
| 标题 | `原始标题` / `📌 原始标题` / `Title` | 文本 | 是 | 是（前缀`[平台]`） | 选题标题或草稿标题 |
| 摘要 | `AI 摘要` / `AI摘要` / `🤖 AI 摘要` / `AI Summary` | 多行文本 | 是（写`topic_summary`） | 是（写`ai_summary`） | topic用源摘要，draft用模型摘要 |
| 状态 | `状态` / `🚦 状态` / `Status` | 单选 | 是 | 是 | 记录状态值 |
| 文档链接 | `文档链接` / `飞书文档` / `🔗 飞书文档` / `Doc URL` | 超链接/文本 | 是 | 是 | 仅写 Drive doc 链接 |
| 平台 | `发布平台` / `发布渠道` / `📢 发布渠道` / `Channels` | 多选 | 是 | 是 | `channels` |
| 日期 | `归档日期` / `日期` / `📅 日期` / `Date` | 日期 | 是 | 是 | 当前系统时间 |
| 来源 | `来源` / `来源信息` / `Source` / `Source Info` | 文本 | 是 | 是 | `source_info` |

### 2.1 平台值映射

写入多选列时，内部平台值映射如下：

- `twitter` -> `Twitter`
- `wechat_blog` / `wechat` -> `公众号`
- `zhihu` -> `知乎`
- `juejin` -> `掘金`
- `xiaohongshu` / `xhs` -> `小红书`

### 2.2 来源字段建议

建议将“来源”列设为**单行文本**，示例值：

- `twitter-yupi`
- `wechat-xinzhiyuan`
- `wechat-qbit`
- `xiaohongshu-xxx`

---

## 3. 状态与回调触发规则

## 3.1 触发入口

- 回调接口：`POST /feishu/callback`
- URL 验证：`type=url_verification` 时返回 `challenge`

## 3.2 触发条件（关键）

系统仅当 `状态` 字段命中下列值之一才触发生成：

- `确认`
- `已确认`
- `通过`
- `approved`
- `confirmed`
- `ready`
- `ready_to_generate`

若状态不在集合内，回调忽略。

## 3.3 回调读取字段

系统从事件中读取：

- 标题：`原始标题` / `📌 原始标题` / `Title` / `选题标题`
- 摘要：`摘要` / `Summary` / `AI 摘要` / `AI摘要` / `🤖 AI 摘要` / `AI Summary` / `选题摘要`
- 来源：`来源` / `来源信息` / `Source` / `source_info`
- 来源链接：`来源链接` / `Source URL` / `原文链接` / `链接`
- 平台：`发布平台` / `发布渠道` / `📢 发布渠道` / `Channels` / `平台`
- Trace ID：`Trace ID` / `trace_id` / `追踪ID` / `追踪 Id`

## 3.4 状态值建议（落地版）

| 状态值 | 记录类型 | 是否触发回调生成 | 语义 |
|---|---|---|---|
| `待评估` | topic | 否 | 刚入库待人工判断 |
| `待确认` | topic | 否 | 可用选题，待确认并选平台 |
| `已确认` | topic | 是 | 触发平台草稿生成 |
| `生成中` | topic | 否 | 回调已触发，处理中 |
| `已转草稿` | topic | 否 | 已产出草稿 |
| `已驳回` | topic/draft | 否 | 不再处理 |
| `生成失败` | topic | 否 | 生成链路失败 |
| `草稿完成` | draft | 否 | 草稿已生成待审 |
| `待发布` | draft | 否 | 审稿完成待人工发布 |
| `已发布` | draft | 否 | 已人工发布 |
| `发布失败` | draft | 否 | 发布过程失败 |

> 触发集合（硬编码）仅包含：`确认`、`已确认`、`通过`、`approved`、`confirmed`、`ready`、`ready_to_generate`。  
> 建议不要在 draft 状态中使用这些词，避免误触发二次生成。

## 3.5 多维表类型兼容说明（按飞书字段类型）

系统对字段类型做了兼容处理：
- 单选列：自动匹配已有 option，不存在时回落第一个 option  
- 多选列：按平台映射后写入 option 数组  
- 日期列：优先写毫秒时间戳  
- 链接列：写 `{text, link}` 对象  
- 文本列：直接写字符串

---

## 4. 飞书云文档规范

## 4.1 目录层级（Drive）

系统按日期分层并与本地一致：

- `YYYY-MM-DD/topic_pool`
- `YYYY-MM-DD/draft_pool`

## 4.2 文档标题规则

- 选题文档：`[YYYY-MM-DD] 选题 | 来源 | 短标题 [#trace]`
- 草稿文档：`[YYYY-MM-DD] 草稿 | 平台 | 短标题 [#trace]`

其中短标题会自动压缩和截断（避免过长）。

## 4.3 选题文档正文结构

- 标题
- Trace ID
- `## 摘要`（来源摘要，不是模型总结）
- 来源信息
- Source URL
- 推荐平台

## 4.4 草稿文档正文结构

- 标题
- Trace ID
- Platform
- 来源信息
- `## AI Summary`
- `## Twitter Draft`（有值时）
- `## Article`
- `## Images`

---

## 5. 链接策略（为什么会看到两种链接）

系统默认先写本地文档，再尝试飞书文档：

1. 本地先成功 -> 得到 `local_http_doc_url`
2. 飞书成功 -> `final_doc_url` 替换为 Drive 链接
3. 飞书失败 -> 保留本地链接作为兜底

多维表格中 `doc_url` 当前只写 `drive_doc_url`（可能为空）。

群通知中的 `Doc` 链接策略：

- 优先 `drive_doc_url`
- 兜底 `final_doc_url`（可能是 localhost）

所以当飞书写文档失败时，群消息会出现 localhost 链接。

---

## 6. 群消息通知内容

通知文本包含：

- TraceID
- Title
- Summary
- Image
- Doc

通知只在 `record_type=topic` 时发送；草稿生成不会发送群通知。

---

## 7. 建议的飞书表结构（可直接落地）

建议至少包含以下列：

1. `原始标题`（文本）
2. `AI 摘要`（多行文本，作为统一摘要显示列）
3. `来源`（文本）
4. `状态`（单选）
5. `发布平台`（多选）
6. `文档链接`（超链接）
7. `日期`（日期）
8. `Trace ID`（文本，建议新增）

> 注意：`Trace ID` 当前不是自动写回字段，只是回调会读取；建议你在飞书自动化里保留该列，以便追踪。
