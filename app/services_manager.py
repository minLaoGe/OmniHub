import os
import sys
import json
import socket
import asyncio
import platform
import psutil
import subprocess
from typing import Dict, List, Optional, Any
from collections import deque
from pathlib import Path
from .config import SERVICES_FILE

CURRENT_OS = platform.system() # 'Darwin' (macOS), 'Windows', 'Linux'

class ServiceProcess:
    def __init__(self, config: dict):
        self.config = config
        self.id = config["id"]
        self.process: Optional[asyncio.subprocess.Process] = None
        self.pid: Optional[int] = None
        self.status: str = "STOPPED" # STOPPED, STARTING, RUNNING, ERROR
        self.memory_exceeded: bool = False
        self.logs: deque = deque(maxlen=2000)
        self.listeners: List[asyncio.Queue] = []
        self._guard_task: Optional[asyncio.Task] = None

    def log(self, line: str):
        line = line.rstrip("\r\n")
        self.logs.append(line)
        # Notify active listeners
        for q in list(self.listeners):
            try:
                q.put_nowait(line)
            except Exception:
                pass

    def add_listener(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.listeners.append(q)
        return q

    def remove_listener(self, q: asyncio.Queue):
        if q in self.listeners:
            self.listeners.remove(q)

class ServicesManager:
    def __init__(self):
        self.services: Dict[str, ServiceProcess] = {}
        self.load_services()

    def load_services(self):
        if not SERVICES_FILE.exists():
            return
        try:
            with open(SERVICES_FILE, "r", encoding="utf-8") as f:
                configs = json.load(f)
            for cfg in configs:
                # Default fallback fields for memory limits
                if "max_memory_mb" not in cfg:
                    cfg["max_memory_mb"] = 0 # 0 means unlimited
                if "memory_limit_action" not in cfg:
                    cfg["memory_limit_action"] = "alert" # alert, restart, stop

                s_id = cfg["id"]
                if s_id not in self.services:
                    self.services[s_id] = ServiceProcess(cfg)
                else:
                    self.services[s_id].config = cfg
        except Exception as e:
            print(f"Error loading services: {e}", file=sys.stderr)

    def save_services(self):
        configs = [s.config for s in self.services.values()]
        with open(SERVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)

    def is_port_open(self, port: Optional[int], host: str = "127.0.0.1") -> bool:
        if not port or port <= 0:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            result = sock.connect_ex((host, port))
            return result == 0

    def find_pids_by_port(self, port: Optional[int]) -> List[int]:
        if not port or port <= 0:
            return []
        pids = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    if conn.pid:
                        pids.append(conn.pid)
        except Exception:
            pass
        return list(set(pids))

    def get_process_tree_metrics(self, pid: int) -> tuple[float, float]:
        """跨平台递归统计进程树的 CPU 和内存占用 (CPU%, MemoryMB)"""
        try:
            parent = psutil.Process(pid)
            if not parent.is_running():
                return 0.0, 0.0

            total_mem = parent.memory_info().rss
            cpu = parent.cpu_percent(interval=None)

            try:
                for child in parent.children(recursive=True):
                    if child.is_running():
                        total_mem += child.memory_info().rss
                        cpu += child.cpu_percent(interval=None)
            except Exception:
                pass

            return round(cpu, 1), round(total_mem / (1024 * 1024), 1)
        except Exception:
            return 0.0, 0.0

    async def get_service_status(self, service_id: str) -> dict:
        if service_id not in self.services:
            return {"error": "Not found"}

        sp = self.services[service_id]
        port = sp.config.get("port")
        port_open = self.is_port_open(port)

        cpu_percent = 0.0
        memory_mb = 0.0
        real_pid = None

        if sp.process and sp.process.returncode is None:
            real_pid = sp.process.pid
        elif port_open:
            pids = self.find_pids_by_port(port)
            if pids:
                real_pid = pids[0]

        if real_pid:
            cpu_percent, memory_mb = self.get_process_tree_metrics(real_pid)
            if memory_mb > 0 or port_open:
                sp.status = "RUNNING"
            else:
                sp.status = "STOPPED"
        else:
            sp.status = "RUNNING" if port_open else "STOPPED"

        max_mem = sp.config.get("max_memory_mb", 0)
        is_exceeded = (max_mem > 0) and (memory_mb > max_mem)

        return {
            "id": sp.id,
            "name": sp.config.get("name"),
            "description": sp.config.get("description"),
            "category": sp.config.get("category"),
            "icon": sp.config.get("icon", "server"),
            "port": port,
            "url": sp.config.get("url"),
            "status": sp.status,
            "pid": real_pid,
            "cpu_percent": cpu_percent,
            "memory_mb": memory_mb,
            "max_memory_mb": max_mem,
            "memory_limit_action": sp.config.get("memory_limit_action", "alert"),
            "memory_exceeded": is_exceeded or sp.memory_exceeded,
            "port_open": port_open,
            "auto_start": sp.config.get("auto_start", False),
            "command": sp.config.get("command"),
            "args": sp.config.get("args", []),
            "cwd": sp.config.get("cwd")
        }

    async def list_services(self) -> List[dict]:
        results = []
        for sid in self.services:
            results.append(await self.get_service_status(sid))
        return results

    async def _memory_guard(self, sp: ServiceProcess):
        """跨平台内存守卫循环：检测超限并执行防护动作"""
        max_mem = sp.config.get("max_memory_mb", 0)
        action = sp.config.get("memory_limit_action", "alert")

        try:
            while sp.status == "RUNNING" and sp.process and sp.process.returncode is None:
                await asyncio.sleep(2.0)
                if not max_mem or max_mem <= 0:
                    continue

                _, mem_mb = self.get_process_tree_metrics(sp.process.pid)
                if mem_mb > max_mem:
                    sp.memory_exceeded = True
                    warning_msg = f"⚠️ [OmniHub 内存限制预警] 服务 '{sp.config['name']}' 内存占用 {mem_mb} MB 已超过上限 {max_mem} MB！(策略: {action})"
                    sp.log(warning_msg)
                    print(warning_msg, file=sys.stderr)

                    if action == "restart":
                        sp.log(f"🔄 [OmniHub 内存守卫] 触发自动重启策略以回收内存...")
                        asyncio.create_task(self.restart_service(sp.id))
                        break
                    elif action == "stop":
                        sp.log(f"🛑 [OmniHub 内存守卫] 触发安全保护停止服务，防止系统 OOM 死机...")
                        asyncio.create_task(self.stop_service(sp.id))
                        break
                else:
                    sp.memory_exceeded = False
        except asyncio.CancelledError:
            pass
        except Exception as e:
            sp.log(f"[OmniHub 内存守卫异常] {e}")

    def build_command_with_port(self, sp: ServiceProcess) -> tuple[str, List[str]]:
        """构建命令并支持动态替换端口参数（跨平台适配 Windows/Mac/Linux）"""
        port = str(sp.config.get("port") or 8000)
        command = sp.config["command"]
        args = list(sp.config.get("args", []))

        # Windows 兼容性转换
        if CURRENT_OS == "Windows":
            if command in ["/bin/bash", "/bin/zsh", "bash", "zsh"]:
                command = "cmd.exe"
                # If script ends with .sh, on windows prefer cmd /c or python
                args = ["/c"] + args
            elif command == "python3":
                command = "python"

        # 动态替换参数中的端口占位符
        new_args = []
        port_replaced = False
        for arg in args:
            if "{port}" in arg:
                new_args.append(arg.replace("{port}", port))
                port_replaced = True
            elif "--port" == arg:
                new_args.append(arg)
            else:
                new_args.append(arg)

        # 如果没有占位符，但原脚本接受端口参数（如 ./server.sh 8088）
        # 针对 server.sh 等脚本动态追加最新端口
        if not port_replaced and len(new_args) > 0 and new_args[0].endswith("server.sh"):
            if len(new_args) == 1:
                new_args.append(port)
            else:
                new_args[1] = port

        return command, new_args

    async def start_service(self, service_id: str) -> dict:
        if service_id not in self.services:
            return {"success": False, "message": "服务不存在"}

        sp = self.services[service_id]
        current_status = await self.get_service_status(service_id)
        if current_status["status"] == "RUNNING":
            return {"success": True, "message": "服务已在运行中", "pid": current_status["pid"]}

        command, cmd_args = self.build_command_with_port(sp)
        cwd = sp.config.get("cwd") or os.getcwd()

        sp.status = "STARTING"
        sp.memory_exceeded = False
        max_mem = sp.config.get("max_memory_mb", 0)
        mem_info = f"{max_mem} MB" if max_mem > 0 else "无限制"

        sp.log(f"--- [OmniHub] 正在启动服务: {sp.config['name']} ---")
        sp.log(f"--- 目标端口: {sp.config.get('port')} | 内存上限: {mem_info} ---")
        sp.log(f"--- 运行环境: {CURRENT_OS} | 运行目录: {cwd} ---")
        sp.log(f"--- 执行命令: {command} {' '.join(cmd_args)} ---")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if sp.config.get("port"):
            env["PORT"] = str(sp.config.get("port"))

        try:
            # 跨平台子进程拉起
            if CURRENT_OS == "Windows":
                # Windows process creation
                sp.process = await asyncio.create_subprocess_exec(
                    command,
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
                    env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                # macOS / Linux
                sp.process = await asyncio.create_subprocess_exec(
                    command,
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
                    env=env
                )

            sp.pid = sp.process.pid
            sp.status = "RUNNING"
            sp.log(f"--- [OmniHub] 进程成功拉起，PID: {sp.pid} ---")

            # 启动日志读取循环与内存守护循环
            asyncio.create_task(self._stream_process_logs(sp))
            if sp._guard_task and not sp._guard_task.done():
                sp._guard_task.cancel()
            sp._guard_task = asyncio.create_task(self._memory_guard(sp))

            return {"success": True, "message": "启动成功", "pid": sp.pid}
        except Exception as e:
            sp.status = "ERROR"
            sp.log(f"--- [OmniHub 错误] 启动失败: {str(e)} ---")
            return {"success": False, "message": f"启动失败: {str(e)}"}

    async def _stream_process_logs(self, sp: ServiceProcess):
        try:
            while sp.process and sp.process.returncode is None:
                line = await sp.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                sp.log(decoded)
        except Exception as e:
            sp.log(f"[OmniHub] 日志流异常: {e}")
        finally:
            if sp.process:
                return_code = await sp.process.wait()
                sp.log(f"--- [OmniHub] 服务已退出，退出码: {return_code} ---")
            sp.status = "STOPPED"
            sp.pid = None
            if sp._guard_task and not sp._guard_task.done():
                sp._guard_task.cancel()

    async def stop_service(self, service_id: str) -> dict:
        if service_id not in self.services:
            return {"success": False, "message": "服务不存在"}

        sp = self.services[service_id]
        status = await self.get_service_status(service_id)
        pid = status.get("pid")

        sp.log(f"--- [OmniHub] 收到停止服务指令 ---")

        if sp._guard_task and not sp._guard_task.done():
            sp._guard_task.cancel()

        # 优雅终止进程树 (跨平台兼容 Windows, macOS, Linux)
        target_pid = sp.process.pid if (sp.process and sp.process.returncode is None) else pid
        if target_pid:
            try:
                parent = psutil.Process(target_pid)
                # 递归杀掉所有子进程
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except Exception:
                        pass

                parent.terminate()

                # 等待 2 秒，如果仍未退出则强制 kill
                _, alive = psutil.wait_procs(children + [parent], timeout=2.0)
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                sp.log(f"[OmniHub] 终止进程异常: {e}")

        sp.status = "STOPPED"
        sp.pid = None
        sp.memory_exceeded = False
        sp.log(f"--- [OmniHub] 服务已安全停止并释放端口 ---")
        return {"success": True, "message": "服务已停止"}

    async def restart_service(self, service_id: str) -> dict:
        await self.stop_service(service_id)
        await asyncio.sleep(1.0)
        return await self.start_service(service_id)

    def update_service(self, service_id: str, new_data: dict) -> dict:
        """更新服务配置（动态端口、内存限制、命令行等）"""
        if service_id not in self.services:
            return {"success": False, "message": "服务不存在"}

        sp = self.services[service_id]
        cfg = sp.config

        # 更新端口并同步 URL
        if "port" in new_data and new_data["port"]:
            old_port = cfg.get("port")
            new_port = int(new_data["port"])
            cfg["port"] = new_port
            if cfg.get("url"):
                cfg["url"] = cfg["url"].replace(f":{old_port}", f":{new_port}")

        if "max_memory_mb" in new_data:
            cfg["max_memory_mb"] = int(new_data["max_memory_mb"])
        if "memory_limit_action" in new_data:
            cfg["memory_limit_action"] = new_data["memory_limit_action"]
        if "name" in new_data and new_data["name"]:
            cfg["name"] = new_data["name"]
        if "category" in new_data:
            cfg["category"] = new_data["category"]
        if "command" in new_data and new_data["command"]:
            cfg["command"] = new_data["command"]
        if "args" in new_data:
            cfg["args"] = new_data["args"]
        if "cwd" in new_data:
            cfg["cwd"] = new_data["cwd"]
        if "description" in new_data:
            cfg["description"] = new_data["description"]

        self.save_services()
        return {"success": True, "service": cfg}

    def add_service(self, config: dict) -> dict:
        sid = config.get("id")
        if not sid:
            sid = f"srv_{len(self.services) + 1}"
            config["id"] = sid

        if "max_memory_mb" not in config:
            config["max_memory_mb"] = 0
        if "memory_limit_action" not in config:
            config["memory_limit_action"] = "alert"

        self.services[sid] = ServiceProcess(config)
        self.save_services()
        return {"success": True, "service": config}

    def delete_service(self, service_id: str) -> dict:
        if service_id in self.services:
            asyncio.create_task(self.stop_service(service_id))
            del self.services[service_id]
            self.save_services()
            return {"success": True, "message": "服务已删除"}
        return {"success": False, "message": "服务未找到"}

services_manager = ServicesManager()
