---

# Neural-Flow v3.0：数字生命体微服务架构方案

## 1. 设计哲学与全景

我们将系统定义为一个**“数字生命体” (Cybernetic Organism)**。它由 **1 个中枢心脏** 和 **5 个功能器官** 组成。

- **解耦原则**：**Pulse (心脏)** 是唯一的调度者，拥有“时间感”。其他器官（眼睛、大脑、记忆等）均为**无状态服务 (Stateless Services)**，只响应请求，不主动发起动作。
- **配置驱动**：所有业务逻辑（发帖频率、平台策略、监控源）与代码分离，通过 `config.yaml` 动态控制。
- **部署环境**：Linux ECS Server (Docker Compose 编排)。

---

## 2. 模块化详细设计 (The Organs)

每个模块都是一个独立的 Docker 容器，暴露 RESTful API (Port 8001-8006)。

### 2.1 Pulse (脉搏) —— 中枢调度器

- **职责**：系统的“心脏”。读取配置文件，管理定时任务 (Cron)，向其他器官发送 HTTP 指令。
- **特性**：唯一的主动模块。包含日志聚合与错误重试机制。
- **配置依赖**：挂载 `/config/rules.yaml`。

### 2.2 Sentry (哨兵) —— 信息采集器

- **职责**：系统的“眼睛”。负责连接外部世界，获取原始数据。
- **输入**：`POST /scan {source_config}`
- **输出**：标准化清洗后的 Item List (JSON)。
- **逻辑**：
    - 调用 RSSHub 获取 Twitter/公众号数据。
    - 执行基础去噪（去除纯链接、广告词）。
    - **不判断价值**（价值判断交给大脑）。

### 2.3 Hippocampus (海马体) —— 记忆与去重

- **职责**：系统的“记忆中枢”。本地 SQLite 数据库，维护长短期记忆。
- **输入**：
    - `POST /check_duplicate {url_hash}` (查重)
    - `POST /retrieve_context {keywords}` (检索历史观点)
- **输出**：`Boolean` 或 `History_Context_String`。
- **数据持久化**：挂载 `/data/memory.db`。

### 2.4 Cortex (皮层) —— 认知大脑

- **职责**：系统的“大脑”。负责深度思考、改写、提取。
- **核心**：集成 **Kimi 2.5 API**。
- **输入**：`POST /think {raw_text, history_context, platform_strategy}`
- **输出**：
    - `twitter_draft`: 短文案
    - `article_markdown`: 深度长文
    - `image_prompt`: 英文绘画提示词

### 2.5 Iris (虹膜) —— 视觉工坊

- **职责**：系统的“视觉神经”。
- **核心**：集成 **即梦 (Jimeng) API**。
- **输入**：`POST /paint {prompt, ratio}` (支持 16:9 / 3:4)
- **输出**：高清图片 URL (或 Base64)。

### 2.6 Archivist (史官) —— 资产归档

- **职责**：系统的“手”。负责与飞书生态交互。
- **核心**：集成 **Feishu Open Platform API**。
- **输入**：`POST /archive {content_pack}`
- **输出**：`feishu_doc_url`。
- **逻辑**：
    - 按日期创建云文档文件夹。
    - 写入 Markdown 与 图片 Block。
    - 回写飞书多维表格。
    - **发送飞书卡片消息通知用户**。

---

## 3. 配置驱动设计 (Configuration)

通过修改挂载的 `rules.yaml` 文件，即可指挥整个系统，无需重启容器。

YAML

# 

`# rules.yaml 示例

# 1. 全局设置
global:
  timezone: "Asia/Shanghai"
  memory_retention_days: 30

# 2. 信号源配置 (Sentry 读取)
sources:
  - id: "twitter_yupi"
    type: "rsshub"
    url: "http://rsshub:1200/twitter/user/yupi996"
    fetch_interval: "30m"  # 每30分钟 Pulse 唤醒一次 Sentry
    weight: 10             # 优先级

# 3. 平台策略 (Cortex 读取)
platforms:
  twitter:
    enabled: true
    style_prompt: "sharp_news" # 对应 Cortex 内部的 Prompt 模板 ID
    max_posts_per_day: 5
    
  wechat_blog:
    enabled: true
    schedule: "20:00"      # 每天晚上8点 Pulse 唤醒一次 Cortex 做汇总
    style_prompt: "deep_tech"
    min_word_count: 2000

# 4. 视觉风格 (Iris 读取)
visual:
  default_style: "cyberpunk, data flow, neon lights, 8k resolution"`

---

## 4. 运行流程 (The Heartbeat SOP)

这是一次完整的“心跳”循环，由 **Pulse** 发起：

1. **Awake (唤醒)**：Pulse 的定时器触发（例如 09:00）。
2. **Scan (扫描)**：
    - Pulse -> 请求 Sentry (`/scan`)。
    - Sentry -> 返回 5 条原始数据。
3. **Filter (过滤)**：
    - Pulse 遍历 5 条数据 -> 请求 Hippocampus (`/check_duplicate`)。
    - Hippocampus -> 返回 2 条是新的，3 条重复。
4. **Context (回忆)**：
    - Pulse 针对 2 条新数据 -> 请求 Hippocampus (`/retrieve_context`)。
    - Hippocampus -> 返回：“关于 Transformer，上周已分析过架构。”
5. **Think (思考)**：
    - Pulse -> 请求 Cortex (`/think`)，附带“上周已分析架构”的上下文。
    - Cortex -> 调用 Kimi，生成“API 成本分析”角度的文案 + Image Prompt。
6. **Paint (绘图)**：
    - Pulse -> 请求 Iris (`/paint`)。
    - Iris -> 调用即梦，返回图片 URL。
7. **Archive (归档)**：
    - Pulse -> 请求 Archivist (`/archive`)。
    - Archivist -> 创建飞书文档，写入图文，回写多维表格，**发送飞书卡片**。
8. **Notify (通知)**：
    - 你的飞书收到卡片。流程结束。

---

## 5. 部署架构 (ECS & Docker)

### 5.1 目录结构

Plaintext

# 

`/opt/neural_flow/
├── docker-compose.yml       # 编排文件
├── .env                     # API Keys (Kimi, Feishu, Jimeng)
├── config/
│   └── rules.yaml           # 你的控制台
├── data/
│   └── memory.db            # SQLite 持久化文件
├── services/
│   ├── pulse/               # 源码
│   ├── sentry/
│   ├── hippocampus/
│   ├── cortex/
│   ├── iris/
│   └── archivist/`

### 5.2 Docker Compose 编排

所有服务运行在内部网络 `neural_net` 中，不对外暴露端口（除了 RSSHub 需要访问外网），保证安全。

YAML

# 

`version: '3.8'

networks:
  neural_net:
    driver: bridge

services:
  # --- 心脏 ---
  pulse:
    build: ./services/pulse
    container_name: nf_pulse
    volumes:
      - ./config/rules.yaml:/app/config.yaml
    environment:
      - SENTRY_API=http://sentry:8000
      - HIPPOCAMPUS_API=http://hippocampus:8000
      - CORTEX_API=http://cortex:8000
      - IRIS_API=http://iris:8000
      - ARCHIVIST_API=http://archivist:8000
    networks:
      - neural_net
    restart: always

  # --- 器官 (无状态服务) ---
  sentry:
    build: ./services/sentry
    container_name: nf_sentry
    networks:
      - neural_net

  hippocampus:
    build: ./services/hippocampus
    container_name: nf_hippocampus
    volumes:
      - ./data:/app/data  # 数据持久化
    networks:
      - neural_net

  cortex:
    build: ./services/cortex
    container_name: nf_cortex
    env_file: .env # Kimi Key
    networks:
      - neural_net

  iris:
    build: ./services/iris
    container_name: nf_iris
    env_file: .env # Jimeng Key
    networks:
      - neural_net

  archivist:
    build: ./services/archivist
    container_name: nf_archivist
    env_file: .env # Feishu Token
    networks:
      - neural_net`

---

## 6. 人机协作接口 (Interface)

系统最终交付给用户的界面，完全在**飞书**中。

### 6.1 飞书多维表格 (Dashboard)

Pulse 触发 Archivist 自动维护此表。

| **📅 日期** | **📌 原始标题** | **🤖 AI 摘要** | **🔗 飞书文档** | **🚦 状态** | **📢 发布渠道** |
| --- | --- | --- | --- | --- | --- |
| 02-12 | DeepSeek V3 发布 | 架构分析... | [点击跳转] | **待审** | 推特, 公众号 |
| 02-12 | Python 3.14 新特性 | 解释器优化... | [点击跳转] | **已发** | 掘金 |

### 6.2 飞书卡片 (Action Card)

当 Archivist 完成归档，Pulse 会通过 Webhook 发送卡片：

> **⚡️ 脉搏：发现高价值信号**
> 
> 
> **Title**: DeepSeek V3 Technical Report
> 
> **Summary**: Kimi 已生成深度解读，侧重于 MLA 注意力机制。
> 
> **Image**: [图片预览]
> 
> ---
> 
> **[ 📝 打开文档精修 (PC) ]**
> 
> **[ 🚀 复制推特文案 (Mobile) ]**
> 

### 6.3 扩音器 (Megaphone)

这是**最后一步的人工动作**：

1. 点击卡片跳转飞书文档。
2. 人工审阅，修改代码细节（注入专家灵魂）。
3. 点击浏览器插件 **WeChatSync**。
4. 一键同步到公众号、掘金、知乎。

---

## 7. 方案总结

此 **v3.0** 方案的完整性与优越性在于：

1. **高度模块化**：你想换掉 Kimi 改用 GPT-4？只需修改 `Cortex` 一个容器的代码，其他模块完全无感。
2. **运维友好**：所有状态都在数据库，所有策略都在配置文件。ECS 上只需要维护 Docker 容器。
3. **专家防呆**：通过 `Hippocampus` 强制 AI 进行“增量式写作”，避免了 AI 常见的“车轱辘话”问题。
4. **体验闭环**：移除了 Telegram，利用飞书强大的 API 能力，实现了“通知-生产-管理”的一体化。