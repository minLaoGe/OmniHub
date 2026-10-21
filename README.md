# 🌟 OmniHub - Unified AI & Service Gateway Platform
### 大模型、多服务与电脑系统资源一体化统一中枢平台

<p align="center">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-blue?style=for-the-badge&logo=apple&logoColor=white" />
  <img src="https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Frontend-TailwindCSS%20%7C%20Vue3%20(100%25%20Offline)-emerald?style=for-the-badge" />
  <img src="https://img.shields.io/badge/License-MIT-amber?style=for-the-badge" />
</p>

---

[English](#english-documentation) | [中文说明](#中文文档)

---

<a name="中文文档"></a>
## 🇨🇳 中文文档

### 📖 项目简介
**OmniHub** 是一款专为**本地大模型、绘图引擎、后台工具以及主机系统应用与进程**打造的**一体化统一集成控制台与资源网关中枢**。

日常本地跑 AI 服务与日常电脑使用时，常常面临多个痛点：
- **服务零散碎片化**：端口分散（如 8088、8188、8899 等），每次都要翻终端窗口、找启动脚本，浏览器打开十几个 Tab 标签页来回切；
- **内存泄漏与整机卡顿**：本地大模型、大型 IDE 或桌面客户端（如**抖音客户端**、各类浏览器）吃满物理内存，甚至引发整机死机；
- **应用管理繁琐无序**：电脑上安装的各类软件难以统揽全局，想要临时结束进程、查找安装所在文件夹或彻底卸载需要层层翻找；
- **AI 智能体缺少系统抓手**：本地智能体（AI Agent）缺少统一的管理接口，无法自主感知和调度后台服务与宿主机资源。

**OmniHub** 将所有 AI 服务的生命周期、系统应用/进程资源管控、物理内存智能压缩释放、硬盘空间统计及 MCP 调试大厅完美汇聚在单个现代化 WebUI 界面中（默认端口 `9527`），并内置了专属 **MCP Server**，让任何 AI Agent 都能通过标准 MCP 协议对全系统进行全自动感知与操控！

---

### 📸 核心界面概览

#### 1. 系统全景仪表盘 (System Overview & Services)
实时呈现宿主机硬件负载（CPU 使用率、物理内存水线、硬盘使用情况）、运行中服务总览与实时健康监控。
![OmniHub Dashboard](docs/screenshots/dashboard.png)

#### 2. 本地应用与进程管理大厅 (App & Process Management)
穿透扫描全电脑已安装软件与实时进程树，支持卡片网格与专业列表双视图、多维度排序（内存、磁盘占用、CPU）、一键启动/杀进程/文件定位/卸载。
![Service Management](docs/screenshots/services.png)

#### 3. MCP 注册与交互式调试大厅 (MCP Hub & Playground)
自动发现并解析任何 MCP Server 的工具与其 JSON Schema，动态生成参数表单，支持在线填参测试与调用执行。
![MCP Hub Playground](docs/screenshots/mcp_hub.png)

#### 4. AI 智能调度助手 (Autonomous AI Agent with MCP)
连接本地大模型（默认 Qwen3.8-27B 或任意 OpenAI 兼容模型），通过 Function Calling 自动识别意图并调度后台服务、清理系统内存或执行 MCP 工具任务。
![AI Assistant](docs/screenshots/ai_agent.png)

---

### ✨ 核心特性

#### 💻 1. 本地应用与运行进程统一管控 (PC Apps & Process Manager)
- **全方位应用发现**：穿透扫描 Windows 64位/32位/当前用户注册表及开始菜单，毫秒级还原快捷方式（`.lnk`）至底层真实 `.exe` 实体路径与安装根目录。
- **双视图随心切换**：
  - 🗂️ **卡片网格视图 (Grid View)**：直观展现软件图标、发布者、内存占用徽章与核心快捷入口。
  - 📋 **专业生产力列表 (Table View)**：多列信息清晰呈现，一览应用名、版本、实时进程、内存 (MB)、磁盘大小 (GB)、CPU 负载及启动路径。
- **多维度实时排序**：支持按照应用名称、物理内存占用（升序/降序）、磁盘占用大小、CPU 占用、运行状态多维正倒序实时重排。
- **四大一键快捷操作**：
  - 🚀 **一键极速启动 (Launch)**：直接调起目标本地软件。
  - 🛑 **一键强杀进程树 (Kill Tree)**：干净递归终止所有关联进程，瞬间释放占用的句柄与系统资源。
  - 📂 **一键定位高亮 (Reveal in Explorer)**：多级回退原生 ShellExecute 机制，**100% 必弹系统资源管理器**并精准选中高亮该 `.exe` 文件。
  - 🗑️ **一键官方卸载 (Uninstall)**：快速调起官方卸载向导或 Winget 卸载引擎。

#### ⚡ 2. Windows 物理内存工作集智能压缩与守护 (Memory Trimming & Guardian)
- **无需杀进程，瞬间释放数百 MB 物理内存**：针对抖音客户端 (Douyin)、浏览器多标签页、大型 Electron 软件等“内存大户”，原生调用 Windows 底层 `EmptyWorkingSet` 核心 API，瞬间压缩释放物理内存（RSS），将数百兆内存回收到 30~50MB，软件依然保持正常运行不中断！
- **后台自动巡检守护进程 (MemoryGuardian)**：内置后台轮询守护引擎，按预设上限自动巡检。当软件超过配额时，自动触发 WorkingSet 内存压缩、终止或预警。
- **实时审计流与事件日志**：WebUI 实时同步后台压降记录、释放前后内存变化与时间戳。

#### 📊 3. 硬盘占用异步扫描与多级区间筛选 (Disk Usage Scanner)
- **非阻塞后台多线程统计**：异步遍历计算各软件安装目录的真实文件物理大小，按目录去重缓存，避免界面卡顿。
- **多档区间智能筛选**：支持一键按空间消耗过滤，如 **>5GB**、**1GB~5GB**、**500MB~1GB**、**<500MB** 以及支持自定义 MB 范围精确检索。

#### 🛒 4. 微软 Winget 在线软件商店与一键部署 (Winget Store)
- 免开命令行终端，Web 界面直连微软官方 Winget 源搜索海量桌面应用，实时查看应用 ID 与版本，一键在后台自动部署安装。

#### 🤖 5. 多服务生命周期管理 & 跨平台进程守护
- **一站式管理**：预置或自定义管理本地 LLM 推理（llama-server / Ollama / vLLM）、ComfyUI、知识库助手等任意命令或脚本。
- **动态端口热改与参数注入**：在 Web 界面直接为任意服务修改监听端口，自动热注入启动参数，内嵌工作区 URL 毫秒级同步。
- **进程树级 OOM 内存防护**：三级防护策略——⚠️ **仅告警 (alert)** | 🔄 **自动重启释放内存 (restart)** | 🛑 **安全终止防死机 (stop)**。
- **WebSocket 实时日志推流**：告别终端乱切，单屏实时掌控各服务标准输出与报错。

#### 🌐 6. OpenAI 兼容通用反向代理网关 (OpenAI Proxy Gateway)
- 原生提供 `/v1/chat/completions` 与 `/v1/models` 标准端点。
- 支持全自动路由容错、降级重试与多后端模型转发，无缝接入各类第三方开源客户端（NextChat、LobeChat、Cherry Studio、Chatbox 等）。

#### 🔍 7. REA (Reverse Engineer Anything) 深度逆向套件与 170+ MCP 工具
- 原生集成 REA 逆向分析引擎，提供专属 Web 控制台 (`http://127.0.0.1:8877`)。
- 覆盖 Android APK、iOS/macOS Mach-O、Windows PE/.NET、Electron/JavaScript 伪代码反编译与动态调用追踪。
- 结合智能语义上下文工具路由（Smart Tool Routing），在本地大模型（如 8K 窗口）中精准毫秒级检索匹配所需逆向工具。

#### 🔌 8. OmniHub 专属 MCP Server (`omnihub-service-manager`)
本地 AI Agent（Antigravity, Claude Desktop, Cursor, Cline）可通过标准 MCP 协议全面感知和操控整台电脑：
- **服务编排工具**：`list_all_services`, `start_service`, `stop_service`, `restart_service`, `configure_service_port_and_memory`, `get_service_logs`, `get_service_project_path`, `reveal_service_in_explorer`
- **系统应用与资源工具**：
  - `list_system_apps(search, only_running)`: 查询电脑安装软件、进程 PID、内存/CPU/磁盘占用
  - `trim_app_memory(app_name)`: 原生触发 Windows 内存工作集压缩，秒级压降物理内存
  - `kill_app_process(app_name)`: 递归强制终止应用进程树
  - `set_app_memory_limit(app_name, max_memory_mb, action)`: 设定内存守护配额规则
  - `reveal_app_in_explorer(launch_path, install_location, app_name)`: 在系统资源管理器中打开并高亮定位
  - `get_memory_guardian_logs(limit)`: 获取内存守护后台优化日志
- **系统健康工具**：`get_system_health_metrics()`, `get_omnihub_project_path()`

#### 🛡️ 9. 100% 纯本地离线化架构 (Zero CDN Dependency)
- Vue 3 与 TailwindCSS 全部内置打包于 `static/vendor/` 静态目录，彻底杜绝外部公共 CDN 故障或无网导致的白屏与排版混乱，局域网与内网隔离环境开箱即用。

---

### 🚀 快速开始

#### 环境要求
- Python 3.10+
- 推荐操作系统：Windows 10/11、macOS、Linux

#### 启动服务

**Windows 用户：**
直接双击根目录 `start.bat` 或在终端运行：
```cmd
start.bat
```

**macOS / Linux 用户：**
```bash
chmod +x start.sh
./start.sh
```

**跨平台通用 Python 启动（所有系统）：**
```bash
python start.py
```

启动脚本会自动安装必要依赖，并在默认浏览器中自动打开统一控制台：
👉 **http://127.0.0.1:9527**

---

### 🧩 本地 AI Agent 接入配置 (MCP)

在你的 Claude Desktop / Cursor / Antigravity / Cline 配置文件（如 `claude_desktop_config.json` 或 `mcp_config.json`）中添加：

```json
{
  "mcpServers": {
    "omnihub-service-manager": {
      "command": "python",
      "args": [
        "C:\Users\your_user\path\to\OmniHub\omnihub_mcp_server.py"
      ]
    }
  }
}
```

---
---

<a name="english-documentation"></a>
## 🇬🇧 English Documentation

### 📖 Introduction
**OmniHub** is an all-in-one unified dashboard, service gateway, local application manager, and Model Context Protocol (MCP) hub designed for local AI models, generative workflows, developer daemons, and host system resources.

When running multiple AI services and desktop applications locally, users and developers face notable challenges:
- **Scattered Services**: Fragmented ports (8088, 8188, 8899, etc.) and endless terminal windows;
- **Memory Bloat & System Freezes**: Heavy local models, desktop streaming apps (e.g., Douyin / TikTok clients), and browsers exhausting RAM;
- **Cluttered App Management**: Difficult to inspect all installed software, locate binary directories, or clean up lingering process trees;
- **AI Agents Lack System Control**: Local AI Agents lack standard tools to perceive host health, manage background apps, or optimize memory.

**OmniHub** aggregates everything into a single modern WebUI (default port `9527`) and exposes a powerful **MCP Server**, empowering any AI Agent to orchestrate services, monitor hardware, and optimize memory programmatically.

---

### ✨ Key Features

1. **Host App & Process Resource Manager**
   - Deep scanning across Windows Registry (64-bit, 32-bit, Current User) and Start Menu shortcuts (resolves `.lnk` to true target `.exe` paths).
   - Dual View Modes: **Card Grid View** & **Professional Table List View**.
   - Multi-Column Dynamic Sorting: Sort by Name, RAM usage (MB), Disk footprint (GB), CPU load, and Running status.
   - 1-Click Operations: 🚀 Launch | 🛑 Kill Process Tree | 📂 Reveal in File Explorer (with highlight) | 🗑️ Official / Winget Uninstall.

2. **Windows WorkingSet Memory Trimming & Guardian**
   - Native Windows `EmptyWorkingSet` memory compression: reclaim hundreds of megabytes of physical RAM without stopping or restarting apps (ideal for Douyin, Chrome, etc.).
   - Background guardian engine (`MemoryGuardian`) periodically inspects active processes and enforces configurable quotas (Trim / Kill / Alert).

3. **Asynchronous Disk Usage Scanner & Range Filtering**
   - Non-blocking background folder calculation with caching.
   - Presets for filtering disk footprints: `>5GB`, `1GB~5GB`, `500MB~1GB`, `<500MB`, or custom MB ranges.

4. **Integrated Winget Online Software Store**
   - Search Microsoft Winget catalog directly within the WebUI and trigger 1-click silent/interactive installations.

5. **AI Service Lifecycle & OOM Guardian**
   - Manage local LLMs (llama.cpp, Ollama, vLLM), ComfyUI, and custom daemons with start, stop, restart, and dynamic port overriding.
   - OOM protection: Alert, Auto-restart, or Safe stop.
   - WebSocket streaming real-time log viewer.

6. **Universal OpenAI-Compatible Proxy Gateway**
   - Standard `/v1/chat/completions` and `/v1/models` endpoints with automatic route tolerance and multi-backend multiplexing.

7. **REA Reverse Engineering Workbench & 170+ MCP Tools**
   - Native integration with REA v6.4.0 reverse-engineering suite (`http://127.0.0.1:8877`).
   - 170+ tools for APKs, Mach-O binaries, Windows PE/.NET, and Electron apps with smart semantic context routing.

8. **Dedicated MCP Server (`omnihub-service-manager`)**
   - Exposes comprehensive tools for AI agents (Claude Desktop, Antigravity, Cursor, Cline):
     - Service orchestration: `list_all_services`, `start_service`, `stop_service`, `restart_service`, `configure_service_port_and_memory`
     - System app management: `list_system_apps`, `trim_app_memory`, `kill_app_process`, `set_app_memory_limit`, `reveal_app_in_explorer`, `get_memory_guardian_logs`
     - Host monitoring: `get_system_health_metrics`, `get_omnihub_project_path`

9. **100% Offline-Ready Architecture**
   - Vue 3 and TailwindCSS assets pre-bundled locally in `static/vendor/`. Works seamlessly in air-gapped intranet environments with zero CDN dependency.

---

### 🚀 Getting Started

```bash
# Windows
start.bat

# macOS / Linux
chmod +x start.sh
./start.sh

# Universal Python (All Platforms)
python start.py
```

Then visit: 👉 **http://127.0.0.1:9527**

---

### 📝 Development & Push Log

For detailed release and commit logs, refer to [PUSH_LOG.md](PUSH_LOG.md).

To re-compile TailwindCSS styles locally:
```powershell
npx --yes --package tailwindcss@3.4.17 tailwindcss -c tailwind.config.cjs -i static/css/tailwind.input.css -o static/vendor/tailwind.min.css --minify
```

---

### 📄 License
This project is licensed under the [MIT License](LICENSE).
