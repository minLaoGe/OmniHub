import json
import httpx
from typing import AsyncGenerator, List, Dict, Any
from .config import get_settings
from .mcp_manager import mcp_manager

async def convert_mcp_tools_to_openai_schema() -> List[dict]:
    """将注册的 MCP 工具及内置服务控制工具转为 OpenAI tools 格式 (使用缓存以实现毫秒级响应)"""
    all_tools = await mcp_manager.list_all_tools(force_refresh=False)
    openai_tools = []

    for server_id, tools in all_tools.items():
        for tool in tools:
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
    """高性能 AI Agent 对话流引擎，支持打字机流式推流、思考链提取与自主 MCP 工具调度"""
    settings = get_settings()
    api_base = settings.llm_api_base.rstrip("/")
    url = f"{api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json"
    }

    # 毫秒级准备工具列表
    tools = await convert_mcp_tools_to_openai_schema() if enable_tools else None
    current_messages = list(messages)

    # 最多允许 4 轮工具调用与自我修正循环
    for iteration in range(4):
        payload = {
            "model": settings.llm_model_name,
            "messages": current_messages,
            "stream": True, # 开启流式推流，消除等待卡顿
            "temperature": 0.7
        }
        if tools and len(tools) > 0:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        full_content = ""
        full_reasoning = ""
        tool_calls_accumulator = {}

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        err_text = await resp.aread()
                        err_msg = err_text.decode('utf-8', errors='replace')
                        yield json.dumps({
                            "type": "error",
                            "content": f"大模型接口请求异常 ({resp.status_code}): {err_msg}。请确认本地服务端口 8088 是否正常运行。"
                        }) + "\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            choice = chunk.get("choices", [{}])[0]
                            delta = choice.get("delta", {})

                            # 1. 思考链过程 (DeepSeek-R1 / Qwen3.8-Thinking)
                            reasoning_chunk = delta.get("reasoning_content") or delta.get("thinking")
                            if reasoning_chunk:
                                full_reasoning += reasoning_chunk
                                yield json.dumps({
                                    "type": "reasoning_chunk",
                                    "content": reasoning_chunk
                                }) + "\n"

                            # 2. 正常文本回复增量
                            content_chunk = delta.get("content")
                            if content_chunk:
                                full_content += content_chunk
                                yield json.dumps({
                                    "type": "content_chunk",
                                    "content": content_chunk
                                }) + "\n"

                            # 3. 工具调用增量搜集
                            if "tool_calls" in delta and delta["tool_calls"]:
                                for tc in delta["tool_calls"]:
                                    tc_idx = tc.get("index", 0)
                                    if tc_idx not in tool_calls_accumulator:
                                        tool_calls_accumulator[tc_idx] = {
                                            "id": tc.get("id", f"call_{tc_idx}"),
                                            "name": tc.get("function", {}).get("name", ""),
                                            "arguments": ""
                                        }
                                    if "function" in tc:
                                        fn = tc["function"]
                                        if fn.get("name"):
                                            tool_calls_accumulator[tc_idx]["name"] += fn.get("name")
                                        if fn.get("arguments"):
                                            tool_calls_accumulator[tc_idx]["arguments"] += fn.get("arguments")

                        except Exception:
                            continue

        except httpx.ConnectError:
            yield json.dumps({
                "type": "error",
                "content": f"无法连接到大模型服务 ({url})！请检查 Qwen3.8-27B 服务是否已启动且端口为 8088。"
            }) + "\n"
            return
        except Exception as e:
            yield json.dumps({
                "type": "error",
                "content": f"与大模型通信异常: {str(e)}"
            }) + "\n"
            return

        # 如果没有触发工具调用，本次回答即最终结果
        if not tool_calls_accumulator:
            yield json.dumps({
                "type": "done",
                "content": full_content
            }) + "\n"
            return

        # 组织工具调用并执行
        assistant_tool_calls = []
        for tc_idx, tc_data in sorted(tool_calls_accumulator.items()):
            assistant_tool_calls.append({
                "id": tc_data["id"],
                "type": "function",
                "function": {
                    "name": tc_data["name"],
                    "arguments": tc_data["arguments"]
                }
            })

        current_messages.append({
            "role": "assistant",
            "content": full_content or None,
            "tool_calls": assistant_tool_calls
        })

        # 执行每一个工具调用
        for tc in assistant_tool_calls:
            raw_fn_name = tc["function"]["name"]
            args_str = tc["function"]["arguments"]
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

            # 执行工具
            tool_res = await mcp_manager.call_tool(server_id, tool_name, args)

            yield json.dumps({
                "type": "tool_call_result",
                "server_id": server_id,
                "tool_name": tool_name,
                "result": tool_res
            }) + "\n"

            current_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_res, ensure_ascii=False)
            })

    yield json.dumps({
        "type": "done",
        "content": full_content
    }) + "\n"
