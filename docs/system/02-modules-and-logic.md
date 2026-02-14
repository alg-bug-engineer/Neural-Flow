# 02. 模块功能与逻辑详解

## 1. 架构概览

系统由 6 个服务组成（HTTP 微服务）：

1. `pulse`：调度与编排
2. `sentry`：RSS 抓取与标准化
3. `hippocampus`：记忆、去重、上下文
4. `cortex`：文本创作（Kimi + fallback）
5. `iris`：图片生成（即梦 + fallback）
6. `archivist`：归档、飞书写入、回调触发

---

## 2. Pulse（调度编排）

## 2.1 职责

- 读取 `config/rules.yaml`
- 按 source interval 触发采集
- 执行去重、高价值筛选
- 生成选题记录并调用 Archivist 写入

## 2.2 核心接口

- `GET /health`
- `GET /status`
- `POST /reload`
- `POST /run_once`

## 2.3 核心逻辑

一次 source 处理流程：

1. `sentry/scan` 拉取条目
2. `hippocampus/check_duplicate` 去重
3. 高价值规则筛选（长度/图像/关键词打分）
4. 构造 `record_type=topic` 内容包
5. `archivist/archive` 落本地+飞书
6. `hippocampus/remember` 记忆存储

### 当前重要变更

- 选题阶段 **不调用大模型**（不做 AI 总结）
- 选题摘要来自 RSS 原始文本摘要
- 自动生成 `source_info`（如 `twitter-yupi`）

---

## 3. Sentry（采集标准化）

## 3.1 职责

- 拉取 RSS XML（支持 http/file）
- 解析为标准 `NormalizedItem`

## 3.2 输出结构

每条标准项包含：

- `url_hash`
- `title`
- `url`
- `summary`
- `raw_text`
- `images[]`
- `keywords[]`
- `published_at`

## 3.3 清洗逻辑

- HTML -> 纯文本
- 去噪（纯链接、广告词等）
- 关键词提取
- 图片链接提取

---

## 4. Hippocampus（记忆去重）

## 4.1 职责

- URL Hash 去重
- 历史语义上下文检索
- 入库记忆
- 过期清理

## 4.2 存储

- SQLite: `data/memory.db`
- 核心表：`memory_items`

## 4.3 接口

- `POST /check_duplicate`
- `POST /retrieve_context`
- `POST /remember`
- `POST /cleanup`

---

## 5. Cortex（文本创作）

## 5.1 职责

- 根据标题/正文/历史上下文/平台策略生成：
  - `twitter_draft`
  - `article_markdown`
  - `image_prompt`
  - `ai_summary`

## 5.2 模式

- Kimi 可用 -> 走 Kimi
- Kimi 不可用/异常 -> fallback 模板

## 5.3 平台策略理解（当前增强）

Prompt 已显式区分：

- `longform_deep_analysis` -> 技术解读/影响/科普长文
- `casual_log_style` -> 记录/日志/感慨口语短文

---

## 6. Iris（图片生成）

## 6.1 职责

- 基于 prompt 生成图片 URL

## 6.2 模式

- 即梦可用 -> 调用即梦异步任务
- 不可用 -> `picsum.photos` 回退图

## 6.3 比例规则

- `twitter/xiaohongshu` 常用 `16:9` + 1 图
- 长文平台常用 `3:4` + 3 图（由 Archivist 决策）

---

## 7. Archivist（归档与飞书交互）

## 7.1 职责

- 写本地 markdown 归档
- 写飞书 Drive 文档
- 写飞书多维表格记录
- 发送群通知（topic）
- 处理飞书状态回调并触发草稿生成

## 7.2 关键接口

- `POST /archive`：写入 topic/draft
- `POST /feishu/callback`：状态回调触发草稿生成
- `GET /dashboard`：查看归档记录
- `GET /local-archive/{rel_path}`：本地稿访问

## 7.3 回调链路

1. 收到飞书事件
2. 判断 `状态` 是否确认态
3. 读取标题、摘要、来源、平台、Trace ID
4. 按平台循环：调用 Cortex + Iris
5. 生成 `record_type=draft` 记录入档

## 7.4 本地归档结构

- `data/archive/YYYY-MM-DD/topic_pool/*.md`
- `data/archive/YYYY-MM-DD/draft_pool/*.md`

---

## 8. 公共库逻辑

## 8.1 `libs/neural_flow/feishu.py`

- tenant token 获取与缓存
- Drive 目录递归创建/查找
- Doc 创建与写入
- Bitable 字段元数据识别（按别名）
- 群消息通知发送

## 8.2 `libs/neural_flow/archive.py`

- 本地 markdown 写入
- dashboard SQLite 持久化
- 历史草稿上下文提取（防重复创作）

## 8.3 `libs/neural_flow/rss.py`

- RSS 标准化解析
- 去噪/抽图/关键词提取

## 8.4 `libs/neural_flow/http.py`

- HTTP 访问与重试（tenacity）

---

## 9. 数据存储清单

1. `data/memory.db`：去重与记忆
2. `data/archive.db`：归档仪表盘
3. `data/archive/YYYY-MM-DD/...`：本地 markdown 文档

---

## 10. 关键状态与记录类型

- `record_type`：`topic` / `draft`
- 常用状态：
  - topic：`待确认`、`生成中`、`已转草稿`、`已驳回`、`生成失败`
  - draft：`草稿完成`、`待发布`、`已发布`、`已驳回`、`发布失败`

> 当前代码里状态是“透传写入 + 回调识别确认态”，不强制状态机闭环。
