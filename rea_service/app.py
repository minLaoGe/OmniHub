import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="REA Reverse Engineering Workbench", version="6.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "templates" / "index.html"

NODE_BIN = "/Users/minfengyu/.nvm/versions/node/v22.20.0/bin/node"
REA_MJS = "/Users/minfengyu/.nvm/versions/node/v22.20.0/lib/node_modules/rea-agents/scripts/rea.mjs"

def get_rea_env() -> dict:
    env = os.environ.copy()
    node_dir = "/Users/minfengyu/.nvm/versions/node/v22.20.0/bin"
    env["PATH"] = f"{node_dir}:{env.get('PATH', '')}"
    return env

async def run_rea_cmd(args: List[str], timeout: int = 60) -> Dict[str, Any]:
    cmd = [NODE_BIN, REA_MJS] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=get_rea_env()
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out_str = stdout.decode("utf-8", errors="replace")
        err_str = stderr.decode("utf-8", errors="replace")
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": out_str,
            "stderr": err_str
        }
    except asyncio.TimeoutError:
        return {"success": False, "returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stdout": "", "stderr": str(e)}

@app.get("/", response_class=HTMLResponse)
async def index_view():
    if HTML_FILE.exists():
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>REA Workbench HTML file not found</h1>", status_code=404)

@app.get("/api/status")
async def get_status():
    doc_res = await run_rea_cmd(["mcp", "doctor"], timeout=15)
    return {
        "rea_version": "6.4.0",
        "node_path": NODE_BIN,
        "mjs_path": REA_MJS,
        "healthy": doc_res["success"],
        "doctor_raw": doc_res["stdout"] if doc_res["success"] else doc_res["stderr"]
    }

@app.get("/api/providers")
async def get_providers():
    res = await run_rea_cmd(["providers"], timeout=20)
    return {
        "success": res["success"],
        "output": res["stdout"] if res["success"] else res["stderr"]
    }

# Cache for tools
CACHED_TOOLS = None

@app.get("/api/tools")
async def get_tools():
    global CACHED_TOOLS
    if CACHED_TOOLS is not None:
        return {"count": len(CACHED_TOOLS), "tools": CACHED_TOOLS}

    # Query via MCP protocol
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    try:
        params = StdioServerParameters(
            command=NODE_BIN,
            args=[REA_MJS, "--mcp"],
            env=get_rea_env()
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_res = await session.list_tools()
                categorized_tools = []
                for t in tools_res.tools:
                    name = t.name
                    desc = t.description or ""
                    schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", {})

                    # Classify category
                    cat = "General"
                    if "adb" in name or "android" in name or "apk" in name:
                        cat = "Android / APK"
                    elif "apple" in name or "macho" in name or "plist" in name or "hopper" in name:
                        cat = "Apple / Mach-O"
                    elif "pe" in name or "windows" in name or "managed" in name:
                        cat = "Windows / PE / .NET"
                    elif "web" in name or "javascript" in name or "electron" in name:
                        cat = "Web / JavaScript / Electron"
                    elif "procedure" in name or "instruction" in name or "disasm" in name or "decompile" in name or "function" in name:
                        cat = "Decompilation & Disassembly"
                    elif "trace" in name or "observe" in name or "inspect" in name:
                        cat = "Dynamic Analysis & Inspection"

                    categorized_tools.append({
                        "name": name,
                        "description": desc,
                        "category": cat,
                        "inputSchema": schema
                    })

                CACHED_TOOLS = categorized_tools
                return {"count": len(CACHED_TOOLS), "tools": CACHED_TOOLS}
    except Exception as e:
        return {"count": 0, "tools": [], "error": str(e)}

class AnalyzeRequest(BaseModel):
    target_path: str
    format: Optional[str] = "json"

@app.post("/api/analyze")
async def analyze_target(req: AnalyzeRequest):
    if not req.target_path or not req.target_path.strip():
        raise HTTPException(status_code=400, detail="Target path is required")
    
    target = req.target_path.strip()
    if not os.path.exists(target):
        return {"success": False, "error": f"Target file or directory not found: {target}"}

    args = ["analyze", target]
    if req.format == "json":
        args.extend(["--format", "json"])

    res = await run_rea_cmd(args, timeout=120)
    return res

class RunCmdRequest(BaseModel):
    command: str
    args: Optional[List[str]] = []

@app.post("/api/cmd")
async def run_custom_cmd(req: RunCmdRequest):
    allowed_commands = [
        "mcp", "providers", "list-adb-devices", "list-adb-packages",
        "search-android-classes", "analyze", "help", "--version"
    ]
    if req.command not in allowed_commands:
        raise HTTPException(status_code=400, detail=f"Command '{req.command}' not permitted")

    full_args = [req.command] + (req.args or [])
    res = await run_rea_cmd(full_args, timeout=60)
    return res

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8877)
