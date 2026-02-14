# 03. 系统运行与操作手册（Runbook）

## 1. 环境准备

## 1.1 必要条件

1. Docker / Docker Compose
2. Python 3.8+（本地测试）
3. `config/feishu_config.json`（如需飞书联动）

## 1.2 关键配置

- 规则：`config/rules.yaml`
- 飞书与模型密钥：`config/feishu_config.json` 或 `.env` 覆盖

---

## 2. 启动方式

## 2.1 常规启动

```bash
cd /Users/zhangqilai/project/Neural-Flow
docker compose up --build -d
```

## 2.2 健康检查

```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
curl http://localhost:8006/health
```

---

## 3. 标准验证流程

## 3.1 一键验证（推荐）

```bash
make run-action
```

验证动作包括：

1. 启动服务
2. 触发 `run_once`
3. 选题回调触发草稿生成
4. 校验 `topic_pool/draft_pool` 目录
5. 校验 dashboard 记录完整性

## 3.2 手动验证

1. 跑一次脉搏：
```bash
curl -X POST "http://localhost:8001/run_once"
```

2. 查仪表盘：
```bash
curl "http://localhost:8006/dashboard?limit=20"
```

3. 模拟飞书回调：
```bash
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
```

---

## 4. 重置与重建脚本

## 4.1 清空记录缓存并重启

```bash
make clean-restart
```

等价脚本：`scripts/clean_and_restart.sh`

动作：

1. 停服务
2. 清空 `data/memory.db`、`data/archive.db`、`data/archive/`
3. 重新启动（不强制重建镜像）

## 4.2 删除容器+记录并重建重启

```bash
make nuke-rebuild
```

等价脚本：`scripts/nuke_and_rebuild.sh`

动作：

1. 停服务并删除容器/网络/卷
2. 删除本地服务镜像
3. 清空数据目录
4. `up --build -d` 全量重建

---

## 5. 常用运维命令

## 5.1 查看日志

```bash
docker compose logs -f pulse
docker compose logs -f archivist
docker compose logs -f cortex
docker compose logs -f iris
```

统一日志检索（结构化 + trace）：

```bash
curl "http://localhost:8006/logs?limit=100"
curl "http://localhost:8006/logs?service=archivist&level=ERROR&limit=50"
curl "http://localhost:8006/logs?keyword=callback&limit=50"
curl "http://localhost:8006/logs/trace/topic1234-twitter?limit=200"
```

日志聚合库默认位于：`data/system_logs.db`

## 5.2 热重载规则

```bash
curl -X POST "http://localhost:8001/reload"
```

## 5.3 查看计划状态

```bash
curl "http://localhost:8001/status"
```

---

## 6. 故障排查

## 6.1 飞书群出现 localhost 链接

原因：飞书文档创建失败，系统降级为本地链接。

排查：

1. 查看 `dashboard` 的 `feishu_doc_status`
2. 检查 app 权限、folder token 权限
3. 校验 `app_id/app_secret/root_folder_token`

## 6.2 回调未触发草稿生成

检查项：

1. 回调 URL 是否配置正确
2. 状态值是否属于确认态（如 `已确认`）
3. 平台字段是否有值
4. `archivist` 日志是否有异常

## 6.3 run-action 构建镜像异常（Docker Desktop）

若出现镜像不存在的 Buildx 异常：

1. 使用 `make nuke-rebuild` 强制重建
2. 或设置 `RUN_ACTION_BUILD=1 make run-action` 走 legacy build

---

## 7. 日常操作建议

1. 先看选题（topic）再确认状态
2. 选平台后触发草稿自动生成
3. 草稿人工审校后手动发布
4. 发布后在表格更新最终状态
