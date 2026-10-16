import os
import shutil
import asyncio
import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any

from .config import STATIC_DIR, get_settings, save_settings, AppConfig
from .services_manager import services_manager
from .mcp_manager import mcp_manager
from .proxy import proxy_service_request
from .ai_agent import chat_with_agent

app = FastAPI(
    title="OmniHub - 统一大模型与服务中枢平台",
    description="集服务管理、MCP 注册与调用、多工作区融合与 AI Agent 于一体的统一入口",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ----------------- 页面入口 -----------------
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>OmniHub 正在准备静态资源...</h1>")

# ----------------- 系统总览与指标 -----------------
@app.get("/api/system/stats")
async def get_system_stats():
    import platform
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    services = await services_manager.list_services()
    running_services = sum(1 for s in services if s.get("status") == "RUNNING")

    all_tools = await mcp_manager.list_all_tools()
    total_tools = sum(len(t) for t in all_tools.values())

    os_family = platform.system() # 'Darwin', 'Windows', 'Linux'
    os_name = "macOS" if os_family == "Darwin" else ("Windows" if os_family == "Windows" else "Linux")

    return {
        "os_name": os_name,
        "os_family": os_family,
        "os_release": platform.release(),
        "cpu_percent": cpu_percent,
        "memory": {
            "total_gb": round(mem.total / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "percent": mem.percent
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "free_gb": round(disk.free / (1024**3), 1),
            "percent": disk.percent
        },
        "services_count": len(services),
        "running_services_count": running_services,
        "mcp_servers_count": len(mcp_manager.servers),
        "total_tools_count": total_tools
    }

# ----------------- 服务管理接口 -----------------
@app.get("/api/services")
async def list_services():
    return await services_manager.list_services()

@app.post("/api/services")
async def add_service(service: dict = Body(...)):
    return services_manager.add_service(service)

@app.put("/api/services/{service_id}")
async def update_service(service_id: str, payload: dict = Body(...)):
    return services_manager.update_service(service_id, payload)

@app.delete("/api/services/{service_id}")
async def delete_service(service_id: str):
    return services_manager.delete_service(service_id)

@app.post("/api/services/{service_id}/start")
async def start_service(service_id: str):
    return await services_manager.start_service(service_id)

@app.post("/api/services/{service_id}/stop")
async def stop_service(service_id: str):
    return await services_manager.stop_service(service_id)

@app.post("/api/services/{service_id}/restart")
async def restart_service(service_id: str):
    return await services_manager.restart_service(service_id)

@app.get("/api/services/{service_id}/logs")
async def get_service_logs(service_id: str, limit: int = 500):
    if service_id not in services_manager.services:
        raise HTTPException(status_code=404, detail="Service not found")
    sp = services_manager.services[service_id]
    logs = list(sp.logs)[-limit:]
    return {"logs": logs}

# WebSocket 实时日志流
@app.websocket("/ws/logs/{service_id}")
async def ws_service_logs(websocket: WebSocket, service_id: str):
    await websocket.accept()
    if service_id not in services_manager.services:
        await websocket.send_text(f"Service {service_id} not found.")
        await websocket.close()
        return

    sp = services_manager.services[service_id]
    # Send historical logs first
    for log_line in list(sp.logs)[-100:]:
        await websocket.send_text(log_line)

    queue = sp.add_listener()
    try:
        while True:
            line = await queue.get()
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        sp.remove_listener(queue)

# ----------------- MCP 管理接口 -----------------
@app.get("/api/mcp/servers")
async def list_mcp_servers():
    return list(mcp_manager.servers.values())

@app.post("/api/mcp/servers")
async def register_mcp_server(config: dict = Body(...)):
    return mcp_manager.register_server(config)

@app.delete("/api/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    return mcp_manager.delete_server(server_id)

@app.get("/api/mcp/tools")
async def list_all_mcp_tools():
    return await mcp_manager.list_all_tools()

@app.post("/api/mcp/call")
async def call_mcp_tool(payload: dict = Body(...)):
    server_id = payload.get("server_id", "builtin")
    tool_name = payload.get("tool_name")
    arguments = payload.get("arguments", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
    return await mcp_manager.call_tool(server_id, tool_name, arguments)

# ----------------- AI Agent 对话接口 -----------------
@app.post("/api/ai/chat")
async def ai_chat(payload: dict = Body(...)):
    messages = payload.get("messages", [])
    enable_tools = payload.get("enable_tools", True)

    async def stream_generator():
        async for chunk in chat_with_agent(messages, enable_tools=enable_tools):
            yield chunk

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

# ----------------- 系统设置 -----------------
@app.get("/api/settings")
async def get_system_settings():
    return get_settings().dict()

@app.post("/api/settings")
async def update_system_settings(settings: dict = Body(...)):
    cfg = AppConfig(**settings)
    save_settings(cfg)
    return {"success": True, "settings": cfg.dict()}

# ----------------- 统一反向代理网关 -----------------
@app.api_route("/proxy/{service_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_endpoint(service_id: str, path: str, request: Request):
    return await proxy_service_request(service_id, path, request)
