def fake_model(messages):
    has_tool = False
    for message in messages:
        if message["role"] == "tool" and message["tool_name"] == "get_weather":
            has_tool = True
    if not has_tool:
        return {
			"type": "tool_calling",
			"function_name": "get_weather",
			"function": {
				"params": {
					"city": "北京"
				}
			}
		}
	if has_tool:
		return {
			"type": "result",
			"result": {
				"data": "今天北京适合跑步"
			}
		}