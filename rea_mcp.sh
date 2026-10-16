#!/usr/bin/env bash
# REA (Reverse Engineer Anything) Standard MCP Stdio Launcher
# Ensures Node.js v22+ environment is loaded for ES import compatibility

NODE_V22_BIN="/Users/minfengyu/.nvm/versions/node/v22.20.0/bin"
REA_MJS="/Users/minfengyu/.nvm/versions/node/v22.20.0/lib/node_modules/rea-agents/scripts/rea.mjs"

# Prepend Node v22 to PATH if present
if [ -d "$NODE_V22_BIN" ]; then
    export PATH="$NODE_V22_BIN:$PATH"
fi

if [ -f "$REA_MJS" ]; then
    exec node "$REA_MJS" --mcp "$@"
else
    exec rea --mcp "$@"
fi
