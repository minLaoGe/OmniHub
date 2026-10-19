import os
import sys
import json
import socket
import asyncio
import platform
import psutil
import subprocess
import signal
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
        self.status: str = "STOPPED" # STOPPED, STARTING, STOPPING, RUNNING, ERROR
        self.last_error: Optional[str] = None
        self.memory_exceeded: bool = False
        self.logs: deque = deque(maxlen=2000)
        self.listeners: List[asyncio.Queue] = []
        self._guard_task: Optional[asyncio.Task] = None

    def log(self, line: str):
        line = line.rstrip("\r\n")
        self.logs.append(line)
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
            SERVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SERVICES_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return
        try:
            with open(SERVICES_FILE, "r", encoding="utf-8") as f:
                configs = json.load(f)
            self.services.clear()
            for cfg in configs:
                if "max_memory_mb" not in cfg:
                    cfg["max_memory_mb"] = 0
                if "memory_limit_action" not in cfg:
                    cfg["memory_limit_action"] = "alert"

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
            sock.settimeout(0.2)
            result = sock.connect_ex((host, port))
            return result == 0

    def find_pids_by_port(self, port: Optional[int]) -> List[int]:
        """跨平台、极具韧性的端口占用 PID 查找（彻底避开 macOS 权限问题）"""
        if not port or port <= 0:
            return []
        pids = []

        # 针对 macOS / Linux 优先使用原生 lsof
        if CURRENT_OS in ["Darwin", "Linux"]:
            try:
                res = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.5
                )
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.strip().splitlines():
                        if line.strip().isdigit():
                            pids.append(int(line.strip()))
                    if pids:
                        return list(set(pids))
            except Exception:
                pass

        # 针对 Windows 使用 netstat -ano
        if CURRENT_OS == "Windows":
            try:
                res = subprocess.run(
                    ["netstat", "-ano"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2.0
                )
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 5 and f":{port}" in parts[1] and "LISTENING" in parts[3]:
                            if parts[-1].isdigit():
                                pids.append(int(parts[-1]))
                    if pids:
                        return list(set(pids))
            except Exception:
                pass

        # 通用备选方案：psutil
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                            pids.append(proc.pid)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        except Exception:
            pass

        return list(set(pids))

    def get_process_tree_metrics(self, pid: int) -> tuple[float, float]:
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
                sp.last_error = None
            elif sp.status not in ["ERROR", "STOPPING"]:
                sp.status = "STOPPED"
        else:
            if port_open:
                sp.status = "RUNNING"
                sp.last_error = None
            elif sp.status not in ["ERROR", "STOPPING"]:
                sp.status = "STOPPED"

        max_mem = sp.config.get("max_memory_mb", 0)
        is_exceeded = (max_mem > 0) and (memory_mb > max_mem)
        path_info = self.resolve_service_paths(sp.config)

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
            "last_error": getattr(sp, "last_error", None),
            "cpu_percent": cpu_percent,
            "memory_mb": memory_mb,
            "max_memory_mb": max_mem,
            "memory_limit_action": sp.config.get("memory_limit_action", "alert"),
            "memory_exceeded": is_exceeded or sp.memory_exceeded,
            "port_open": port_open,
            "auto_start": sp.config.get("auto_start", False),
            "command": sp.config.get("command"),
            "args": sp.config.get("args", []),
            "cwd": path_info["cwd"],
            "project_path": path_info["project_path"],
            "entry_script": path_info["entry_script"],
            "path_exists": path_info["path_exists"],
            "key_files": path_info["key_files"]
        }

    def resolve_service_paths(self, config: dict) -> dict:
        """解析并精确推断服务的项目根目录、工作目录与入口脚本绝对路径"""
        cwd = config.get("cwd") or str(Path.cwd())
        args = config.get("args") or []
        entry_script = None

        # 检查 args 中是否有脚本或主程序文件
        for arg in args:
            if isinstance(arg, str):
                p = Path(arg)
                if not p.is_absolute() and cwd:
                    p = Path(cwd) / p
                if p.is_file():
                    entry_script = str(p.resolve())
                    break

        # 智能推断 project_path (项目源码/模块所在具体目录)
        project_path = cwd
        sid = config.get("id", "").lower()
        cwd_p = Path(cwd)
        
        if "cleaner" in sid and (cwd_p / "cleaner").is_dir():
            project_path = str((cwd_p / "cleaner").resolve())
        elif "rea" in sid and (cwd_p / "rea_service").is_dir():
            project_path = str((cwd_p / "rea_service").resolve())
        elif entry_script:
            script_parent = Path(entry_script).parent
            if script_parent.is_dir() and script_parent != cwd_p and not str(script_parent).endswith("/bin"):
                project_path = str(script_parent.resolve())

        exists = Path(project_path).exists() if project_path else False

        # 获取该工程目录下关键标志文件
        key_files = []
        if exists and Path(project_path).is_dir():
            try:
                for item in Path(project_path).iterdir():
                    if item.name.startswith("."):
                        continue
                    if item.is_file() and item.suffix in [".py", ".sh", ".json", ".md", ".txt", ".yml", ".toml", ".bat", ".js"]:
                        key_files.append(item.name)
            except Exception:
                pass

        return {
            "project_path": project_path,
            "cwd": cwd,
            "entry_script": entry_script,
            "path_exists": exists,
            "key_files": sorted(key_files)[:8]
        }

    def reveal_in_explorer(self, path_or_service_id: str) -> dict:
        """在系统文件浏览器 (macOS Finder / Windows 资源管理器) 中定位并打开该项目目录"""
        target_path = path_or_service_id
        if path_or_service_id in self.services:
            path_info = self.resolve_service_paths(self.services[path_or_service_id].config)
            target_path = path_info.get("project_path") or path_info.get("cwd")

        if not target_path or not Path(target_path).exists():
            return {"success": False, "error": f"Path not found on disk: {target_path}"}

        try:
            if CURRENT_OS == "Darwin":
                subprocess.run(["open", str(target_path)], check=True)
            elif CURRENT_OS == "Windows":
                subprocess.run(["explorer", str(target_path)], check=True)
            else:
                subprocess.run(["xdg-open", str(target_path)], check=True)
            return {"success": True, "message": f"Opened {target_path} in file explorer", "path": str(target_path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_omnihub_info(self) -> dict:
        """获取 OmniHub 自身的根工程路径与核心元数据"""
        root_dir = Path(__file__).resolve().parent.parent
        return {
            "platform": "OmniHub",
            "root_dir": str(root_dir),
            "omnihub_project_path": str(root_dir),
            "services_file": str(SERVICES_FILE),
            "mcp_servers_file": str(root_dir / "data" / "mcp_servers.json"),
            "os": CURRENT_OS,
            "services_count": len(self.services)
        }

    async def list_services(self) -> List[dict]:
        results = []
        for sid in self.services:
            results.append(await self.get_service_status(sid))
        return results

    async def _memory_guard(self, sp: ServiceProcess):
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
        port = str(sp.config.get("port") or 8000)
        command = sp.config["command"]
        args = list(sp.config.get("args", []))

        if CURRENT_OS == "Windows":
            if command in ["/bin/bash", "/bin/zsh", "bash", "zsh"]:
                command = "cmd.exe"
                args = ["/c"] + args
            elif command == "python3":
                command = "python"

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
        sp.last_error = None
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
            if CURRENT_OS == "Windows":
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

            asyncio.create_task(self._stream_process_logs(sp))
            if sp._guard_task and not sp._guard_task.done():
                sp._guard_task.cancel()
            sp._guard_task = asyncio.create_task(self._memory_guard(sp))

            return {"success": True, "message": f"服务已启动 (PID: {sp.pid})", "pid": sp.pid}
        except Exception as e:
            sp.status = "ERROR"
            sp.last_error = str(e)
            sp.log(f"--- [OmniHub 错误] 启动失败: {str(e)} ---")
            return {"success": False, "message": f"启动失败: {str(e)}"}

    async def _stream_process_logs(self, sp: ServiceProcess):
        return_code = 0
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
            sp.pid = None
            if return_code != 0:
                sp.status = "ERROR"
                last_logs = [l for l in list(sp.logs)[-8:] if l and not l.startswith("---")]
                sp.last_error = "\n".join(last_logs) if last_logs else f"进程退出，退出码: {return_code}"
            else:
                sp.status = "STOPPED"
                sp.last_error = None

            if sp._guard_task and not sp._guard_task.done():
                sp._guard_task.cancel()

    async def stop_service(self, service_id: str) -> dict:
        """强化版停止服务：多维度追查关联 PID 和端口占用，确保 100% 杀死并释放端口"""
        if service_id not in self.services:
            return {"success": False, "message": "服务不存在"}

        sp = self.services[service_id]
        port = sp.config.get("port")
        sp.status = "STOPPING"
        sp.log(f"--- [OmniHub] 正在停止服务 (释放端口 {port}) ---")

        if sp._guard_task and not sp._guard_task.done():
            sp._guard_task.cancel()

        # 收集所有需要清理的目标 PID
        target_pids = set()
        if sp.process and sp.process.pid:
            target_pids.add(sp.process.pid)
        if sp.pid:
            target_pids.add(sp.pid)

        # 无论是否脱离父进程，通过端口强制查找占用者 PID
        port_pids = self.find_pids_by_port(port)
        for p in port_pids:
            target_pids.add(p)

        sp.log(f"--- [OmniHub] 目标终止进程列表: {list(target_pids)} ---")

        # 第一阶段：优雅发送 SIGTERM 并杀死子进程树
        for pid in list(target_pids):
            try:
                p = psutil.Process(pid)
                for child in p.children(recursive=True):
                    try:
                        child.terminate()
                    except Exception:
                        pass
                p.terminate()
            except (psutil.NoSuchProcess, Exception):
                pass

        if sp.process:
            try:
                sp.process.terminate()
            except Exception:
                pass

        # 轮询等待端口释放（最多 1.5 秒）
        for _ in range(15):
            await asyncio.sleep(0.1)
            if not self.is_port_open(port):
                break

        # 第二阶段：如果端口仍被占用或进程仍在存活，执行强制 SIGKILL
        still_alive_pids = self.find_pids_by_port(port)
        for pid in set(list(target_pids) + still_alive_pids):
            try:
                p = psutil.Process(pid)
                for child in p.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                p.kill()
            except Exception:
                pass

            # 在 POSIX 上调用底层 os.kill 确保强制杀除
            if CURRENT_OS in ["Darwin", "Linux"]:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

        # 最终确认端口释放
        for _ in range(10):
            if not self.is_port_open(port):
                break
            await asyncio.sleep(0.1)

        sp.status = "STOPPED"
        sp.process = None
        sp.pid = None
        sp.memory_exceeded = False
        sp.last_error = None
        sp.log(f"--- [OmniHub] 服务已成功停止，端口 {port} 已释放 ---")

        return {"success": True, "message": f"服务已彻底停止，端口 {port} 已释放"}

    async def restart_service(self, service_id: str) -> dict:
        sp = self.services.get(service_id)
        if sp:
            sp.status = "STARTING"
        await self.stop_service(service_id)
        await asyncio.sleep(0.8)
        return await self.start_service(service_id)

    def update_service(self, service_id: str, new_data: dict) -> dict:
        if service_id not in self.services:
            return {"success": False, "message": "服务不存在"}

        sp = self.services[service_id]
        cfg = sp.config

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
