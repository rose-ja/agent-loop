from typing import Any


def fake_model(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a deterministic two-turn model response for the experiment."""
    has_weather_result = any(
        message.get("role") == "tool"
        and message.get("tool_name") == "get_weather"
        for message in messages
    )

    if not has_weather_result:
        return {
            "type": "tool_calling",
            "function": {
                "function_name": "get_weather",
                "params": {"city": "北京"},
            },
        }

    return {"type": "result", "response": "今天北京适合跑步"}
