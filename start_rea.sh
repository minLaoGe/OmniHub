#!/usr/bin/env bash
# 启动 REA 逆向工程分析控制台 (REA Reverse Engineering Workbench)
# 默认端口: 8877
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

PORT="${1:-8877}"
URL="http://127.0.0.1:$PORT"

# 检查当前端口是否已经被占用
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "========================================================"
    echo "  REA 逆向工程分析控制台已经在运行中！"
    echo "  访问地址: $URL"
    echo "========================================================"
    exit 0
fi

# 激活虚拟环境（如果存在）
if [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
fi

# 注入 Node 22 环境
NODE_V22_BIN="/Users/minfengyu/.nvm/versions/node/v22.20.0/bin"
if [ -d "$NODE_V22_BIN" ]; then
    export PATH="$NODE_V22_BIN:$PATH"
fi

echo "========================================================"
echo "  🚀 正在启动 REA 逆向工程分析控制台 (v6.4.0)..."
echo "  服务端口: $PORT"
echo "  访问地址: $URL"
echo "  集成支持: 170+ MCP 工具 / 动静态逆向 / Android / iOS / PE"
echo "========================================================"

exec python3 -m uvicorn rea_service.app:app --host 127.0.0.1 --port "$PORT"
