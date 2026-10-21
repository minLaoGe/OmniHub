import os
import sys
import json
import time
import asyncio
import platform
import plistlib
from xml.parsers.expat import ExpatError
import subprocess
import psutil
from send2trash import send2trash
from pathlib import Path
from typing import List, Dict, Any, Optional

from .config import APP_RULES_FILE
from .disk_usage import disk_usage_cache

CURRENT_OS = platform.system()

# Windows API 动态加载（用于工作集内存快速压缩回收）
kernel32 = None
psapi = None
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

if CURRENT_OS == "Windows":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
    except Exception as e:
        print(f"[AppsManager] Failed to load Windows API: {e}", file=sys.stderr)

class AppsManager:
    def __init__(self):
        self.rules: Dict[str, Dict[str, Any]] = {}
        self.installed_cache: List[Dict[str, Any]] = []
        self.last_scan_time: float = 0.0
        self.guardian_logs: List[Dict[str, Any]] = []
        self.load_rules()

    def load_rules(self):
        """加载已配置的应用内存限制规则"""
        if not APP_RULES_FILE.exists():
            APP_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            # 默认内置对高耗内存软件（如抖音）的规则推荐
            default_rules = {
                "抖音": {
                    "process_names": ["douyin.exe", "Douyin.exe"],
                    "max_memory_mb": 800,
                    "action": "trim", # trim (工作集压缩释放), kill (强制结束), alert (仅记录)
                    "enabled": True
                }
            }
            try:
                with open(APP_RULES_FILE, "w", encoding="utf-8") as f:
                    json.dump(default_rules, f, ensure_ascii=False, indent=2)
                self.rules = default_rules
            except Exception:
                self.rules = {}
            return

        try:
            with open(APP_RULES_FILE, "r", encoding="utf-8") as f:
                self.rules = json.load(f)
        except Exception as e:
            print(f"[AppsManager] Error loading rules: {e}", file=sys.stderr)
            self.rules = {}

    def save_rules(self):
        """持久化保存规则配置"""
        try:
            with open(APP_RULES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AppsManager] Error saving rules: {e}", file=sys.stderr)

    def scan_installed_apps(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """扫描本地所有安装的应用程序（支持 Windows 注册表与快捷方式）"""
        now = time.time()
        # 缓存 45 秒，避免前端高频轮询时频繁读取注册表
        if not force_refresh and self.installed_cache and (now - self.last_scan_time < 45):
            return self.installed_cache

        apps = []
        seen_names = set()

        if CURRENT_OS == "Windows":
            import winreg

            # 1. 扫描注册表卸载项 (64位、32位与当前用户)
            reg_locations = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
            ]

            for root, subkey in reg_locations:
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                sub_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, sub_name) as app_key:
                                    def get_val(v_name):
                                        try:
                                            v, _ = winreg.QueryValueEx(app_key, v_name)
                                            return str(v).strip()
                                        except Exception:
                                            return ""

                                    name = get_val("DisplayName")

                                    # 处理名称：若为空、问号或乱码，尝试以 sub_name 挽救

                                    if not name or name in ['?', ''] or '\ufffd' in name or len(name.strip()) <= 1:

                                        if sub_name.lower() == 'douyin':

                                            name = '抖音 (Douyin)'

                                        elif sub_name and not sub_name.startswith('{'):

                                            name = sub_name

                                        else:

                                            continue



                                    # 过滤掉系统更新补丁和空名称

                                    if not name or name in seen_names or "KB" in name and name.startswith("KB"):

                                        continue

                                    install_loc = get_val("InstallLocation")
                                    icon = get_val("DisplayIcon")
                                    version = get_val("DisplayVersion")
                                    publisher = get_val("Publisher")
                                    uninstall = get_val("UninstallString")

                                    # 尝试提取主 exe 路径

                                    exe_path = ""

                                    if icon and icon.lower().endswith(".exe") and Path(icon.split(",")[0].strip('"')).exists():

                                        exe_path = icon.split(",")[0].strip('"')

                                    elif install_loc and Path(install_loc).is_dir():

                                        try:

                                            exes = list(Path(install_loc).glob("*.exe"))

                                            if exes:

                                                exe_path = str(exes[0])

                                        except Exception:

                                            pass



                                    if not install_loc and exe_path:

                                        install_loc = str(Path(exe_path).parent)

                                    if not install_loc and uninstall and ".exe" in uninstall.lower():
                                        try:
                                            u_clean = uninstall.replace('"', "").replace("'", "").strip()
                                            idx = u_clean.lower().find(".exe")
                                            if idx != -1:
                                                candidate = u_clean[:idx + 4]
                                                if Path(candidate).exists():
                                                    install_loc = str(Path(candidate).parent)
                                        except Exception:
                                            pass
                                            if m and Path(m.group(1)).exists():

                                                install_loc = str(Path(m.group(1)).parent)

                                        except Exception:

                                            pass

                                    seen_names.add(name)
                                    apps.append({
                                        "name": name,
                                        "version": version,
                                        "publisher": publisher,
                                        "install_location": install_loc,
                                        "launch_path": exe_path,
                                        "icon": icon.split(",")[0].strip('"') if icon else "",
                                        "uninstall_string": uninstall,
                                        "source": "Registry"
                                    })
                            except Exception:
                                pass
                except Exception:
                    pass

            # 2. 扫描开始菜单快捷方式（捕捉便携式软件、绿色软件等，并智能解析真实 exe 目标）

            start_dirs = [

                Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",

                Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

            ]

            wscript_shell = None

            if CURRENT_OS == "Windows":

                try:

                    import win32com.client

                    wscript_shell = win32com.client.Dispatch("WScript.Shell")

                except Exception:

                    wscript_shell = None



            for sdir in start_dirs:

                if sdir.exists():

                    for lnk in sdir.rglob("*.lnk"):

                        stem = lnk.stem

                        if stem not in seen_names and not stem.lower().startswith("uninstall") and "卸载" not in stem:

                            seen_names.add(stem)

                            target_exe = ""

                            target_dir = ""

                            if wscript_shell:

                                try:

                                    sc = wscript_shell.CreateShortcut(str(lnk))

                                    sc_path = sc.TargetPath

                                    if sc_path and Path(sc_path).exists():

                                        target_exe = sc_path

                                        target_dir = str(Path(sc_path).parent)

                                except Exception:

                                    pass



                            launch_path = target_exe if target_exe else str(lnk)

                            install_loc = target_dir if target_dir else str(lnk.parent)



                            apps.append({

                                "name": stem,

                                "version": "",

                                "publisher": "",

                                "install_location": install_loc,

                                "launch_path": launch_path,

                                "icon": target_exe if (target_exe and target_exe.lower().endswith(".exe")) else "",

                                "source": "StartMenu"

                            })

        elif CURRENT_OS == "Darwin":
            roots = [Path('/Applications'), Path.home() / 'Applications',
                     Path('/System/Applications'), Path('/System/Library/CoreServices/Applications')]
            seen_bundles = set()
            for root in roots:
                for folder, dirs, _ in os.walk(root, followlinks=False):
                    for directory in list(dirs):
                        if not directory.lower().endswith('.app'):
                            continue
                        dirs.remove(directory)
                        bundle = (Path(folder) / directory).resolve()
                        if bundle in seen_bundles:
                            continue
                        seen_bundles.add(bundle)
                        try:
                            with (bundle / 'Contents/Info.plist').open('rb') as stream:
                                info = plistlib.load(stream)
                        except (OSError, ValueError, plistlib.InvalidFileException, ExpatError):
                            continue
                        executable = info.get('CFBundleExecutable', '')
                        apps.append({
                            'name': info.get('CFBundleDisplayName') or info.get('CFBundleName') or bundle.stem,
                            'version': info.get('CFBundleShortVersionString') or info.get('CFBundleVersion', ''),
                            'publisher': '',
                            'install_location': str(bundle),
                            'launch_path': str(bundle),
                            'executable_name': executable,
                            'icon': '',
                            'source': 'MacBundle',
                        })

        self.installed_cache = apps
        self.last_scan_time = now
        return apps

    def get_running_process_map(self) -> Dict[str, Dict[str, Any]]:
        """获取所有运行中的进程统计（按小写名称聚合）"""
        running = {}
        for p in psutil.process_iter(['pid', 'name', 'exe', 'memory_info', 'cpu_percent']):
            try:
                info = p.info
                pname = info.get('name')
                if not pname:
                    continue
                lower_pname = pname.lower()
                # 过滤无意义的系统基础句柄
                if lower_pname in ['system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe', 'lsass.exe']:
                    continue

                mem_mb = (info['memory_info'].rss / (1024 * 1024)) if info.get('memory_info') else 0.0
                cpu = info.get('cpu_percent') or 0.0

                if lower_pname not in running:
                    running[lower_pname] = {
                        "name": pname,
                        "pids": [],
                        "memory_mb": 0.0,
                        "cpu_percent": 0.0,
                        "exe": info.get('exe') or ""
                    }
                running[lower_pname]["pids"].append(info['pid'])
                running[lower_pname]["memory_mb"] += mem_mb
                running[lower_pname]["cpu_percent"] += cpu
            except Exception:
                pass
        return running

    def list_apps(self, search: str = "", only_running: bool = False, only_limited: bool = False, refresh: bool = False) -> List[Dict[str, Any]]:
        """列出本机应用，并关联当前实时运行状态与内存限制规则"""
        installed = self.scan_installed_apps(force_refresh=refresh)
        running_map = self.get_running_process_map()
        mac_bundles = {}
        if CURRENT_OS == "Darwin":
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'memory_info', 'cpu_percent']):
                try:
                    info = proc.info
                    executable = info.get('exe') or ''
                    if '.app/' not in executable:
                        continue
                    bundle = executable.split('.app/', 1)[0] + '.app'
                    mac_bundles.setdefault(bundle, []).append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        matched_lower_procs = set()
        result_list = []

        # 1. 关联安装清单中的应用
        for app in installed:
            name = app["name"]
            launch_path = app.get("launch_path", "")
            exe_name = (app.get("executable_name") or (Path(launch_path).name if launch_path else "")).lower()

            # 匹配运行中状态
            matched_procs = []
            matched_pids = []
            mem_sum = 0.0
            cpu_sum = 0.0

            # 匹配规则：通过 exe_name 或名称匹配
            if CURRENT_OS == "Darwin":
                for info in mac_bundles.get(launch_path, []):
                    matched_procs.append(info['name'])
                    matched_pids.append(info['pid'])
                    mem_sum += info['memory_info'].rss / (1024 * 1024) if info.get('memory_info') else 0
                    cpu_sum += info.get('cpu_percent') or 0
                    matched_lower_procs.add(info['name'].lower())
            elif exe_name and exe_name in running_map:
                matched_procs.append(running_map[exe_name]["name"])
                matched_pids.extend(running_map[exe_name]["pids"])
                mem_sum += running_map[exe_name]["memory_mb"]
                cpu_sum += running_map[exe_name]["cpu_percent"]
                matched_lower_procs.add(exe_name)
            elif CURRENT_OS != "Darwin":
                # 模糊名称匹配
                name_clean = name.lower().replace(" ", "").replace(".exe", "")
                for r_low, r_val in running_map.items():
                    r_clean = r_low.replace(".exe", "").replace(" ", "")
                    if name_clean in r_clean or r_clean in name_clean:
                        matched_procs.append(r_val["name"])
                        matched_pids.extend(r_val["pids"])
                        mem_sum += r_val["memory_mb"]
                        cpu_sum += r_val["cpu_percent"]
                        matched_lower_procs.add(r_low)

            is_running = len(matched_pids) > 0

            # 获取匹配规则
            rule = self.rules.get(name)
            if not rule and exe_name:
                rule = self.rules.get(exe_name)

            max_memory_mb = rule.get("max_memory_mb", 0) if rule else 0
            memory_action = rule.get("action", "trim") if rule else "trim"
            rule_enabled = rule.get("enabled", True) if rule else False
            is_over_limit = bool(is_running and rule_enabled and max_memory_mb > 0 and mem_sum > max_memory_mb)

            # 若已有运行进程，但原本 launch_path 为空，则自动补充真实进程路径

            if not launch_path and matched_pids:

                for r_low in matched_lower_procs:

                    if r_low in running_map and running_map[r_low].get("exe"):

                        launch_path = running_map[r_low]["exe"]

                        break



            install_dir = app.get("install_location") or (str(Path(launch_path).parent) if launch_path and Path(launch_path).exists() else "")
            item = {
                "id": name,
                "name": name,
                "version": app.get("version", ""),
                "publisher": app.get("publisher", ""),
                "install_location": install_dir,
                "launch_path": launch_path,
                "uninstall_string": app.get("uninstall_string", ""),
                "is_running": is_running,
                "process_names": list(set(matched_procs)),
                "pids": matched_pids,
                "memory_mb": round(mem_sum, 1),
                "cpu_percent": round(cpu_sum, 1),
                "max_memory_mb": max_memory_mb,
                "memory_action": memory_action,
                "rule_enabled": rule_enabled,
                "is_over_limit": is_over_limit,
                "source": app.get("source", "Registry")
            }
            result_list.append(item)

        # 2. 将正在运行但未在注册表中的知名桌面进程（如自解压软件、后台客户端）也补充进来
        for r_low, r_val in running_map.items():
            if r_low not in matched_lower_procs and r_val["memory_mb"] > 25:
                # 排除完全后台的系统服务
                if r_low in ['svchost.exe', 'conhost.exe', 'sihost.exe', 'dwm.exe', 'explorer.exe', 'searchapp.exe', 'taskhostw.exe']:
                    continue
                pname = r_val["name"]
                rule = self.rules.get(pname)
                max_memory_mb = rule.get("max_memory_mb", 0) if rule else 0
                memory_action = rule.get("action", "trim") if rule else "trim"
                rule_enabled = rule.get("enabled", True) if rule else False
                is_over_limit = bool(rule_enabled and max_memory_mb > 0 and r_val["memory_mb"] > max_memory_mb)

                proc_exe = r_val.get("exe", "")
                proc_dir = str(Path(proc_exe).parent) if proc_exe and Path(proc_exe).exists() else ""
                result_list.append({
                    "id": pname,
                    "name": pname.replace(".exe", "").capitalize(),
                    "version": "",
                    "publisher": "本地运行程序",
                    "install_location": proc_dir,
                    "launch_path": proc_exe,
                    "uninstall_string": "",
                    "is_running": True,
                    "process_names": [pname],
                    "pids": r_val["pids"],
                    "memory_mb": round(r_val["memory_mb"], 1),
                    "cpu_percent": round(r_val["cpu_percent"], 1),
                    "max_memory_mb": max_memory_mb,
                    "memory_action": memory_action,
                    "rule_enabled": rule_enabled,
                    "is_over_limit": is_over_limit,
                    "source": "Process"
                })

        # 排序：优先排【正在运行】且【内存占用大】的应用
        result_list.sort(key=lambda x: (not x["is_running"], -x["memory_mb"], x["name"].lower()))

        # 过滤
        filtered = []
        s_lower = search.strip().lower()
        for it in result_list:
            if only_running and not it["is_running"]:
                continue
            if only_limited and it["max_memory_mb"] <= 0:
                continue
            if s_lower:
                if s_lower not in it["name"].lower() and s_lower not in it.get("publisher", "").lower() and not any(s_lower in p.lower() for p in it["process_names"]):
                    continue
            it.update(disk_usage_cache.describe(it))
            filtered.append(it)

        return filtered

    def launch_app(self, launch_path: str, app_name: str) -> Dict[str, Any]:
        """快速启动应用程序"""
        try:
            if CURRENT_OS == "Darwin":
                if not launch_path or not Path(launch_path).is_dir() or Path(launch_path).suffix.lower() != '.app':
                    return {"success": False, "message": "未找到可启动的 Mac 应用程序包"}
                subprocess.run(['/usr/bin/open', '-a', launch_path], check=True)
                return {"success": True, "message": f"已成功发送启动指令: {app_name}"}
            if launch_path and Path(launch_path).exists():
                if CURRENT_OS == "Windows":
                    os.startfile(launch_path)
                else:
                    subprocess.Popen([launch_path])
                return {"success": True, "message": f"已成功发送启动指令: {app_name}"}
            else:
                # 尝试根据名字在命令行中启动
                clean_name = app_name if app_name.endswith(".exe") else f"{app_name}.exe"
                subprocess.Popen(["start", clean_name], shell=True)
                return {"success": True, "message": f"已尝试通过系统命令拉起: {app_name}"}
        except Exception as e:
            return {"success": False, "message": f"启动失败: {str(e)}"}

    def kill_app(self, process_names: List[str], pids: List[int]) -> Dict[str, Any]:
        """立即杀死/强制结束该应用的所有相关进程树"""
        killed_count = 0
        try:
            if CURRENT_OS == "Windows":
                # 优先根据进程名直接 taskkill /F /T
                for pname in process_names:
                    res = subprocess.run(["taskkill", "/F", "/T", "/IM", pname], capture_output=True)
                    if res.returncode == 0:
                        killed_count += 1
                # 针对剩余 PID 双重保险
                for pid in pids:
                    try:
                        p = psutil.Process(pid)
                        p.kill()
                        killed_count += 1
                    except Exception:
                        pass
            else:
                for pid in pids:
                    try:
                        p = psutil.Process(pid)
                        p.kill()
                        killed_count += 1
                    except Exception:
                        pass
            return {"success": True, "message": f"已成功强制终止目标进程 (操作次数: {killed_count})"}
        except Exception as e:
            return {"success": False, "message": f"杀死进程失败: {str(e)}"}

    def open_app_directory(

        self,

        install_location: str = "",

        launch_path: str = "",

        process_names: List[str] = None,

        pids: List[int] = None,

        app_name: str = ""

    ) -> Dict[str, Any]:

        """一键打开安装所在文件目录并在资源管理器中定位高亮（多级回退机制保障 100% 弹窗）"""

        try:

            target_file = None

            target_folder = None



            # 1. 如果是 .lnk 快捷方式，使用 WScript.Shell 解析为真实的目标程序路径

            if launch_path and launch_path.lower().endswith(".lnk") and Path(launch_path).exists():

                try:

                    import win32com.client

                    ws = win32com.client.Dispatch("WScript.Shell")

                    sc_target = ws.CreateShortcut(launch_path).TargetPath

                    if sc_target and Path(sc_target).exists():

                        launch_path = sc_target

                except Exception:

                    pass



            # 2. 如果提供了 launch_path 且存在

            if launch_path and Path(launch_path).exists():

                p = Path(launch_path).resolve()

                if p.is_file():

                    target_file = str(p)

                    target_folder = str(p.parent)

                else:

                    target_folder = str(p)



            # 3. 如果 launch_path 仍未解析出有效文件，尝试根据正在运行的进程提取绝对路径

            if not target_file:

                # 优先根据已知 PID 获取 exe

                if pids:

                    for pid in pids:

                        try:

                            pexe = psutil.Process(pid).exe()

                            if pexe and Path(pexe).exists():

                                target_file = str(Path(pexe).resolve())

                                target_folder = str(Path(pexe).parent.resolve())

                                break

                        except Exception:

                            pass

                # 其次根据进程名从全局进程池查找

                if not target_file and process_names:

                    for p in psutil.process_iter(['name', 'exe']):

                        try:

                            if p.info['name'] in process_names and p.info.get('exe'):

                                pexe = p.info['exe']

                                if pexe and Path(pexe).exists():

                                    target_file = str(Path(pexe).resolve())

                                    target_folder = str(Path(pexe).parent.resolve())

                                    break

                        except Exception:

                            pass



            # 4. 如果没有具体执行文件，但有有效安装目录

            if not target_folder and install_location and Path(install_location).exists():

                ip = Path(install_location).resolve()

                if ip.is_file():

                    target_file = str(ip)

                    target_folder = str(ip.parent)

                else:

                    target_folder = str(ip)



            # 5. 若仍未找到任何本地有效路径

            if not target_folder and not target_file:

                return {

                    "success": False,

                    "message": f"未找到【{app_name or '目标应用'}】的本地安装路径或执行程序（可能为虚拟应用或系统组件）"

                }



            # 6. 执行唤起操作（多重双保险机制）

            if CURRENT_OS == "Windows":

                from .native_paths import open_windows_path
                open_windows_path(target_file or target_folder)
                return {
                    "success": True,
                    "message": f"已打开资源管理器：{target_folder}",
                    "target_file": target_file,
                    "target_folder": target_folder
                }

            elif CURRENT_OS == "Darwin":

                if target_file:

                    subprocess.Popen(["open", "-R", target_file])

                else:

                    subprocess.Popen(["open", target_folder])

                return {"success": True, "message": f"已在 Finder 中打开: {target_folder}"}

            else:

                subprocess.Popen(["xdg-open", target_folder or str(Path(target_file).parent)])

                return {"success": True, "message": f"已在文件管理器中打开: {target_folder}"}



        except Exception as e:

            return {"success": False, "message": f"打开目录异常: {str(e)}"}

    def preview_app_cleanup(self, launch_path: str) -> Dict[str, Any]:
        """列出可独立确认的应用关联目录，不处理共享目录或猜测项目路径。"""
        if CURRENT_OS != 'Darwin':
            return {'success': False, 'message': '关联文件扫描仅支持 macOS。'}
        bundle = Path(launch_path).expanduser().resolve()
        installed = self.scan_installed_apps(force_refresh=True)
        if bundle.is_relative_to(Path('/System')) or not any(
                a.get('source') == 'MacBundle' and a['launch_path'] == str(bundle) for a in installed):
            return {'success': False, 'message': '目标不是可卸载的已安装应用。'}
        try:
            with (bundle / 'Contents/Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
        except (OSError, ValueError, ExpatError, plistlib.InvalidFileException) as exc:
            return {'success': False, 'message': f'读取应用信息失败：{exc}'}
        home = Path.home()
        library = home / 'Library'
        identifier = info.get('CFBundleIdentifier', '')
        name = info.get('CFBundleName') or bundle.stem
        candidates = []
        if identifier and '/' not in identifier and identifier not in ('.', '..'):
            for folder, leaf in [('Caches', identifier), ('Application Support', identifier),
                    ('Preferences', identifier + '.plist'), ('Logs', identifier),
                    ('Saved Application State', identifier + '.savedState'),
                    ('HTTPStorages', identifier), ('WebKit', identifier), ('Containers', identifier)]:
                candidates.append((library / folder / leaf, '缓存' if folder == 'Caches' else '设置与用户数据'))
        # 名称目录只有在已安装应用中不存在同名时，才归属给当前应用。
        if name and '/' not in name and name not in ('.', '..') and sum(a['name'] == name for a in installed) <= 1:
            for folder in ['Application Support', 'Caches', 'Logs']:
                candidates.append((library / folder / name, '缓存' if folder == 'Caches' else '设置与用户数据'))
        if identifier == 'app.omlx':
            candidates.append((home / '.omlx', '模型、设置与用户数据'))
        items, seen = [], set()
        for path, category in candidates:
            if not path.exists() or path.is_symlink() or path.resolve() != path.absolute():
                continue
            if str(path) in seen:
                continue
            seen.add(str(path))
            size, complete = 0, True
            try:
                if path.is_file():
                    size = path.stat().st_size
                else:
                    def onerror(error):
                        nonlocal complete
                        complete = False
                    for root, dirs, files in os.walk(path, followlinks=False, onerror=onerror):
                        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                        for filename in files:
                            entry = Path(root) / filename
                            if entry.is_symlink():
                                continue
                            try:
                                size += entry.stat().st_size
                            except OSError:
                                complete = False
            except OSError:
                complete = False
            items.append({'path': str(path), 'category': category, 'size_bytes': size,
                          'size_complete': complete})
        return {'success': True, 'items': items, 'total_bytes': sum(i['size_bytes'] for i in items),
                'note': '仅列出可识别的独立关联目录；不自动包含共享目录、自选项目位置或其他用户的数据。大小为逻辑大小，移入废纸篓不会立即释放磁盘空间。'}

    def uninstall_app(self, app_name: str, uninstall_string: str, launch_path: str = "", cleanup_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """Mac 应用移入废纸篓；Windows 启动卸载向导。"""
        try:
            if CURRENT_OS == "Darwin":
                if not launch_path:
                    return {"success": False, "message": "缺少应用安装路径，请刷新应用列表后重试。"}
                bundle = Path(launch_path).expanduser().resolve()
                if bundle.is_relative_to(Path('/System')):
                    return {"success": False, "message": "macOS 系统应用不能在此卸载。"}
                installed = self.scan_installed_apps(force_refresh=True)
                if not any(a.get('source') == 'MacBundle' and a['launch_path'] == str(bundle) for a in installed):
                    return {"success": False, "message": "未找到已安装的 Mac 应用，请刷新列表后重试。"}
                if bundle.suffix.lower() != '.app' or not (bundle / 'Contents/Info.plist').is_file():
                    return {"success": False, "message": "目标不是有效的 Mac 应用程序包。"}
                for proc in psutil.process_iter(['exe']):
                    try:
                        executable = proc.info.get('exe') or ''
                        if executable.startswith(str(bundle) + '/'):
                            return {"success": False, "message": f"【{app_name}】仍在运行，请先退出应用后再卸载。"}
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                selected = list(dict.fromkeys(cleanup_paths or []))
                if selected:
                    preview = self.preview_app_cleanup(str(bundle))
                    if not preview.get('success'):
                        return preview
                    allowed = {item['path'] for item in preview['items']}
                    if any(path not in allowed for path in selected):
                        return {'success': False, 'message': '关联文件列表已变化或路径无效，请重新扫描后确认。'}
                send2trash(str(bundle))
                if bundle.exists():
                    return {"success": False, "message": "应用尚未移入废纸篓，请检查系统权限后重试。"}
                self.installed_cache = []
                self.last_scan_time = 0
                removed, failed = [], []
                # 父目录先移动，避免嵌套候选被重复操作。
                for path in sorted(selected, key=len):
                    if any(Path(path).is_relative_to(Path(parent)) for parent in removed):
                        continue
                    try:
                        send2trash(path)
                        if Path(path).exists():
                            raise OSError('移动未生效')
                        removed.append(path)
                    except OSError as exc:
                        failed.append({'path': path, 'error': str(exc)})
                message = f'【{app_name}】已移入废纸篓。'
                message += f'已移除 {len(removed)} 项选中的关联数据。' if selected else '应用数据和缓存已保留。'
                if failed:
                    message += f'有 {len(failed)} 项未能移除，请查看失败清单。'
                return {'success': not failed, 'app_removed': True, 'message': message,
                        'removed_paths': removed, 'failed_paths': failed}
            if CURRENT_OS != "Windows":
                return {"success": False, "message": "此平台暂不支持应用卸载。"}
            if uninstall_string:
                clean_cmd = uninstall_string.strip()
                # Windows 下直接通过 shell 拉起卸载程序
                subprocess.Popen(clean_cmd, shell=True)
                return {"success": True, "message": f"已拉起【{app_name}】的官方卸载向导，请在弹出的系统窗口中确认卸载。"}
            else:
                # 若无注册表卸载串，尝试调用 winget 卸载
                clean_name = app_name.split()[0]
                subprocess.Popen(f'start cmd /k "winget uninstall \"{clean_name}\""', shell=True)
                return {"success": True, "message": f"已在命令行调起 Winget 卸载向导: {clean_name}"}
        except Exception as e:
            return {"success": False, "message": f"触发卸载失败: {str(e)}"}

    def trim_app_memory(self, pids: List[int], process_names: List[str]) -> Dict[str, Any]:
        """对目标应用的所有进程执行 Windows 工作集物理内存压缩释放"""
        if CURRENT_OS != "Windows" or not kernel32 or not psapi:
            return {"success": False, "message": "内存压缩特性仅支持 Windows 系统原生 API"}

        # 收集有效 PID
        target_pids = set(pids)
        if process_names:
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if p.info['name'] in process_names:
                        target_pids.add(p.info['pid'])
                except Exception:
                    pass

        before_mb = 0.0
        after_mb = 0.0
        success_count = 0

        # 计算释放前物理内存
        for pid in list(target_pids):
            try:
                before_mb += psutil.Process(pid).memory_info().rss / (1024 * 1024)
            except Exception:
                pass

        # 逐个调用 EmptyWorkingSet
        for pid in list(target_pids):
            try:
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                if handle:
                    res = psapi.EmptyWorkingSet(handle)
                    kernel32.CloseHandle(handle)
                    if res:
                        success_count += 1
            except Exception:
                pass

        # 计算释放后物理内存
        for pid in list(target_pids):
            try:
                after_mb += psutil.Process(pid).memory_info().rss / (1024 * 1024)
            except Exception:
                pass

        saved_mb = max(0.0, before_mb - after_mb)
        return {
            "success": True,
            "before_mb": round(before_mb, 1),
            "after_mb": round(after_mb, 1),
            "saved_mb": round(saved_mb, 1),
            "processes_trimmed": success_count,
            "message": f"内存压缩成功！释放前 {round(before_mb,1)} MB 降至 {round(after_mb,1)} MB，瞬间节省 {round(saved_mb,1)} MB 物理内存！"
        }

    def trim_all_running_apps(self) -> Dict[str, Any]:
        """一键优化：压缩当前系统所有高内存应用的物理工作集"""
        if CURRENT_OS != "Windows" or not kernel32 or not psapi:
            return {"success": False, "message": "仅支持 Windows 系统"}

        total_saved = 0.0
        trimmed_count = 0

        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = p.info
                pname = info.get('name', '').lower()
                if pname in ['system', 'registry', 'smss.exe', 'csrss.exe']:
                    continue
                mem_rss = info['memory_info'].rss / (1024 * 1024)
                # 仅对内存大于 30MB 的活跃进程进行优化释放
                if mem_rss > 30.0:
                    pid = info['pid']
                    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
                    if handle:
                        if psapi.EmptyWorkingSet(handle):
                            trimmed_count += 1
                        kernel32.CloseHandle(handle)
            except Exception:
                pass

        return {
            "success": True,
            "trimmed_processes": trimmed_count,
            "message": f"一键深度内存整理完成！已成功对 {trimmed_count} 个应用进程执行工作集压缩。"
        }

    def set_app_rule(self, app_id: str, max_memory_mb: int, action: str = "trim", process_names: Optional[List[str]] = None, enabled: bool = True) -> Dict[str, Any]:
        """设定/修改某个应用的内存限制配额"""
        if not process_names:
            # 自动探测
            process_names = [f"{app_id}.exe", f"{app_id.lower()}.exe"]

        self.rules[app_id] = {
            "process_names": process_names,
            "max_memory_mb": max_memory_mb,
            "action": action, # trim, kill, alert
            "enabled": enabled,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save_rules()
        return {"success": True, "rule": self.rules[app_id], "message": f"已成功为 {app_id} 设定内存限制配额: {max_memory_mb} MB (策略: {action})"}

    def delete_app_rule(self, app_id: str) -> Dict[str, Any]:
        """删除某个应用的内存限制规则"""
        if app_id in self.rules:
            del self.rules[app_id]
            self.save_rules()
        return {"success": True, "message": f"已移除 {app_id} 的内存配额限制"}

    def get_rules(self) -> Dict[str, Any]:
        return self.rules

    def get_guardian_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.guardian_logs[-limit:]

    async def start_memory_guardian(self):
        """后台常驻守护任务：实时监控配置了内存限制的应用，超限自动处理"""
        try:
            print("[MemoryGuardian] Engine started.")
        except Exception:
            pass
        while True:
            try:
                await asyncio.sleep(4.0)
                if not self.rules:
                    continue

                running_map = self.get_running_process_map()
                for rule_key, rule in list(self.rules.items()):
                    if not rule.get("enabled", True):
                        continue
                    max_mb = rule.get("max_memory_mb", 0)
                    if max_mb <= 0:
                        continue
                    action = rule.get("action", "trim")
                    pnames = [p.lower() for p in rule.get("process_names", [])]
                    if not pnames:
                        pnames = [f"{rule_key.lower()}.exe"]

                    # 统计该应用占用总内存
                    matched_pids = []
                    current_mem = 0.0
                    for lower_pname, rdata in running_map.items():
                        if any(pn in lower_pname or lower_pname in pn for pn in pnames):
                            matched_pids.extend(rdata["pids"])
                            current_mem += rdata["memory_mb"]

                    # 判定是否超限
                    if current_mem > max_mb and matched_pids:
                        timestamp = time.strftime("%H:%M:%S")
                        if action == "trim":
                            trim_res = self.trim_app_memory(matched_pids, pnames)
                            log_msg = f"[{timestamp}] ⚡ 内存超限管控: {rule_key} 内存达到 {round(current_mem,1)} MB (上限: {max_mb} MB)，已自动触发工作集物理压缩，降至 {trim_res.get('after_mb')} MB！"
                            # log_msg recorded
                            self.guardian_logs.append({
                                "time": timestamp,
                                "type": "trim",
                                "app": rule_key,
                                "message": log_msg
                            })
                        elif action == "kill":
                            self.kill_app(pnames, matched_pids)
                            log_msg = f"[{timestamp}] 🛑 内存超限保护: {rule_key} 内存达到 {round(current_mem,1)} MB 超过安全配额 ({max_mb} MB)，已自动强制终止进程保护电脑不卡死！"
                            # log_msg recorded
                            self.guardian_logs.append({
                                "time": timestamp,
                                "type": "kill",
                                "app": rule_key,
                                "message": log_msg
                            })
                        else: # alert
                            log_msg = f"[{timestamp}] ⚠️ 内存超限告警: {rule_key} 当前物理内存 {round(current_mem,1)} MB (超过限制 {max_mb} MB)"
                            self.guardian_logs.append({
                                "time": timestamp,
                                "type": "alert",
                                "app": rule_key,
                                "message": log_msg
                            })

                        if len(self.guardian_logs) > 200:
                            self.guardian_logs = self.guardian_logs[-100:]

            except Exception as e:
                # 捕获守护异常，确保不中断循环
                await asyncio.sleep(5.0)

    # ---------------- Winget 在线软件搜索与一键安装 ----------------
    def search_online_apps(self, keyword: str) -> List[Dict[str, Any]]:
        """调用系统 Winget 在线软件源搜索软件包"""
        if not keyword.strip():
            return []
        try:
            cmd = ["powershell", "-NoProfile", "-Command", f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; winget search {keyword.strip()} -n 12 --accept-source-agreements"]
            res = subprocess.run(cmd, capture_output=True, timeout=12)
            lines = res.stdout.decode('utf-8', errors='ignore').splitlines()

            results = []
            start_parsing = False
            for line in lines:
                if "---" in line:
                    start_parsing = True
                    continue
                if start_parsing and line.strip():
                    parts = line.split()
                    if len(parts) >= 3:
                        # 格式通常为: Name, Id, Version, Source
                        # 查找包含英文点号或类似标准的 ID 列
                        pkg_id = parts[1] if "." in parts[1] else parts[-3] if len(parts) >= 4 and "." in parts[-3] else parts[1]
                        pkg_name = parts[0]
                        version = parts[2] if len(parts) > 2 else ""
                        results.append({
                            "name": pkg_name,
                            "id": pkg_id,
                            "version": version,
                            "source": parts[-1] if len(parts) > 3 else "winget"
                        })
            return results
        except Exception as e:
            return [{"name": "搜索出错", "id": "", "version": "", "source": str(e)}]

    def install_online_app(self, package_id: str) -> Dict[str, Any]:
        """后台静默安装指定的 Winget 软件包"""
        try:
            # 异步启动安装进程，不阻塞主线程
            cmd = f'winget install --id "{package_id}" --silent --accept-package-agreements --accept-source-agreements'
            subprocess.Popen(["powershell", "-Command", cmd], shell=True)
            return {"success": True, "message": f"已在后台启动安装向导: {package_id}，稍后可在列表中刷新查看！"}
        except Exception as e:
            return {"success": False, "message": f"调用安装失败: {str(e)}"}

apps_manager = AppsManager()
