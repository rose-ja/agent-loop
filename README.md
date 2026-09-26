# Agent Loop

一个用于构建和运行 AI Agent 循环的项目。Agent 根据任务获取上下文、调用工具并持续迭代，直到完成目标或达到停止条件。

## 核心流程

1. 接收用户任务
2. 分析当前状态并制定下一步行动
3. 调用模型或外部工具
4. 更新上下文并循环执行
5. 返回最终结果

## 开始使用

需要 Python 3.11+。在 Git Bash 中运行：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py
.venv/Scripts/python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

同步 CLI `python main.py` 保持原有接口；HTTP 异步入口是 `POST /agent/stream`，返回 SSE 事件（`progress`、`success` 或 `failed`）。

```bash
curl -N -X POST http://127.0.0.1:8000/agent/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: demo-123' \
  -d '{"question":"请查询北京天气","max_steps":5,"timeout":10,"tool_timeout":3,"tool_delay":0.01,"max_retries":2}'
```

浏览器原生 `EventSource` 只支持 GET，不能直接调用本 POST 接口；使用支持 POST 流式读取的 `fetch` 客户端。`X-Request-ID` 仅接受 1-128 位英文字母、数字、点、下划线和短横线；非法值由服务端重生成。错误响应格式为 `{"code":"...","message":"...","request_id":"..."}`，流中失败事件的 `error` 字段也是同一格式。工具只允许注册表内的异步工具，重试仅限明确标记幂等、返回可重试 `TIMEOUT` 的工具，且始终受总截止时间限制。

```bash
.venv/Scripts/python -m pytest -q
```
