import os
import sys
import json
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .config import MCP_SERVERS_FILE
from .services_manager import services_manager

class MCPManager:
    def __init__(self):
        self.servers: Dict[str, dict] = {}
        self.cached_tools: Dict[str, List[dict]] = {}
        self.load_servers()

    def load_servers(self):
        if not MCP_SERVERS_FILE.exists():
            MCP_SERVERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(MCP_SERVERS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return
        try:
            with open(MCP_SERVERS_FILE, "r", encoding="utf-8") as f:
                servers = json.load(f)
            self.servers.clear()
            for s in servers:
                self.servers[s["id"]] = s
        except Exception as e:
            print(f"Error loading MCP servers: {e}", file=sys.stderr)

    def save_servers(self):
        with open(MCP_SERVERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(self.servers.values()), f, ensure_ascii=False, indent=2)

    def get_builtin_tools(self) -> List[dict]:
        """内置服务管理 MCP 工具集"""
        return [
            {
                "name": "omnihub_list_services",
                "description": "列出 OmniHub 管理的所有本地服务（如 Qwen3.8-27B大模型、ComfyUI绘画、Mac清理工具等）及其运行状态、端口和PID",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "omnihub_start_service",
                "description": "启动指定的本地服务（如 qwen27b, comfyui, mac_cleaner）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {
                            "type": "string",
                            "description": "服务的唯一标识符，例如 'qwen27b', 'comfyui', 'mac_cleaner'"
                        }
                    },
                    "required": ["service_id"]
                }
            },
            {
                "name": "omnihub_stop_service",
                "description": "停止指定的本地服务",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {
                            "type": "string",
                            "description": "服务的唯一标识符"
                        }
                    },
                    "required": ["service_id"]
                }
            },
            {
                "name": "omnihub_restart_service",
                "description": "重启指定的本地服务",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {
                            "type": "string",
                            "description": "服务的唯一标识符"
                        }
                    },
                    "required": ["service_id"]
                }
            },
            {
                "name": "omnihub_get_service_project_path",
                "description": "查询指定服务的本地源码项目路径、工作目录(cwd)、启动脚本路径和关键文件列表",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {
                            "type": "string",
                            "description": "服务唯一标识符，如 'qwen27b', 'comfyui', 'mac_cleaner', 'rea_hub'"
                        }
                    },
                    "required": ["service_id"]
                }
            },
            {
                "name": "omnihub_get_project_info",
                "description": "获取 OmniHub 统一中枢平台自身的本地项目根路径及配置文件信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "omnihub_reveal_service_in_explorer",
                "description": "在宿主机文件浏览器(macOS 访达 Finder / Windows 资源管理器)中打开指定服务的项目文件夹",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_id": {
                            "type": "string",
                            "description": "服务唯一标识符"
                        }
                    },
                    "required": ["service_id"]
                }
            }
        ]

    async def execute_builtin_tool(self, name: str, args: dict) -> Any:
        if name == "omnihub_list_services":
            return await services_manager.list_services()
        elif name == "omnihub_start_service":
            return await services_manager.start_service(args.get("service_id"))
        elif name == "omnihub_stop_service":
            return await services_manager.stop_service(args.get("service_id"))
        elif name == "omnihub_restart_service":
            return await services_manager.restart_service(args.get("service_id"))
        elif name == "omnihub_get_service_project_path":
            sid = args.get("service_id")
            if sid in services_manager.services:
                cfg = services_manager.services[sid].config
                p_info = services_manager.resolve_service_paths(cfg)
                return {
                    "service_id": sid,
                    "name": cfg.get("name"),
                    **p_info
                }
            return {"error": f"Service '{sid}' not found"}
        elif name == "omnihub_get_project_info":
            return services_manager.get_omnihub_info()
        elif name == "omnihub_reveal_service_in_explorer":
            return services_manager.reveal_in_explorer(args.get("service_id"))
        else:
            raise ValueError(f"Unknown builtin tool: {name}")

    async def list_tools_for_server(self, server_id: str) -> List[dict]:
        if server_id == "builtin":
            return self.get_builtin_tools()

        if server_id not in self.servers:
            return []

        server_cfg = self.servers[server_id]
        if not server_cfg.get("enabled", True):
            return []

        # Connect and query
        command = server_cfg.get("command")
        args = server_cfg.get("args", [])
        env_vars = os.environ.copy()
        if server_cfg.get("env"):
            env_vars.update(server_cfg.get("env"))

        try:
            params = StdioServerParameters(command=command, args=args, env=env_vars)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    tool_list = []
                    for t in tools_result.tools:
                        schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", {})
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump()
                        elif hasattr(schema, "dict"):
                            schema = schema.dict()

                        tool_list.append({
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": schema if isinstance(schema, dict) else {}
                        })
                    self.cached_tools[server_id] = tool_list
                    return tool_list
        except Exception as e:
            print(f"Error connecting to MCP server {server_id}: {e}", file=sys.stderr)
            # return cached if exists
            return self.cached_tools.get(server_id, [])

    async def list_all_tools(self, force_refresh: bool = False) -> Dict[str, List[dict]]:
        results = {
            "builtin": self.get_builtin_tools()
        }
        for sid in self.servers:
            if not force_refresh and sid in self.cached_tools and len(self.cached_tools[sid]) > 0:
                results[sid] = self.cached_tools[sid]
            else:
                results[sid] = await self.list_tools_for_server(sid)
        return results

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> dict:
        if server_id == "builtin" or tool_name.startswith("omnihub_"):
            try:
                res = await self.execute_builtin_tool(tool_name, arguments)
                return {"success": True, "result": res}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if server_id not in self.servers:
            return {"success": False, "error": f"MCP 服务器 {server_id} 未注册"}

        server_cfg = self.servers[server_id]
        command = server_cfg.get("command")
        args = server_cfg.get("args", [])
        env_vars = os.environ.copy()
        if server_cfg.get("env"):
            env_vars.update(server_cfg.get("env"))

        try:
            params = StdioServerParameters(command=command, args=args, env=env_vars)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

                    # Extract content
                    content_list = []
                    if hasattr(result, "content") and result.content:
                        for item in result.content:
                            if hasattr(item, "text"):
                                content_list.append(item.text)
                            else:
                                content_list.append(str(item))

                    return {
                        "success": not getattr(result, "isError", False),
                        "content": "\n".join(content_list) if content_list else "",
                        "raw": str(result)
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def register_server(self, config: dict) -> dict:
        sid = config.get("id")
        if not sid:
            sid = f"mcp_{len(self.servers) + 1}"
            config["id"] = sid

        config["enabled"] = config.get("enabled", True)
        self.servers[sid] = config
        self.save_servers()
        return {"success": True, "server": config}

    def delete_server(self, server_id: str) -> dict:
        if server_id in self.servers:
            del self.servers[server_id]
            if server_id in self.cached_tools:
                del self.cached_tools[server_id]
            self.save_servers()
            return {"success": True, "message": "MCP 服务器已删除"}
        return {"success": False, "message": "未找到指定 MCP 服务器"}

mcp_manager = MCPManager()
