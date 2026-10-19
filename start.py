#!/usr/bin/env python3
"""
OmniHub - 跨平台通用启动器 (Windows, macOS, Linux)
使用纯标准库探测环境、检查并安装依赖、检测端口占用并在浏览器中自动打开统一控制台
"""

import os
import sys
import time
import socket
import webbrowser
import subprocess
import platform
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CURRENT_OS = platform.system()

def check_and_install_dependencies():
    packages = ["fastapi", "uvicorn", "httpx", "psutil", "mcp"]
    missing = []
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"📦 正在自动安装运行依赖: {', '.join(missing)} ...")
        cmd = [sys.executable, "-m", "pip", "install"] + missing
        subprocess.check_call(cmd)
        print("✅ 依赖安装完成！")

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0

def find_available_port(start_port: int = 9527) -> int:
    port = start_port
    while port < 65535:
        if not is_port_in_use(port):
            return port
        port += 1
    return start_port

def main():
    os.chdir(str(BASE_DIR))
    sys.path.insert(0, str(BASE_DIR))

    check_and_install_dependencies()

    port = 9527
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    if is_port_in_use(port):
        print(f"⚠️ 端口 {port} 已被占用，正在直接打开现有控制台...")
        webbrowser.open(f"http://127.0.0.1:{port}")
        sys.exit(0)

    url = f"http://127.0.0.1:{port}"
    print("=" * 66)
    print(f"🌟 正在启动 OmniHub 跨平台服务中枢平台 ({CURRENT_OS}) ...")
    print(f"📍 服务端口: {port}")
    print(f"🌐 统一控制台入口: {url}")
    print("=" * 66)

    # 延迟 1.2 秒自动打开浏览器
    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import threading
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
