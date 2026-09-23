export default def get_weather(params: dict):
	result = {"status": None, "response": {"data": ""}}
	if not isinstance(params, dict):
		result["status"] = "error"
		result["response"]["data"] = "params 必须是字典"
		return result

	if params["city"] not in params:
		result["status"] = "error"
		result["response"]["data"] = "城市不能为空"
		return result
	
	if not isinstance(params["city"], str) or params["city"].strip() == "": 
		result["status"] = "error"
		result["response"]["data"] = "城市不能为空"
		return result
	
	if params["city"] == "北京":
		result["status"] = "success"
		result["response"]["data"] = "北京今天适合跑步"
		return result
	
	else:
		result["status"] = "error"
		result["response"]["data"] = "城市错误"
		return result