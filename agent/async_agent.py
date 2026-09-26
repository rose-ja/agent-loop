from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from model.fake_model import fake_model
from tools.get_weather import get_weather

logger = logging.getLogger(__name__)


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    question: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=5, ge=1, le=100, strict=True)
    max_retries: int = Field(default=2, ge=0, le=10, strict=True)
    timeout: float = Field(default=10, gt=0, le=300)
    tool_timeout: float = Field(default=3, gt=0, le=300)
    tool_delay: float = Field(default=0.01, gt=0, le=300)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("timeout", "tool_timeout", "tool_delay", mode="before")
    @classmethod
    def reject_boolean(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean is not a duration")
        return value


AsyncTool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
Model = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass(frozen=True)
class AsyncToolSpec:
    handler: AsyncTool
    idempotent: bool = False


async def async_weather(params: dict[str, Any], delay: float = 0.01) -> dict[str, Any]:
    """Simulate non-blocking I/O, retaining the synchronous weather contract."""
    await asyncio.sleep(delay)
    return get_weather(params)


def failed(code: str, message: str) -> dict[str, Any]:
    return {"type": "failed", "error": {"code": code, "message": message}}


async def run_agent_async(
    question: str,
    *,
    max_steps: int = 5,
    timeout: float = 10,
    tool_timeout: float = 3,
    tool_delay: float = 0.01,
    max_retries: int = 2,
    model: Model = fake_model,
    tools: Mapping[str, AsyncToolSpec] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run a bounded loop. No timeout scope survives an event yield."""
    try:
        options = AgentRequest(question=question, max_steps=max_steps, timeout=timeout,
                               tool_timeout=tool_timeout, tool_delay=tool_delay,
                               max_retries=max_retries)
    except ValidationError:
        yield failed("INVALID_ARGUMENT", "invalid agent arguments")
        return
    if not callable(model) or (tools is not None and (
        not isinstance(tools, Mapping) or any(
            not isinstance(name, str) or not isinstance(spec, AsyncToolSpec)
            or not callable(spec.handler) or not isinstance(spec.idempotent, bool)
            for name, spec in tools.items()
        )
    )):
        yield failed("INVALID_ARGUMENT", "invalid model or tool registry")
        return

    async def weather(params: dict[str, Any]) -> dict[str, Any]:
        return await async_weather(params, options.tool_delay)

    registry = {"get_weather": AsyncToolSpec(weather, True)} if tools is None else tools
    messages: list[dict[str, Any]] = [{"role": "user", "content": options.question}]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + options.timeout
    for step in range(1, options.max_steps + 1):
        yield {"type": "progress", "step": step, "message": "model"}
        if loop.time() >= deadline:
            yield failed("TOTAL_TIMEOUT", "agent deadline exceeded")
            return
        try:
            response = model(messages)
        except Exception:
            logger.exception("model execution failed")
            yield failed("MODEL_ERROR", "model execution failed")
            return
        if loop.time() >= deadline:
            yield failed("TOTAL_TIMEOUT", "agent deadline exceeded")
            return
        if not isinstance(response, dict):
            yield failed("INVALID_MODEL_RESULT", "invalid model response")
            return
        kind = response.get("type")
        if kind == "result":
            answer = response.get("response")
            if isinstance(answer, str) and answer.strip() and len(answer) <= 16000:
                yield {"type": "success", "answer": answer.strip(), "step": step}
            else:
                yield failed("INVALID_MODEL_RESULT", "invalid model answer")
            return
        function = response.get("function")
        if kind != "tool_calling" or not isinstance(function, dict):
            yield failed("INVALID_MODEL_RESULT", "invalid model response")
            return
        name, params = function.get("function_name"), function.get("params")
        if not isinstance(name, str) or not isinstance(params, dict):
            yield failed("INVALID_MODEL_RESULT", "invalid tool call")
            return
        spec = registry.get(name)
        if spec is None:
            yield failed("UNKNOWN_TOOL", "requested tool is not allowed")
            return
        for attempt in range(options.max_retries + 1):
            if loop.time() >= deadline:
                yield failed("TOTAL_TIMEOUT", "agent deadline exceeded")
                return
            tool_deadline = min(deadline, loop.time() + options.tool_timeout)
            try:
                # timeout_at cancels only the tool await, never the consumer at yield.
                async with asyncio.timeout_at(tool_deadline):
                    result = await spec.handler(params)
            except TimeoutError:
                result = {"status": "error", "error_code": "TIMEOUT", "retryable": True}
            except Exception:
                logger.exception("tool execution failed")
                yield failed("TOOL_EXCEPTION", "tool execution failed")
                return
            if loop.time() >= deadline:
                yield failed("TOTAL_TIMEOUT", "agent deadline exceeded")
                return
            if not isinstance(result, dict) or result.get("status") not in ("success", "error"):
                yield failed("INVALID_TOOL_RESULT", "invalid tool response")
                return
            if result["status"] == "success":
                payload = result.get("response")
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), str) or len(payload["data"]) > 16000:
                    yield failed("INVALID_TOOL_RESULT", "invalid tool payload")
                    return
                messages.append({"role": "tool", "tool_name": name, "content": result})
                yield {"type": "progress", "step": step, "message": "tool complete"}
                break
            is_timeout = result.get("error_code") == "TIMEOUT"
            if is_timeout and result.get("retryable") is True and spec.idempotent and attempt < options.max_retries:
                yield {"type": "progress", "step": step, "message": "retry", "retry": attempt + 1}
                continue
            yield failed("TOOL_TIMEOUT" if is_timeout else "TOOL_ERROR", "tool execution failed")
            return
    yield failed("MAX_STEPS", "maximum steps reached")
