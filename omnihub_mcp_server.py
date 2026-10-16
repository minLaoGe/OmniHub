#!/usr/bin/env python3
"""
OmniHub Service Manager - Model Context Protocol (MCP) Server
Allows AI Agents (Antigravity, Claude, Cursor, Cline, local agents) to inspect,
start, stop, restart, configure ports, limit memory, and monitor all local AI & web services.
"""

import os
import sys
import json
import asyncio
import httpx
import platform
from pathlib import Path
from typing import Dict, List, Optional, Any
from mcp.server.mcpserver import MCPServer

# Initialize MCP Server
mcp = MCPServer("omnihub-service-manager")

BASE_DIR = Path(__file__).resolve().parent
HUB_API_URL = os.environ.get("OMNIHUB_URL", "http://127.0.0.1:9527")

def _call_hub_api(method: str, path: str, json_data: Optional[dict] = None) -> Any:
    """尝试优先请求运行中的 OmniHub HTTP API，若未运行则回退到本地逻辑"""
    url = f"{HUB_API_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.request(method, url, json=json_data)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None

def _get_local_services_manager():
    """回退：直接导入本地 services_manager 模块执行控制"""
    sys.path.insert(0, str(BASE_DIR))
    from app.services_manager import services_manager
    return services_manager

@mcp.tool()
def list_all_services() -> Dict[str, Any]:
    """
    List all local AI & web services managed by OmniHub (e.g. Qwen3.8-27B, ComfyUI, Mac Cleaner).
    Returns running status, port, PID, CPU%, memory usage, max memory quota, and memory exceed flags.
    """
    res = _call_hub_api("GET", "/api/services")
    if res is not None:
        return {"source": "omnihub_api", "services": res}

    # Fallback to local
    sm = _get_local_services_manager()
    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(sm.list_services())
        return {"source": "local_engine", "services": data}
    finally:
        loop.close()

@mcp.tool()
def start_service(service_id: str, custom_port: Optional[int] = None) -> Dict[str, Any]:
    """
    Start a designated local service (e.g. 'qwen27b', 'comfyui', 'mac_cleaner').
    Optionally pass custom_port to override and launch on a specific port.
    """
    if custom_port:
        # Update port first
        configure_service_port_and_memory(service_id, port=custom_port)

    res = _call_hub_api("POST", f"/api/services/{service_id}/start")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sm.start_service(service_id))
    finally:
        loop.close()

@mcp.tool()
def stop_service(service_id: str) -> Dict[str, Any]:
    """
    Stop a running service safely, cleanly killing child processes and releasing the port.
    """
    res = _call_hub_api("POST", f"/api/services/{service_id}/stop")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sm.stop_service(service_id))
    finally:
        loop.close()

@mcp.tool()
def restart_service(service_id: str) -> Dict[str, Any]:
    """
    Restart a local service.
    """
    res = _call_hub_api("POST", f"/api/services/{service_id}/restart")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sm.restart_service(service_id))
    finally:
        loop.close()

@mcp.tool()
def configure_service_port_and_memory(
    service_id: str,
    port: Optional[int] = None,
    max_memory_mb: Optional[int] = None,
    memory_limit_action: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure a service's listen port and memory limits.
    - service_id: target service (e.g. 'qwen27b', 'comfyui')
    - port: new listen port number (e.g. 8090, 8188)
    - max_memory_mb: memory ceiling in Megabytes (e.g. 4096 for 4GB, 8192 for 8GB, 0 for unlimited)
    - memory_limit_action: protection action when exceeded: 'alert' (warn only), 'restart' (auto reload), or 'stop' (safe terminate)
    """
    payload = {}
    if port is not None:
        payload["port"] = int(port)
    if max_memory_mb is not None:
        payload["max_memory_mb"] = int(max_memory_mb)
    if memory_limit_action:
        payload["memory_limit_action"] = memory_limit_action

    res = _call_hub_api("PUT", f"/api/services/{service_id}", payload)
    if res is not None:
        return res

    sm = _get_local_services_manager()
    return sm.update_service(service_id, payload)

@mcp.tool()
def get_service_logs(service_id: str, limit: int = 80) -> Dict[str, Any]:
    """
    Fetch the recent console output logs of a service for troubleshooting or error inspection.
    """
    res = _call_hub_api("GET", f"/api/services/{service_id}/logs?limit={limit}")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    if service_id in sm.services:
        logs = list(sm.services[service_id].logs)[-limit:]
        return {"service_id": service_id, "logs": logs}
    return {"error": f"Service {service_id} not found"}

@mcp.tool()
def get_system_health_metrics() -> Dict[str, Any]:
    """
    Get host system resource metrics: OS platform (macOS/Win/Linux), CPU load, memory usage, free disk space, and total running services.
    """
    res = _call_hub_api("GET", "/api/system/stats")
    if res is not None:
        return res

    import psutil
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    return {
        "os": platform.system(),
        "cpu_percent": cpu_percent,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "memory_percent": mem.percent,
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_percent": disk.percent
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
