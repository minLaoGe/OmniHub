#!/usr/bin/env bash
# ==============================================================================
# OmniHub - 统一大模型与多服务中枢平台启动脚本
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

PORT="${1:-9527}"
HOST="0.0.0.0"
URL="http://127.0.0.1:$PORT"

# 虚拟环境探测与激活
if [ -d "$DIR/../.venv" ]; then
    source "$DIR/../.venv/bin/activate"
elif [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
fi

# 检查依赖
python3 -c "import fastapi, uvicorn, httpx, psutil, mcp" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "📦 正在安装运行依赖..."
    pip install fastapi uvicorn httpx psutil mcp
fi

# 检查端口占用
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️ 端口 $PORT 已被占用，正在打开已运行的控制台: $URL"
    open "$URL"
    exit 0
fi

echo "=================================================================="
echo "🌟 正在启动 OmniHub 统一大模型与服务中枢平台..."
echo "📍 运行端口: $PORT"
echo "🌐 统一控制台入口: $URL"
echo "=================================================================="

# 自动在浏览器中打开控制台
(sleep 1.2 && open "$URL") &

# 启动 FastAPI 服务
exec python3 -m uvicorn app.main:app --host $HOST --port $PORT --reload
