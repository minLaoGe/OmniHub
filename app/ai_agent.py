import json
import httpx
from typing import AsyncGenerator, List, Dict, Any
from .config import get_settings
from .mcp_manager import mcp_manager

async def convert_mcp_tools_to_openai_schema() -> List[dict]:
    """将注册的 MCP 工具及内置服务控制工具转为 OpenAI tools 格式"""
    all_tools = await mcp_manager.list_all_tools()
    openai_tools = []

    for server_id, tools in all_tools.items():
        for tool in tools:
            # Format tool name: server__toolname to avoid conflicts
            if server_id == "builtin":
                full_name = tool["name"]
            else:
                full_name = f"{server_id}__{tool['name']}"

            schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": full_name,
                    "description": f"[{server_id}] {tool.get('description', '')}",
                    "parameters": schema
                }
            })
    return openai_tools

async def chat_with_agent(messages: List[Dict[str, Any]], enable_tools: bool = True) -> AsyncGenerator[str, None]:
    """AI Agent 对话生成器，带自主 MCP 工具调用循环"""
    settings = get_settings()
    api_base = settings.llm_api_base.rstrip("/")
    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json"
    }

    tools = await convert_mcp_tools_to_openai_schema() if enable_tools else None

    # Max 5 iterations of tool calls
    current_messages = list(messages)

    for step in range(5):
        payload = {
            "model": settings.llm_model_name,
            "messages": current_messages,
            "stream": False # Non-stream during tool call decision
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code != 200:
                    yield json.dumps({
                        "type": "error",
                        "content": f"大模型接口请求异常 ({resp.status_code}): {resp.text}"
                    }) + "\n"
                    return

                res_json = resp.json()
                choice = res_json.get("choices", [{}])[0]
                message = choice.get("message", {})
                current_messages.append(message)

                tool_calls = message.get("tool_calls")
                if not tool_calls:
                    # Final response
                    content = message.get("content", "")
                    yield json.dumps({
                        "type": "message",
                        "content": content
                    }) + "\n"
                    return

                # Handle tool calls
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    raw_fn_name = fn.get("name", "")
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args = {}

                    if "__" in raw_fn_name:
                        server_id, tool_name = raw_fn_name.split("__", 1)
                    else:
                        server_id, tool_name = "builtin", raw_fn_name

                    yield json.dumps({
                        "type": "tool_call_start",
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "arguments": args
                    }) + "\n"

                    # Execute tool call
                    tool_res = await mcp_manager.call_tool(server_id, tool_name, args)

                    yield json.dumps({
                        "type": "tool_call_result",
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "result": tool_res
                    }) + "\n"

                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{raw_fn_name}"),
                        "content": json.dumps(tool_res, ensure_ascii=False)
                    })

        except Exception as e:
            yield json.dumps({
                "type": "error",
                "content": f"与大模型通信或工具执行出错: {str(e)}"
            }) + "\n"
            return
