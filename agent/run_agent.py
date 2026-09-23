from typing import Any, Callable

from model.fake_model import fake_model
from tools.tool_register import tool_registry

Model = Callable[[list[dict[str, Any]]], dict[str, Any]]


def run_agent(
    user_input: str,
    max_steps: int = 5,
    model: Model = fake_model,
) -> dict[str, Any]:
    """Run the minimal Agent Loop and return its complete state."""
    state: dict[str, Any] = {
        "messages": [],
        "current_step": 0,
        "max_steps": max_steps,
        "status": "running",
        "final_answer": None,
        "error": None,
    }

    if not isinstance(user_input, str) or not user_input.strip():
        state["status"] = "failed"
        state["error"] = "用户输入不能为空"
        state["messages"] = [{"role": "user", "content": user_input}]
        return state

    if not isinstance(max_steps, int) or max_steps <= 0:
        state["status"] = "failed"
        state["error"] = "max_steps 必须是正整数"
        return state

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_input.strip()}
    ]

    while state["current_step"] < state["max_steps"]:
        state["current_step"] += 1
        model_response = model(messages)

        if not isinstance(model_response, dict):
            state["status"] = "failed"
            state["error"] = "模型响应必须是字典"
            break

        response_type = model_response.get("type")
        if response_type == "error":
            state["status"] = "failed"
            state["error"] = model_response.get("error", "模型返回未知错误")
            break

        if response_type == "result":
            final_answer = model_response.get("response")
            if not isinstance(final_answer, str) or not final_answer.strip():
                state["status"] = "failed"
                state["error"] = "模型最终答案为空或格式无效"
                break
            state["final_answer"] = final_answer
            state["status"] = "done"
            break

        if response_type != "tool_calling":
            state["status"] = "failed"
            state["error"] = f"未知模型响应类型: {response_type}"
            break

        function_data = model_response.get("function")
        if not isinstance(function_data, dict):
            state["status"] = "failed"
            state["error"] = "工具调用缺少 function 对象"
            break

        tool_name = function_data.get("function_name")
        tool_params = function_data.get("params")
        if tool_name not in tool_registry:
            state["status"] = "failed"
            state["error"] = f"工具 {tool_name} 未注册"
            break
        if not isinstance(tool_params, dict):
            state["status"] = "failed"
            state["error"] = "工具参数必须是字典"
            break

        messages.append({
            "role": "assistant",
            "tool_call": {
                "function_name": tool_name,
                "params": tool_params,
            },
        })
        tool_result = tool_registry[tool_name](tool_params)
        messages.append({
            "role": "tool",
            "tool_name": tool_name,
            "content": tool_result,
        })

    if state["status"] == "running":
        state["status"] = "failed"
        state["error"] = "达到最大执行步数"

    state["messages"] = messages
    return state
