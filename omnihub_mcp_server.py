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

@mcp.tool()
def get_service_project_path(service_id: str) -> Dict[str, Any]:
    """
    Get the exact local filesystem project path, working directory (cwd), and entry script path for any service.
    Returns:
    - service_id: Identifier of the service (e.g. 'qwen27b', 'comfyui', 'mac_cleaner', 'rea_hub')
    - name: Human-readable service name
    - project_path: Absolute directory path of the service's project workspace
    - cwd: Working directory configured for process execution
    - entry_script: Full path to the executable or script
    - path_exists: Whether the directory exists on local disk
    - key_files: Prominent code/config files found in the project root
    """
    res = _call_hub_api("GET", "/api/services")
    if res and isinstance(res, list):
        for s in res:
            if s.get("id") == service_id:
                return {
                    "service_id": s.get("id"),
                    "name": s.get("name"),
                    "project_path": s.get("project_path"),
                    "cwd": s.get("cwd"),
                    "entry_script": s.get("entry_script"),
                    "path_exists": s.get("path_exists"),
                    "port": s.get("port"),
                    "status": s.get("status"),
                    "key_files": s.get("key_files", [])
                }

    # Fallback to local
    sm = _get_local_services_manager()
    if service_id in sm.services:
        cfg = sm.services[service_id].config
        p_info = sm.resolve_service_paths(cfg)
        return {
            "service_id": service_id,
            "name": cfg.get("name"),
            "project_path": p_info.get("project_path"),
            "cwd": p_info.get("cwd"),
            "entry_script": p_info.get("entry_script"),
            "path_exists": p_info.get("path_exists"),
            "port": cfg.get("port"),
            "status": sm.services[service_id].status,
            "key_files": p_info.get("key_files", [])
        }
    return {"error": f"Service '{service_id}' not found"}

@mcp.tool()
def get_omnihub_project_path() -> Dict[str, Any]:
    """
    Get OmniHub's own root repository and project path, along with configuration files.
    """
    res = _call_hub_api("GET", "/api/system/project")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    return sm.get_omnihub_info()

@mcp.tool()
def reveal_service_in_explorer(service_id: str) -> Dict[str, Any]:
    """
    Open the project directory of a service in the host OS file browser (macOS Finder / Windows File Explorer).
    """
    res = _call_hub_api("POST", f"/api/services/{service_id}/reveal")
    if res is not None:
        return res

    sm = _get_local_services_manager()
    return sm.reveal_in_explorer(service_id)

def _get_local_apps_manager():
    """回退：直接导入本地 apps_manager 模块执行应用管控"""
    sys.path.insert(0, str(BASE_DIR))
    from app.apps_manager import apps_manager
    return apps_manager

@mcp.tool()
def list_system_apps(search: Optional[str] = None, only_running: bool = False) -> Dict[str, Any]:
    """
    List installed desktop applications and running processes on the host machine.
    Returns app names, PIDs, memory usage (MB), CPU%, disk footprint, install paths, and memory limits.
    """
    params = {}
    if search:
        params["search"] = search
    if only_running:
        params["only_running"] = "true"
    
    query_str = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    res = _call_hub_api("GET", f"/api/apps{query_str}")
    if res is not None:
        return {"source": "omnihub_api", "apps": res}

    am = _get_local_apps_manager()
    apps = am.get_all_apps(search=search or "", only_running=only_running)
    return {"source": "local_engine", "apps": apps}

@mcp.tool()
def trim_app_memory(app_name: str) -> Dict[str, Any]:
    """
    Compress and release physical working set memory for a running application (e.g. 'douyin', 'chrome').
    Calls Windows EmptyWorkingSet natively without killing or restarting the app.
    """
    # First find app details
    apps_res = list_system_apps(search=app_name, only_running=True)
    matched = None
    for a in apps_res.get("apps", []):
        if app_name.lower() in a["name"].lower() or any(app_name.lower() in p.lower() for p in a.get("process_names", [])):
            matched = a
            break

    if not matched:
        return {"success": False, "message": f"未找到正在运行的目标应用: {app_name}"}

    payload = {
        "pids": matched.get("pids", []),
        "process_names": matched.get("process_names", [])
    }
    res = _call_hub_api("POST", "/api/apps/trim", json_data=payload)
    if res is not None:
        return res

    am = _get_local_apps_manager()
    return am.trim_app_memory(matched.get("pids", []), matched.get("process_names", []))

@mcp.tool()
def kill_app_process(app_name: str) -> Dict[str, Any]:
    """
    Force terminate all processes associated with the designated application.
    """
    apps_res = list_system_apps(search=app_name, only_running=True)
    matched = None
    for a in apps_res.get("apps", []):
        if app_name.lower() in a["name"].lower() or any(app_name.lower() in p.lower() for p in a.get("process_names", [])):
            matched = a
            break

    if not matched:
        return {"success": False, "message": f"未找到正在运行的目标应用: {app_name}"}

    payload = {
        "process_names": matched.get("process_names", []),
        "pids": matched.get("pids", [])
    }
    res = _call_hub_api("POST", "/api/apps/kill", json_data=payload)
    if res is not None:
        return res

    am = _get_local_apps_manager()
    return am.kill_app(matched.get("process_names", []), matched.get("pids", []))

@mcp.tool()
def set_app_memory_limit(app_name: str, max_memory_mb: int, action: str = "trim") -> Dict[str, Any]:
    """
    Configure background memory quota guard for an application (e.g. Douyin / 抖音 max 800MB).
    action options: 'trim' (compress memory working set), 'kill' (terminate process), 'alert' (log only).
    """
    payload = {
        "app_id": app_name,
        "max_memory_mb": max_memory_mb,
        "action": action,
        "process_names": [app_name if app_name.endswith('.exe') else f"{app_name}.exe"],
        "enabled": True
    }
    res = _call_hub_api("POST", "/api/apps/rules", json_data=payload)
    if res is not None:
        return res

    am = _get_local_apps_manager()
    return am.set_app_rule(app_name, max_memory_mb, action, payload["process_names"], True)

@mcp.tool()
def reveal_app_in_explorer(launch_path: Optional[str] = None, install_location: Optional[str] = None, app_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Open the host OS file explorer (Windows Explorer / macOS Finder) and highlight the application's executable.
    """
    payload = {
        "launch_path": launch_path or "",
        "install_location": install_location or "",
        "app_name": app_name or ""
    }
    res = _call_hub_api("POST", "/api/apps/open_dir", json_data=payload)
    if res is not None:
        return res

    am = _get_local_apps_manager()
    return am.open_app_directory(
        install_location=install_location or "",
        launch_path=launch_path or "",
        app_name=app_name or ""
    )

@mcp.tool()
def get_memory_guardian_logs(limit: int = 20) -> Dict[str, Any]:
    """
    Retrieve recent background memory guardian logs and memory compression events.
    """
    res = _call_hub_api("GET", f"/api/apps/guardian_logs?limit={limit}")
    if res is not None:
        return {"logs": res}

    am = _get_local_apps_manager()
    return {"logs": am.get_guardian_logs(limit)}

if __name__ == "__main__":
    mcp.run(transport="stdio")
