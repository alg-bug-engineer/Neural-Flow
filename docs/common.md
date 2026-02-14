一键执行完整验证（启动+run_once+回调+结果校验）：
make run-action

一键清空记录/缓存并重启：
make clean-restart

一键删除容器/记录并重建重启：
make nuke-rebuild

先清理去重缓存，让系统重新处理现有源（会重新产出内容）：
curl -X POST "http://localhost:8003/cleanup?retention_days=0"
再跑一次：
curl -X POST "http://localhost:8001/run_once"
看结果：
curl "http://localhost:8006/dashboard?limit=5"

飞书回调（状态确认后触发分平台草稿生成）：
curl -X POST "http://localhost:8006/feishu/callback" \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "record": {
        "fields": {
          "原始标题": "GLM-5 发布",
          "摘要": "模型发布摘要",
          "来源": "twitter-yupi",
          "状态": "已确认",
          "发布平台": ["Twitter", "知乎"],
          "Trace ID": "topic1234",
          "来源链接": "https://example.com/post/1"
        }
      }
    }
  }'

停止所有服务（不删容器）：
docker compose stop

停止并删除容器网络：
docker compose down

重启（重建镜像）：
docker compose down && docker compose up --build -d



按这个顺序做一遍即可验证：

进入项目并启动容器
cd /Users/zhangqilai/project/Neural-Flow
docker compose down
docker compose up --build -d
检查 6 个服务健康状态
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
curl http://localhost:8006/health
触发一次“采集->选题入库”
curl -X POST "http://localhost:8001/run_once"
查看仪表盘（应看到 record_type=topic 的记录）
curl "http://localhost:8006/dashboard?limit=20"
模拟飞书确认回调（触发分平台草稿）
curl -X POST "http://localhost:8006/feishu/callback" \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "record": {
        "fields": {
          "原始标题": "GLM-5 发布",
          "摘要": "模型发布摘要",
          "来源": "twitter-yupi",
          "状态": "已确认",
          "发布平台": ["Twitter", "知乎"],
          "Trace ID": "topic1234",
          "来源链接": "https://example.com/post/1"
        }
      }
    }
  }'
再看仪表盘（应新增 record_type=draft，平台分别生成）
curl "http://localhost:8006/dashboard?limit=50"
检查本地目录层级是否一致
find /Users/zhangqilai/project/Neural-Flow/data/archive -maxdepth 3 -type d | sort
你应看到：

.../YYYY-MM-DD/topic_pool
.../YYYY-MM-DD/draft_pool
如果要验证“多维表格链接指向 Drive”，需要先在 feishu_config.json 配好飞书凭据；否则会走本地兜底。

统一日志查看（按服务/关键词/trace 检索）：
curl "http://localhost:8006/logs?limit=100"
curl "http://localhost:8006/logs?service=cortex&level=ERROR&limit=50"
curl "http://localhost:8006/logs?keyword=feishu&limit=50"
curl "http://localhost:8006/logs/trace/topic1234-twitter?limit=200"

说明：
- 全链路使用 `x-trace-id` / `x-request-id` 透传，支持跨服务追踪。
- 聚合日志 SQLite：`data/system_logs.db`。
