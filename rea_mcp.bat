@echo off
REM REA MCP Stdio Server Launcher for Windows
where rea >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    rea --mcp %*
) else (
    npx -y rea-agents@latest --mcp %*
)
