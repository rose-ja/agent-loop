from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import secrets
import string
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent.async_agent import AgentRequest, run_agent_async

logger = logging.getLogger(__name__)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_ALLOWED = set(string.ascii_letters + string.digits + "._-")


def _new_request_id() -> str:
    return secrets.token_urlsafe(16)


def _valid_request_id(value: str | None) -> bool:
    return bool(value) and 1 <= len(value) <= 128 and all(char in _ALLOWED for char in value)


def error_payload(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"code": code, "message": message, "request_id": request_id}


class RequestIdMiddleware:
    """Pure ASGI middleware keeps the ContextVar active for the whole stream."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = raw if _valid_request_id(raw) else _new_request_id()
        scope["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


app = FastAPI()
app.add_middleware(RequestIdMiddleware)


def get_request_id(request: Request) -> str:
    return str(request.scope.get("request_id") or request_id_var.get() or _new_request_id())


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = get_request_id(request)
    logger.info("request validation failed: %s", exc.errors())
    return JSONResponse(error_payload("VALIDATION_ERROR", "invalid request", request_id), status_code=422)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        error_payload("HTTP_ERROR", "request not found" if exc.status_code == 404 else "request failed", get_request_id(request)),
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    logger.exception("unhandled request error")
    return JSONResponse(
        error_payload("INTERNAL_ERROR", "internal server error", request_id),
        status_code=500,
        headers={"X-Request-ID": request_id},
    )


@app.post("/agent/stream")
async def agent_stream(
    payload: AgentRequest,
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:

    async def events():
        generator = run_agent_async(**payload.model_dump())
        try:
            async for event in generator:
                event = dict(event)
                event["request_id"] = request_id
                if event.get("type") == "failed":
                    event["error"] = {**event["error"], "request_id": request_id}
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("streaming agent failed")
            failed_event = {"type": "failed", "request_id": request_id,
                            "error": error_payload("INTERNAL_ERROR", "internal server error", request_id)}
            yield f"event: failed\ndata: {json.dumps(failed_event, ensure_ascii=False)}\n\n".encode()
        finally:
            await generator.aclose()

    return StreamingResponse(events(), media_type="text/event-stream")
