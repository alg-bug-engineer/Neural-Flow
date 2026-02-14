# Neural-Flow 生产操作手册

## 1. 系统目标

Neural-Flow 负责自动完成以下流程：

1. 从线上 RSS 源扫描技术内容（Twitter + 微信公众号）。
2. 去重并结合历史上下文生成增量观点。
3. 通过 Kimi 生成推文草稿、长文草稿和配图提示词。
4. 通过即梦生成图片。
5. 在飞书写入文档、多维表格，并向接收群发送通知。

## 2. 信息源与平台资源

1. Kimi 文档  
https://platform.moonshot.cn/docs/guide/kimi-k2-quickstart#%E9%AA%8C%E8%AF%81%E5%AE%89%E8%A3%85%E7%BB%93%E6%9E%9C
2. 自建微信公众号服务  
http://101.126.33.252:8001/add-subscription
3. 飞书多维表格  
https://my.feishu.cn/base/AzMrbnplgamyjtsEkoIcwSQSnUh?table=tblG6FKx1Ur08eMu&view=vew75PlObA
4. 飞书机器人应用  
https://open.feishu.cn/app/cli_a90470f197f8dcc5/baseinfo
5. 飞书云盘目录  
https://my.feishu.cn/drive/folder/D7K2fZdKzlLk4GdVxYCcjO0MnNc
6. 公共 wechat2rss 列表  
https://wechat2rss.xlab.app/list/all
7. 自建 RSSHub（Twitter）  
http://101.126.33.252:1200/twitter/user/yupi996/exclude_replies=1&include_rts=0

## 3. 当前线上源配置

已启用配置文件：`config/rules.yaml`

1. `twitter_yupi_live`  
`http://101.126.33.252:1200/twitter/user/yupi996/exclude_replies=1&include_rts=0`
2. `wechat_datawhale_live`  
`https://wechat2rss.xlab.app/feed/4d620d988cb21cfeefd2263207221f0dc70df9ff.xml`
3. `wechat_qbit_live`  
`https://wechat2rss.xlab.app/feed/7131b577c61365cb47e81000738c10d872685908.xml`
4. `wechat_xinzhiyuan_live`  
`https://wechat2rss.xlab.app/feed/ede30346413ea70dbef5d485ea5cbb95cca446e7.xml`
5. `wechat_jiqizhixin_live`  
`https://wechat2rss.xlab.app/feed/51e92aad2728acdd1fda7314be32b16639353001.xml`

## 4. 启动前检查

1. 确认 Python 与 Docker 可用。
2. 确认 `config/feishu_config.json` 已填入生产密钥。
3. 确认公网可访问 Kimi、即梦、飞书、RSS 源。
4. 确认 `config/rules.yaml` 已为线上 URL（不是 `file://`）。

## 5. 部署步骤

1. 安装依赖（本地调试）：
```bash
pip install -r requirements.txt
```
2. 启动服务：
```bash
docker compose up --build -d
```
3. 查看容器状态：
```bash
docker compose ps
```
4. 检查健康接口：
```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
curl http://localhost:8006/health
```

## 6. 首次联调步骤

1. 手动触发一次全链路：
```bash
curl -X POST "http://localhost:8001/run_once"
```
2. 查看 Pulse 调度状态：
```bash
curl "http://localhost:8001/status"
```
3. 查看归档结果：
```bash
curl "http://localhost:8006/dashboard?limit=20"
```
4. 验证飞书侧：
   - 飞书云盘是否出现新文档。
   - 多维表格是否新增记录。
   - 目标群是否收到文本通知。

## 6.1 收到飞书通知后，如何创作与确认

以群消息中的这几项为准：

1. `Title`：本条选题标题。
2. `Summary`：AI 摘要，快速判断是否值得发。
3. `Image`：配图链接，可直接预览。
4. `Doc`：正文入口。

标准动作：

1. 打开 `Doc` 链接查看全文草稿。
2. 先改标题和开头 3 段（保证观点准确，不要直接照搬）。
3. 检查事实信息：时间、模型名、版本号、链接是否正确。
4. 补上你的个人观点和结论（这是差异化价值）。
5. 发布前在飞书多维表格把 `状态` 从 `待审` 改成 `已发` 或 `驳回`。
6. 使用 WeChatSync 或你的发布链路同步到公众号/掘金/知乎。

## 6.2 如何判断一条记录是否真正写入飞书

查看接口：

```bash
curl "http://localhost:8006/dashboard?limit=20"
```

关注 4 个字段：

1. `archive_url`：最终文档地址。
2. `feishu_doc_status`：
   - `ok` = 飞书云文档创建成功
   - 其他错误文本 = 云文档失败，当前回退到本地文档
3. `feishu_bitable_status`：
   - `ok` = 多维表格写入成功
4. `feishu_notify_status`：
   - `ok` = 群通知发送成功

## 6.3 为什么群里有通知，但云盘没文档

这是常见权限问题，不是你操作错。

当 `feishu_doc_status` 出现：

- `403 Forbidden`
- `1770040 no folder permission`

说明应用对目标文件夹没有写权限。处理方法：

1. 打开飞书云盘文件夹：`D7K2fZdKzlLk4GdVxYCcjO0MnNc`
2. 给机器人应用（`cli_a90470f197f8dcc5`）添加可编辑权限。
3. 在飞书开放平台确认应用开通文档与云盘相关权限（创建/编辑文档、云盘写入）。
4. 重试：
```bash
curl -X POST "http://localhost:8001/run_once"
```

备注：即使云盘失败，系统也会提供本地可访问文档链接，例如：
`http://localhost:8006/local-archive/2026-02-13/xxxx.md`

## 6.4 Summary 在系统里的处理规则

`Summary`（`ai_summary`）会同时进入 3 个位置：

1. 飞书群通知：`Summary: ...`，用于快速筛选是否值得创作。
2. 飞书多维表格：写入 `AI 摘要` 字段。
3. 飞书云文档正文：写入 `## AI Summary` 小节。

建议把 `Summary` 当作“导语 + 观点提纲”，不是最终正文。最终发布前至少补充：

1. 事实核验（时间/模型版本/链接）。
2. 你自己的判断和结论。
3. 面向目标平台的改写（微博短版、公众号长版）。

## 6.5 本地稿与云文档如何一一对应

系统已使用统一追踪键（`Trace ID`）打通 4 个位置：

1. 飞书群消息：`TraceID: abc12345`
2. 云文档标题：`[2026-02-13] 标题 [#abc12345]`
3. 本地草稿文件名：`HHMMSS_sourceId_abc12345.md`
4. Dashboard 字段：`trace_id`

所以只要用 `trace_id` 就能做精确对照，不再依赖随机 hash 猜测。

## 6.6 云文档按日期分目录策略

启用 `root_folder_token` 后，Archivist 创建云文档时会：

1. 优先在根目录下查找当日目录（如 `2026-02-13`）。
2. 未找到则自动创建该日期目录。
3. 将文档写入该日期目录。
4. 若目录权限异常，自动回退到应用默认空间，避免任务失败。

## 6.7 停止服务

停止当前栈（保留数据卷）：

```bash
docker compose stop
```

停止并移除容器网络（保留本地 `data/`）：

```bash
docker compose down
```

停止并强制重建：

```bash
docker compose down
docker compose up --build -d
```

## 7. 集成测试命令

1. 本地功能测试：
```bash
pytest -q
```
2. Kimi + 即梦线上测试：
```bash
RUN_LIVE_INTEGRATION=1 pytest -q tests/test_kimi_api.py tests/test_jimeng_api.py
```
3. 飞书线上测试：
```bash
RUN_FEISHU_INTEGRATION=1 pytest -q tests/test_feishu_integration.py
```

## 8. 日常运维

1. 查看服务日志：
```bash
docker compose logs -f pulse
docker compose logs -f cortex
docker compose logs -f iris
docker compose logs -f archivist
```
2. 修改策略后热更新：
```bash
curl -X POST "http://localhost:8001/reload"
```
3. 数据落盘目录：
   - `data/memory.db`
   - `data/archive.db`
   - `data/archive/YYYY-MM-DD/*.md`

## 9. 常见问题处理

1. 即梦返回 fallback 图（`picsum.photos`）  
原因：即梦 API 调用失败或超时。  
处理：检查 `jimeng_ak`、`jimeng_sk`，并执行 `tests/test_jimeng_api.py`。

2. 飞书未写入文档或表格  
原因：应用权限不足或 token 配置错误。  
处理：检查 `app_id`、`app_secret`、`root_folder_token`、`bitable_app_token`、`bitable_table_id`。

3. Kimi 输出一直 fallback  
原因：`kimi_api_key` 不可用或请求失败。  
处理：执行 `tests/test_kimi_api.py`，并检查 Kimi 账户额度与网络连通性。

4. RSS 抓取为空  
原因：源不可访问或内容全被清洗规则过滤。  
处理：直接访问 RSS URL 验证可用性，必要时提高 `max_items` 或切换源。

## 10. 变更规范

1. 先在 `config/rules.yaml` 调整源和频率。
2. 执行 `curl -X POST "http://localhost:8001/reload"` 触发重载。
3. 手动执行一次 `run_once` 做验收。
4. 确认飞书链路正常后再进入定时运行。
