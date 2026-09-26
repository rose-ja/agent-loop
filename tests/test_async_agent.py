import asyncio
import json
import re

import httpx
import pytest

from agent.async_agent import AsyncToolSpec, run_agent_async
from api.app import app, request_id_var


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def collect(**kwargs):
    return [event async for event in run_agent_async("weather", **kwargs)]


def tool_model(_):
    return {"type": "tool_calling", "function": {"function_name": "get_weather", "params": {"city": "北京"}}}


@pytest.mark.anyio
async def test_success_and_max_steps():
    events = await collect()
    assert events[-1]["type"] == "success"
    events = await collect(max_steps=1)
    assert events[-1]["error"]["code"] == "MAX_STEPS"


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [
    {"question": " "}, {"timeout": float("inf")}, {"tool_timeout": float("nan")},
    {"max_steps": True}, {"max_retries": -1}, {"tool_delay": 0},
])
async def test_invalid_direct_args(kwargs):
    events = [event async for event in run_agent_async(kwargs.pop("question", "weather"), **kwargs)]
    assert events == [{"type": "failed", "error": {"code": "INVALID_ARGUMENT", "message": "invalid agent arguments"}}]


@pytest.mark.anyio
async def test_unknown_tool_and_invalid_results():
    assert (await collect(model=tool_model, tools={}))[-1]["error"]["code"] == "UNKNOWN_TOOL"
    assert (await collect(model=lambda _: "secret"))[-1]["error"]["code"] == "INVALID_MODEL_RESULT"
    assert (await collect(model=tool_model, tools={"get_weather": AsyncToolSpec(lambda _: bad())}))[-1]["error"]["code"] == "INVALID_TOOL_RESULT"


async def bad():
    return "secret"


@pytest.mark.anyio
async def test_retry_idempotency_and_budget():
    count = 0

    async def intermittent(_):
        nonlocal count
        count += 1
        if count < 3:
            return {"status": "error", "error_code": "TIMEOUT", "retryable": True}
        return {"status": "success", "response": {"data": "ok"}}

    tools = {"get_weather": AsyncToolSpec(intermittent, True)}
    assert (await collect(model=tool_model, tools=tools, max_steps=1))[-1]["error"]["code"] == "MAX_STEPS"
    assert count == 3
    count = 0
    assert (await collect(model=tool_model, tools={"get_weather": AsyncToolSpec(intermittent, False)}))[-1]["error"]["code"] == "TOOL_TIMEOUT"
    assert count == 1

    async def slow(_):
        await asyncio.sleep(1)
        return {"status": "success", "response": {"data": "late"}}

    events = await collect(model=tool_model, tools={"get_weather": AsyncToolSpec(slow, True)}, timeout=0.02, tool_timeout=0.1)
    assert events[-1]["error"]["code"] == "TOTAL_TIMEOUT"
    assert not any(e["type"] == "success" for e in events)


@pytest.mark.anyio
async def test_cancel_unwinds_tool():
    started, closed = asyncio.Event(), asyncio.Event()

    async def blocking(_):
        try:
            started.set()
            await asyncio.sleep(10)
        finally:
            closed.set()

    async def run():
        return await collect(model=tool_model, tools={"get_weather": AsyncToolSpec(blocking)})

    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.anyio
async def test_http_success_and_validation():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/agent/stream", json={"question": " 北京 "}, headers={"x-request-id": "req-123"})
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "req-123"
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "success"
        assert all(event["request_id"] == "req-123" for event in events)
        for data in ({"question": "   "}, {"question": "x", "extra": 1}, {"question": "x", "tool_delay": 0}):
            response = await client.post("/agent/stream", json=data, headers={"x-request-id": "bad id"})
            assert response.status_code == 422
            assert response.json() == {"code": "VALIDATION_ERROR", "message": "invalid request", "request_id": response.headers["x-request-id"]}
            assert re.fullmatch(r"[A-Za-z0-9._-]{1,128}", response.headers["x-request-id"])
        response = await client.post(
            "/agent/stream",
            content=b'{"question":"x","timeout":Infinity}',
            headers={"content-type": "application/json", "x-request-id": "finite-check"},
        )
        assert response.status_code == 422


@pytest.mark.anyio
async def test_stream_failure_request_id_and_concurrent_context(monkeypatch):
    import api.app as module

    async def stub(**_):
        await asyncio.sleep(0.01)
        yield {"type": "failed", "error": {"code": "TEST", "message": request_id_var.get()}}

    monkeypatch.setattr(module, "run_agent_async", stub)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def call(value):
            r = await client.post("/agent/stream", json={"question": "x"}, headers={"x-request-id": value})
            return r, json.loads(r.text.split("data: ")[1])
        results = await asyncio.gather(call("one"), call("two"))
    for response, event in results:
        assert event["error"] == {"code": "TEST", "message": response.headers["x-request-id"], "request_id": response.headers["x-request-id"]}


@pytest.mark.anyio
async def test_asgi_disconnect_cancels_stream(monkeypatch):
    import api.app as module

    started, closed = asyncio.Event(), asyncio.Event()

    async def blocking(_):
        try:
            started.set()
            await asyncio.sleep(10)
        finally:
            closed.set()

    async def model(_):
        return {"type": "tool_calling", "function": {"function_name": "get_weather", "params": {}}}

    monkeypatch.setattr(module, "run_agent_async", lambda **kwargs: run_agent_async(
        **kwargs, model=lambda _: {"type": "tool_calling", "function": {"function_name": "get_weather", "params": {}}},
        tools={"get_weather": AsyncToolSpec(blocking)},
    ))
    messages = [{"type": "http.request", "body": b'{"question":"x"}', "more_body": False}]
    sent = []

    async def receive():
        if messages:
            return messages.pop(0)
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await module.app({
        "type": "http", "method": "POST", "path": "/agent/stream", "raw_path": b"/agent/stream",
        "query_string": b"", "headers": [(b"content-type", b"application/json"), (b"x-request-id", b"disconnect")],
        "scheme": "http", "server": ("test", 80), "client": ("test", 1), "http_version": "1.1",
    }, receive, send)
    assert closed.is_set()
    assert any(message["type"] == "http.response.start" for message in sent)
