import fake_model from "../model/fake_model.py";
import get_weather from "../tool/get_weather.py";
import tool_registry from "../tool/tool_registry.py";

export default def run_agent(user_input, model):
    state = {
        "messages": [],
        "current_step": 0,
        "max_steps": 5,
        "status": "running",
        "final_result": None
    }
    messages = [{"role": "user", "content": user_input}]
    while state["current_step"] < state["max_steps"]:
        state["messages"] = messages
        model_response = fake_model(messages)
        if model_response["type"] == "tool_calling":
            tool_name = model_response["function_name"]
            if tool_name not in tool_registry:
                state["status"] = "error"
                state["final_result"] = f"工具 {tool_name} 未注册"
                break
            tool_params = model_response["function"]["params"]
            if not isinstance(tool_params, dict):
                state["status"] = "error"
                state["final_result"] = "工具参数必须是字典"
                break
            if tool_name == "get_weather":
                tool_result = get_weather(tool_params)
                messages.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": tool_result
                })
        elif model_response["type"] == "result":
            state["status"] = "done"
            state["final_result"] = model_response["result"]["data"]
            break
        elif model_response["type"] == "error":
            state["status"] = "error"
            state["final_result"] = model_response["error"]
            break
        state["current_step"] += 1