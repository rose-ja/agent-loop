from typing import Any


def get_weather(params: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic weather data for the experiment."""
    if not isinstance(params, dict):
        return {"status": "error", "response": {"data": "params 必须是字典"}}

    city = params.get("city")
    if not isinstance(city, str) or not city.strip():
        return {"status": "error", "response": {"data": "城市不能为空"}}

    city = city.strip()
    if city != "北京":
        return {"status": "error", "response": {"data": "城市错误"}}

    return {"status": "success", "response": {"data": "北京今天适合跑步"}}
