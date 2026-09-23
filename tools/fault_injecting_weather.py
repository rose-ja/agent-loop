from typing import Any


class FaultInjectingWeatherTool:
    def __init__(self, failures_before_success: int):
        if not isinstance(failures_before_success, int) or failures_before_success < 0:
            raise ValueError("failures_before_success 必须是非负整数")
        self.failures_before_success = failures_before_success
        self.call_count = 0

    def __call__(self, params: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        if self.call_count <= self.failures_before_success:
            return {
                "status": "error",
                "error_code": "TIMEOUT",
                "message": "天气服务请求超时",
                "retryable": True,
            }
        return {
            "status": "success",
            "response": {"data": "北京今天适合跑步"},
        }
