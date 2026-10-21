const { createApp, ref, computed, onMounted, onUnmounted, nextTick } = Vue;

const app = createApp({
  setup() {
    // Current Active View
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab') || 'dashboard';
    const currentTab = ref(initialTab);

    // Global Toast Notification System
    const toasts = ref([]);
    let toastIdCounter = 0;
    const showToast = (message, type = 'info', duration = 3500) => {
      const id = ++toastIdCounter;
      toasts.value.push({ id, message, type });
      setTimeout(() => {
        toasts.value = toasts.value.filter(t => t.id !== id);
      }, duration);
    };

    // System stats
    const stats = ref({
      os_name: "macOS",
      os_family: "Darwin",
      os_release: "",
      cpu_percent: 0,
      memory: { total_gb: 0, used_gb: 0, percent: 0 },
      disk: { total_gb: 0, free_gb: 0, percent: 0 },
      services_count: 0,
      running_services_count: 0,
      mcp_servers_count: 0,
      total_tools_count: 0
    });

    // OmniHub Root & Project Info
    const omnihubProject = ref({
      root_dir: "",
      platform: "OmniHub",
      services_file: "",
      mcp_servers_file: "",
      os: "",
      services_count: 0
    });

    // Copy to clipboard helper
    const copyText = async (text, label = '路径') => {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        showToast(`📋 已成功复制${label}到剪贴板！`, 'success', 2500);
      } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast(`📋 已成功复制${label}到剪贴板！`, 'success', 2500);
      }
    };

    // Open directory in native file manager (Finder / File Explorer)
    const revealService = async (serviceId) => {
      try {
        showToast(`📂 正在打开文件管理器定位...`, 'info', 2000);
        const res = await fetch(`/api/services/${encodeURIComponent(serviceId)}/reveal`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`📂 已在系统访达/文件管理器中定位项目目录！`, 'success', 3000);
        } else {
          showToast(`⚠️ 定位失败: ${data.message || data.error || "未知错误"}`, 'error', 3500);
        }
      } catch (e) {
        showToast(`⚠️ 定位出错: ${e}`, 'error', 3500);
      }
    };

    // Services
    const services = ref([]);
    const serviceFilter = ref('all');
    const filteredServices = computed(() => {
      if (serviceFilter.value === 'all') return services.value;
      return services.value.filter(s => s.category === serviceFilter.value);
    });

    // Service Action In-Progress Trackers (id -> 'starting' | 'stopping' | 'restarting')
    const actionLoading = ref({});

    // Logs Drawer & WebSocket
    const logsModalOpen = ref(false);
    const activeLogService = ref(null);
    const logLines = ref([]);
    let logWs = null;

    // MCP
    const mcpServers = ref([]);
    const mcpToolsMap = ref({});
    const selectedMCPServer = ref(null);
    const selectedTool = ref(null);
    const toolArgs = ref({});
    const toolCallLoading = ref(false);
    const toolCallResult = ref(null);

    // Workspace Iframe Tabs
    const workspaceServices = computed(() => {
      return services.value.filter(s => s.url && s.port);
    });
    const currentWorkspaceId = ref(null);
    const currentWorkspaceService = computed(() => {
      return services.value.find(s => s.id === currentWorkspaceId.value) || workspaceServices.value[0];
    });

    const isQwenRunning = computed(() => {
      const s = services.value.find(item => item.id === 'qwen27b');
      return s && s.status === 'RUNNING';
    });

    // AI Assistant
    const aiMessages = ref([
      {
        role: "assistant",
        content: "你好！我是 OmniHub 统一服务中枢助手。我支持跨平台（Windows / macOS / Linux）管理所有服务、支持动态修改启动端口、设定内存上限防护，并可自动调用已注册的 MCP 工具。"
      }
    ]);
    const aiInput = ref("");
    const aiLoading = ref(false);
    const enableAITools = ref(true);

    // Settings
    const settings = ref({
      llm_api_base: "http://127.0.0.1:8088/v1",
      llm_model_name: "Qwen3.8-27B",
      llm_api_key: "not-needed"
    });

    // Modals: Add New Service
    const newServiceModalOpen = ref(false);
    const newServiceForm = ref({
      id: "",
      name: "",
      description: "",
      category: "ai_model",
      command: "python3",
      args: "",
      cwd: "",
      port: 8000,
      max_memory_mb: 4096,
      memory_limit_action: "alert",
      url: "http://127.0.0.1:8000"
    });

    // Modals: Edit Service Config (Port & Memory Limit)
    const editServiceModalOpen = ref(false);
    const editServiceForm = ref({
      id: "",
      name: "",
      description: "",
      category: "ai_model",
      port: 8088,
      max_memory_mb: 4096,
      memory_limit_action: "alert",
      command: "",
      args: "",
      cwd: ""
    });

    // Modals: Add New MCP
    const newMCPModalOpen = ref(false);
    const newMCPForm = ref({
      id: "",
      name: "",
      description: "",
      type: "stdio",
      command: "python3",
      args: ""
    });

    // Polling timer
    let pollInterval = null;

    const fetchOmniHubProject = async () => {
      try {
        const res = await fetch('/api/system/project');
        if (res.ok) {
          omnihubProject.value = await res.json();
        }
      } catch (e) {
        console.error("fetchOmniHubProject error:", e);
      }
    };

    const fetchStats = async () => {
      try {
        const res = await fetch('/api/system/stats');
        if (res.ok) {
          stats.value = await res.json();
          if (stats.value.os_family === 'Windows' && newServiceForm.value.command === 'python3') {
            newServiceForm.value.command = 'python';
          }
        }
      } catch (e) {
        console.error("fetchStats error:", e);
      }
    };

    const fetchServices = async () => {
      try {
        const res = await fetch('/api/services');
        if (res.ok) {
          const list = await res.json();
          // Keep current action status if still processing
          services.value = list.map(item => {
            if (actionLoading.value[item.id]) {
              const act = actionLoading.value[item.id];
              item.status = act === 'stopping' ? 'STOPPING' : (act === 'starting' ? 'STARTING' : item.status);
            }
            return item;
          });

          if (!currentWorkspaceId.value && workspaceServices.value.length > 0) {
            currentWorkspaceId.value = workspaceServices.value[0].id;
          }
        }
      } catch (e) {
        console.error("fetchServices error:", e);
      }
    };

    const startService = async (id) => {
      const s = services.value.find(item => item.id === id);
      const name = s ? s.name : id;

      actionLoading.value[id] = 'starting';
      if (s) s.status = 'STARTING';
      showToast(`🚀 正在启动服务「${name}」...`, 'info', 2500);

      try {
        const res = await fetch(`/api/services/${id}/start`, { method: 'POST' });
        const data = await res.json();

        if (data.success) {
          showToast(`⏳「${name}」进程已拉起，正在初始化监听...`, 'info', 2000);
        } else {
          showToast(`❌ 启动失败: ${data.message}`, 'error', 4000);
        }

        await fetchServices();

        // 1.8秒后二次确认运行状态
        setTimeout(async () => {
          delete actionLoading.value[id];
          await fetchServices();
          const updated = services.value.find(item => item.id === id);
          if (updated) {
            if (updated.status === 'RUNNING') {
              showToast(`✅ 服务「${name}」已成功启动并就绪！(端口: ${updated.port})`, 'success', 3500);
            } else if (updated.status === 'ERROR') {
              showToast(`❌ 服务「${name}」启动异常退出，已自动为你打开错误日志`, 'error', 5000);
              openLogs(updated);
            }
          }
        }, 1800);

        return data;
      } catch (e) {
        delete actionLoading.value[id];
        showToast(`❌ 请求异常: ${e}`, 'error', 4000);
      }
    };

    const stopService = async (id) => {
      const s = services.value.find(item => item.id === id);
      const name = s ? s.name : id;

      actionLoading.value[id] = 'stopping';
      if (s) s.status = 'STOPPING';
      showToast(`🛑 正在终止服务「${name}」并释放端口占用...`, 'warning', 3000);

      try {
        const res = await fetch(`/api/services/${id}/stop`, { method: 'POST' });
        const data = await res.json();

        delete actionLoading.value[id];
        await fetchServices();

        if (data.success) {
          showToast(`✅ 服务「${name}」已彻底安全停止，端口已成功释放！`, 'success', 3500);
        } else {
          showToast(`❌ 停止服务失败: ${data.message}`, 'error', 4000);
        }
      } catch (e) {
        delete actionLoading.value[id];
        showToast(`❌ 停止请求出错: ${e}`, 'error', 4000);
      }
    };

    const restartService = async (id) => {
      const s = services.value.find(item => item.id === id);
      const name = s ? s.name : id;

      actionLoading.value[id] = 'restarting';
      showToast(`🔄 正在安全重启服务「${name}」...`, 'info', 3000);

      try {
        const res = await fetch(`/api/services/${id}/restart`, { method: 'POST' });
        const data = await res.json();

        setTimeout(async () => {
          delete actionLoading.value[id];
          await fetchServices();
          showToast(`✅ 服务「${name}」已重启完毕！`, 'success', 3000);
        }, 1500);
      } catch (e) {
        delete actionLoading.value[id];
        showToast(`❌ 重启失败: ${e}`, 'error', 4000);
      }
    };

    const openLogs = async (service) => {
      activeLogService.value = service;
      logsModalOpen.value = true;
      logLines.value = [];

      if (logWs) {
        logWs.close();
      }

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/logs/${service.id}`;
      logWs = new WebSocket(wsUrl);

      logWs.onmessage = (event) => {
        logLines.value.push(event.data);
        nextTick(() => {
          const el = document.getElementById("logContainer");
          if (el) el.scrollTop = el.scrollHeight;
        });
      };
    };

    const closeLogs = () => {
      logsModalOpen.value = false;
      if (logWs) {
        logWs.close();
        logWs = null;
      }
    };

    // Edit Service Modal Handlers
    const openEditService = (service) => {
      editServiceForm.value = {
        id: service.id,
        name: service.name,
        description: service.description || "",
        category: service.category || "ai_model",
        port: service.port || 8000,
        max_memory_mb: service.max_memory_mb !== undefined ? service.max_memory_mb : 0,
        memory_limit_action: service.memory_limit_action || "alert",
        command: service.command || "",
        args: Array.isArray(service.args) ? service.args.join(" ") : (service.args || ""),
        cwd: service.cwd || ""
      };
      editServiceModalOpen.value = true;
    };

    const saveEditService = async () => {
      const form = editServiceForm.value;
      if (!form.port || form.port <= 0) {
        showToast("请输入有效的端口号！", "warning");
        return;
      }
      const argsArray = form.args ? form.args.split(" ").filter(Boolean) : [];
      const payload = {
        name: form.name,
        description: form.description,
        category: form.category,
        port: parseInt(form.port),
        max_memory_mb: parseInt(form.max_memory_mb) || 0,
        memory_limit_action: form.memory_limit_action,
        command: form.command,
        args: argsArray,
        cwd: form.cwd
      };

      try {
        const res = await fetch(`/api/services/${form.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          editServiceModalOpen.value = false;
          await fetchServices();
          showToast(`✅ 服务「${form.name}」配置已成功保存！`, 'success');
        } else {
          showToast("❌ 保存修改失败", "error");
        }
      } catch (e) {
        showToast(`❌ 请求异常: ${e}`, 'error');
      }
    };

    // MCP Handlers
    const fetchMCPServers = async () => {
      try {
        const res = await fetch('/api/mcp/servers');
        if (res.ok) {
          const list = await res.json();
          mcpServers.value = [
            {
              id: "builtin",
              name: "OmniHub 系统服务中枢 (内置)",
              description: "跨平台提供查看、启动、停止、重启系统内所有大模型与服务的内置核心工具"
            },
            ...list
          ];
          if (!selectedMCPServer.value && mcpServers.value.length > 0) {
            selectMCPServer(mcpServers.value[0]);
          }
        }
      } catch (e) {
        console.error("fetchMCPServers error:", e);
      }
    };

    const fetchMCPTools = async () => {
      try {
        const res = await fetch('/api/mcp/tools');
        if (res.ok) {
          mcpToolsMap.value = await res.json();
        }
      } catch (e) {
        console.error("fetchMCPTools error:", e);
      }
    };

    const selectMCPServer = (server) => {
      selectedMCPServer.value = server;
      selectedTool.value = null;
      toolCallResult.value = null;
      const tools = mcpToolsMap.value[server.id] || [];
      if (tools.length > 0) {
        selectTool(tools[0]);
      }
    };

    const selectTool = (tool) => {
      selectedTool.value = tool;
      toolCallResult.value = null;
      const args = {};
      const props = tool.inputSchema?.properties || {};
      for (const [key, prop] of Object.entries(props)) {
        if (prop.default !== undefined) {
          args[key] = prop.default;
        } else if (prop.type === 'boolean') {
          args[key] = false;
        } else if (prop.type === 'number' || prop.type === 'integer') {
          args[key] = 0;
        } else {
          args[key] = '';
        }
      }
      toolArgs.value = args;
    };

    const executeTool = async () => {
      if (!selectedTool.value || !selectedMCPServer.value) return;
      toolCallLoading.value = true;
      toolCallResult.value = null;
      showToast(`正在执行 MCP 工具: ${selectedTool.value.name}...`, 'info', 2000);

      try {
        const res = await fetch('/api/mcp/call', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            server_id: selectedMCPServer.value.id,
            tool_name: selectedTool.value.name,
            arguments: toolArgs.value
          })
        });
        const data = await res.json();
        toolCallResult.value = data;
        if (data.success) {
          showToast(`✅ MCP 工具 ${selectedTool.value.name} 执行完成！`, 'success');
        } else {
          showToast(`⚠️ 工具返回错误: ${data.error || '执行未成功'}`, 'error');
        }
        if (selectedTool.value.name.startsWith('omnihub_')) {
          await fetchServices();
        }
      } catch (e) {
        toolCallResult.value = { success: false, error: String(e) };
        showToast(`❌ 工具调用异常: ${e}`, 'error');
      } finally {
        toolCallLoading.value = false;
      }
    };

    const openInWorkspace = (service) => {
      currentWorkspaceId.value = service.id;
      currentTab.value = 'workspace';
      showToast(`已在工作区中加载服务「${service.name}」`, 'info', 2000);
    };

    const sendChatMessage = async () => {
      const q = aiInput.value.trim();
      if (!q || aiLoading.value) return;

      aiMessages.value.push({ role: "user", content: q });
      aiInput.value = "";
      aiLoading.value = true;

      const assistantMsg = {
        role: "assistant",
        content: "",
        reasoning: "",
        showReasoning: false,
        tool_calls: []
      };
      aiMessages.value.push(assistantMsg);

      try {
        const res = await fetch('/api/ai/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: aiMessages.value.slice(0, -1).map(m => ({ role: m.role, content: m.content })),
            enable_tools: enableAITools.value
          })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop();

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const chunk = JSON.parse(line);
              if (chunk.type === 'reasoning_chunk') {
                assistantMsg.reasoning += chunk.content;
                assistantMsg.showReasoning = true;
              } else if (chunk.type === 'content_chunk' || chunk.type === 'message') {
                assistantMsg.content += chunk.content;
              } else if (chunk.type === 'tool_call_start') {
                assistantMsg.tool_calls.push({
                  server_id: chunk.server_id,
                  tool_name: chunk.tool_name,
                  arguments: chunk.arguments,
                  status: 'running'
                });
                showToast(`🤖 AI 正在自主调度工具: ${chunk.tool_name}`, 'info', 2000);
              } else if (chunk.type === 'tool_call_result') {
                const target = assistantMsg.tool_calls.find(
                  tc => tc.tool_name === chunk.tool_name && tc.status === 'running'
                );
                if (target) {
                  target.status = 'done';
                  target.result = chunk.result;
                }
                if (chunk.tool_name.startsWith('omnihub_')) {
                  fetchServices();
                }
              } else if (chunk.type === 'error') {
                assistantMsg.content += `\n> ⚠️ **错误**: ${chunk.content}`;
                showToast(`❌ 对话异常: ${chunk.content}`, 'error', 5000);
              }
            } catch (err) {
              console.error("Parse line error:", err, line);
            }
          }
        }
      } catch (e) {
        assistantMsg.content += `\n> ⚠️ 发送消息发生网络异常: ${e}`;
        showToast(`❌ 网络请求失败: ${e}`, 'error');
      } finally {
        aiLoading.value = false;
        fetchServices();
      }
    };

    const saveNewService = async () => {
      const form = newServiceForm.value;
      if (!form.id || !form.name || !form.command) {
        showToast("请完整填写必填字段！", "warning");
        return;
      }
      const argsArray = form.args ? form.args.split(" ").filter(Boolean) : [];
      const portNum = parseInt(form.port) || 8000;
      const payload = {
        ...form,
        port: portNum,
        max_memory_mb: parseInt(form.max_memory_mb) || 0,
        args: argsArray,
        url: `http://127.0.0.1:${portNum}`
      };

      const res = await fetch('/api/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        newServiceModalOpen.value = false;
        await fetchServices();
        showToast(`✅ 新服务「${form.name}」已成功挂载！`, 'success');
      }
    };

    const deleteService = async (id) => {
      if (!confirm(`确定要移除服务 ${id} 吗？`)) return;
      await fetch(`/api/services/${id}`, { method: 'DELETE' });
      await fetchServices();
      showToast(`已删除服务 ${id}`, 'info');
    };

    const saveNewMCP = async () => {
      const form = newMCPForm.value;
      if (!form.id || !form.name || !form.command) {
        showToast("请完整填写必填字段！", "warning");
        return;
      }
      const argsArray = form.args ? form.args.split(" ").filter(Boolean) : [];
      const payload = {
        ...form,
        args: argsArray
      };

      const res = await fetch('/api/mcp/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        newMCPModalOpen.value = false;
        await fetchMCPServers();
        await fetchMCPTools();
        showToast(`✅ MCP 服务「${form.name}」注册成功！`, 'success');
      }
    };

    const deleteMCPServer = async (id) => {
      if (!confirm(`确定要移除 MCP 服务器 ${id} 吗？`)) return;
      await fetch(`/api/mcp/servers/${id}`, { method: 'DELETE' });
      await fetchMCPServers();
      await fetchMCPTools();
      if (selectedMCPServer.value?.id === id) {
        if (mcpServers.value.length > 0) {
          selectMCPServer(mcpServers.value[0]);
        } else {
          selectedMCPServer.value = null;
        }
      }
      showToast(`已移除 MCP 服务器 ${id}`, 'info');
    };

    const loadSettings = async () => {
      try {
        const res = await fetch('/api/settings');
        if (res.ok) settings.value = await res.json();
      } catch (e) {
        console.error(e);
      }
    };


    // ==========================================
    // Apps & Process Management Module (本地应用与内存管控)
    // ==========================================
    const apps = ref([]);
    const appsLoading = ref(false);
    const appsSearch = ref('');
    const appsDiskFilter = ref('all');
    const appsDiskMin = ref('');
    const appsDiskMax = ref('');
    const formatDisk = (app) => {
      if (app.disk_bytes == null) return app.disk_status === 'scanning' ? '统计中…' : '无法统计';
      const bytes = app.disk_bytes;
      const unit = bytes >= 1073741824 ? 'GB' : 'MB';
      const value = bytes / (unit === 'GB' ? 1073741824 : 1048576);
      return (app.disk_status === 'partial' ? '≥ ' : '') + value.toFixed(1) + ' ' + unit;
    };
    const appsFilter = ref('all'); // 'all' | 'running' | 'limited'
    const appsViewMode = ref('list'); // 'list' (列表显示) | 'grid' (卡片网格)
    const appsSortBy = ref('memory_mb'); // 'memory_mb' | 'name' | 'cpu_percent' | 'is_running'
    const appsSortOrder = ref('desc'); // 'desc' | 'asc'
    const guardianLogs = ref([]);
    const guardianLogsOpen = ref(false);

    const toggleSort = (field) => {
      if (appsSortBy.value === field) {
        appsSortOrder.value = appsSortOrder.value === 'asc' ? 'desc' : 'asc';
      } else {
        appsSortBy.value = field;
        appsSortOrder.value = (field === 'name' ? 'asc' : 'desc');
      }
    };

    const runningAppsCount = computed(() => {
      return apps.value.filter(a => a.is_running).length;
    });

    const limitedAppsCount = computed(() => {
      return apps.value.filter(a => a.max_memory_mb > 0).length;
    });

    const filteredApps = computed(() => {
      let list = [...apps.value];
      if (appsFilter.value === 'running') {
        list = list.filter(a => a.is_running);
      } else if (appsFilter.value === 'limited') {
        list = list.filter(a => a.max_memory_mb > 0);
      }
      if (appsSearch.value.trim()) {
        const q = appsSearch.value.trim().toLowerCase();
        list = list.filter(a =>
          a.name.toLowerCase().includes(q) ||
          (a.publisher && a.publisher.toLowerCase().includes(q)) ||
          (a.process_names && a.process_names.some(p => p.toLowerCase().includes(q)))
        );
      }

      const diskMode = appsDiskFilter.value;
      if (diskMode === 'unknown') list = list.filter(a => a.disk_status !== 'ready');
      else if (diskMode !== 'all') list = list.filter(a => {
        if (a.disk_status !== 'ready' || a.disk_bytes == null) return false;
        const mb = a.disk_bytes / 1048576;
        if (diskMode === 'small') return mb < 1024;
        if (diskMode === 'medium') return mb >= 1024 && mb < 5120;
        if (diskMode === 'large') return mb >= 5120;
        return (appsDiskMin.value === '' || mb >= Number(appsDiskMin.value)) &&
               (appsDiskMax.value === '' || mb <= Number(appsDiskMax.value));
      });
      // 执行动态排序 (按名称、物理内存、CPU占用或运行状态)
      list.sort((a, b) => {
        let factor = appsSortOrder.value === 'asc' ? 1 : -1;
        if (appsSortBy.value === 'disk_bytes') {
          if (a.disk_bytes == null || b.disk_bytes == null) return (a.disk_bytes == null) - (b.disk_bytes == null);
          return factor * (a.disk_bytes - b.disk_bytes);
        }
        if (appsSortBy.value === 'name') {
          return factor * a.name.localeCompare(b.name, 'zh-CN');
        } else if (appsSortBy.value === 'memory_mb') {
          if (a.memory_mb === b.memory_mb) {
            return (b.is_running ? 1 : 0) - (a.is_running ? 1 : 0);
          }
          return factor * (a.memory_mb - b.memory_mb);
        } else if (appsSortBy.value === 'cpu_percent') {
          return factor * (a.cpu_percent - b.cpu_percent);
        } else if (appsSortBy.value === 'is_running') {
          return factor * ((a.is_running ? 1 : 0) - (b.is_running ? 1 : 0));
        }
        return 0;
      });

      return list;
    });

    const loadApps = async (silent = false) => {
      if (!silent) appsLoading.value = true;
      try {
        const res = await fetch('/api/apps');
        const data = await res.json();
        apps.value = data;
      } catch (e) {
        if (!silent) showToast(`获取应用列表失败: ${e}`, 'error');
      } finally {
        if (!silent) appsLoading.value = false;
      }
    };

    const launchApp = async (appItem) => {
      try {
        showToast(`🚀 正在启动 ${appItem.name}...`, 'info', 2000);
        const res = await fetch('/api/apps/launch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            launch_path: appItem.launch_path,
            app_name: appItem.name
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success');
          setTimeout(() => loadApps(true), 1500);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`启动失败: ${e}`, 'error');
      }
    };

    const killApp = async (appItem) => {
      if (!confirm(`确定要立即杀死/强制结束【${appItem.name}】的所有进程吗？`)) return;
      try {
        showToast(`🛑 正在终止 ${appItem.name} 进程...`, 'info', 1500);
        const res = await fetch('/api/apps/kill', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            process_names: appItem.process_names,
            pids: appItem.pids
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`已成功杀死 ${appItem.name}！`, 'success');
          loadApps(true);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`操作失败: ${e}`, 'error');
      }
    };

    const trimAppMemory = async (appItem) => {
      try {
        showToast(`⚡ 正在对 ${appItem.name} 执行物理工作集压缩...`, 'info', 1500);
        const res = await fetch('/api/apps/trim', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            process_names: appItem.process_names,
            pids: appItem.pids
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success', 4500);
          loadApps(true);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`压缩内存失败: ${e}`, 'error');
      }
    };

    const trimAllAppsMemory = async () => {
      try {
        showToast(`⚡ 正在全盘优化当前所有高内存进程...`, 'info', 2000);
        const res = await fetch('/api/apps/trim_all', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success', 4500);
          loadApps(true);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`优化失败: ${e}`, 'error');
      }
    };

    const openAppDir = async (appItem) => {

      try {

        showToast(`📂 正在定位【${appItem.name}】所在目录...`, 'info', 1500);

        const res = await fetch('/api/apps/open_dir', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({

            install_location: appItem.install_location,

            launch_path: appItem.launch_path,

            process_names: appItem.process_names,

            pids: appItem.pids,

            app_name: appItem.name

          })

        });

        const data = await res.json();

        if (data.success) {

          showToast(data.message, 'success');

        } else {

          showToast(data.message, 'warning');

        }

      } catch (e) {

        showToast(`打开目录失败: ${e}`, 'error');

      }

    };

    const selectedAppPaths = ref([]);
    const canSelectApp = (item) => stats.value.os_family === 'Darwin' && item.source === 'MacBundle' && !item.is_running && item.launch_path && !item.launch_path.startsWith('/System/');
    const selectedApps = computed(() => apps.value.filter(item => selectedAppPaths.value.includes(item.launch_path) && canSelectApp(item)));
    const selectVisibleApps = () => {
      selectedAppPaths.value = [...new Set([...selectedAppPaths.value, ...filteredApps.value.filter(canSelectApp).map(item => item.launch_path)])];
    };
    const uninstallPlan = ref(null);
    const cleanupSize = (bytes) => bytes >= 1024 ** 3 ? (bytes / 1024 ** 3).toFixed(2) + ' GB' : bytes >= 1024 ** 2 ? (bytes / 1024 ** 2).toFixed(1) + ' MB' : (bytes / 1024).toFixed(1) + ' KB';
    const toggleCleanup = (group) => {
      group.selected = group.removeData ? group.items.map(item => item.path) : [];
    };
    const openMacUninstall = async (items) => {
      if (!items.length) return;
      uninstallPlan.value = {groups: items.map(app => ({app, items: [], selected: [], removeData: false, error: '', note: ''})), loading: true, busy: false, done: false, results: []};
      const plan = uninstallPlan.value;
      for (const group of plan.groups) {
        try {
          const res = await fetch('/api/apps/uninstall/preview', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({launch_path: group.app.launch_path})
          });
          const data = await res.json();
          if (!res.ok || !data.success) throw new Error(data.message || data.detail || '扫描失败');
          group.items = data.items;
          group.note = data.note;
        } catch (error) { group.error = String(error); }
      }
      plan.loading = false;
    };
    const confirmMacUninstall = async () => {
      const plan = uninstallPlan.value;
      if (!plan || plan.busy || plan.loading || plan.done || plan.groups.some(group => group.error)) return;
      const names = plan.groups.map(group => group.app.name).join('、');
      const count = plan.groups.reduce((sum, group) => sum + (group.removeData ? group.selected.length : 0), 0);
      if (!confirm(`最后确认：将 ${plan.groups.length} 个应用（${names}）及 ${count} 项关联数据移入废纸篓？`)) return;
      plan.busy = true;
      for (const group of plan.groups) {
        try {
          const res = await fetch('/api/apps/uninstall', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({app_name: group.app.name, launch_path: group.app.launch_path,
              cleanup_paths: group.removeData ? group.selected : []})
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || '卸载失败');
          plan.results.push({name: group.app.name, success: data.success, message: data.message,
            failed: data.failed_paths || []});
          if (data.app_removed) selectedAppPaths.value = selectedAppPaths.value.filter(path => path !== group.app.launch_path);
        } catch (error) {
          plan.results.push({name: group.app.name, success: false, message: String(error), failed: []});
        }
      }
      plan.busy = false;
      plan.done = true;
      await loadApps(true);
    };

    const uninstallApp = async (appItem) => {
      const isMac = stats.value.os_family === 'Darwin';
      if (isMac && appItem.is_running) {
        showToast('请先退出应用后再卸载。', 'error');
        return;
      }
      if (isMac) {
        await openMacUninstall([appItem]);
        return;
      }
      const message = isMac
        ? `确定将【${appItem.name}】移入废纸篓吗？\n可以从废纸篓恢复，应用数据和缓存将保留。`
        : `⚠️ 确定要卸载应用【${appItem.name}】吗？\n系统将拉起该应用的官方卸载向导。`;
      if (!confirm(message)) return;
      try {
        showToast(isMac ? `正在将【${appItem.name}】移入废纸篓…` : `正在拉起【${appItem.name}】卸载向导…`, 'info', 2500);
        const res = await fetch('/api/apps/uninstall', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_name: appItem.name,
            uninstall_string: appItem.uninstall_string,
            launch_path: appItem.launch_path
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success', 5000);
          setTimeout(() => loadApps(true), 3000);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`卸载操作失败: ${e}`, 'error');
      }
    };

    // 内存限制配额模态框
    const memoryModalOpen = ref(false);
    const memoryModalForm = ref({
      app_id: '',
      name: '',
      max_memory_mb: 800,
      action: 'trim',
      process_names: [],
      enabled: true
    });

    const openMemoryModal = (appItem) => {
      memoryModalForm.value = {
        app_id: appItem.id,
        name: appItem.name,
        max_memory_mb: appItem.max_memory_mb || 800,
        action: appItem.memory_action || 'trim',
        process_names: appItem.process_names || [],
        enabled: true
      };
      memoryModalOpen.value = true;
    };

    const setQuickMemory = (mb) => {
      memoryModalForm.value.max_memory_mb = mb;
    };

    const saveMemoryLimit = async () => {
      try {
        const res = await fetch('/api/apps/rules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(memoryModalForm.value)
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success');
          memoryModalOpen.value = false;
          loadApps(true);
        } else {
          showToast(data.message || '保存失败', 'error');
        }
      } catch (e) {
        showToast(`保存出错: ${e}`, 'error');
      }
    };

    const removeMemoryLimit = async (formItem) => {
      try {
        const res = await fetch(`/api/apps/rules/${encodeURIComponent(formItem.app_id)}`, {
          method: 'DELETE'
        });
        const data = await res.json();
        if (data.success) {
          showToast(`已解除 ${formItem.name} 的内存限制`, 'info');
          memoryModalOpen.value = false;
          loadApps(true);
        }
      } catch (e) {
        showToast(`删除规则失败: ${e}`, 'error');
      }
    };

    // Winget 在线软件搜索与安装
    const onlineInstallModalOpen = ref(false);
    const onlineSearchQuery = ref('');
    const onlineSearchResults = ref([]);
    const onlineSearching = ref(false);
    const installingMap = ref({});

    const openOnlineInstallModal = () => {
      onlineInstallModalOpen.value = true;
      if (!onlineSearchResults.value.length) {
        onlineSearchQuery.value = 'douyin';
        searchOnlineApps();
      }
    };

    const searchOnlineApps = async () => {
      if (!onlineSearchQuery.value.trim()) return;
      onlineSearching.value = true;
      try {
        const res = await fetch(`/api/apps/search_online?query=${encodeURIComponent(onlineSearchQuery.value.trim())}`);
        const data = await res.json();
        onlineSearchResults.value = data;
      } catch (e) {
        showToast(`搜索在线软件失败: ${e}`, 'error');
      } finally {
        onlineSearching.value = false;
      }
    };

    const installOnlineApp = async (pkg) => {
      if (!pkg.id) return;
      installingMap.value[pkg.id] = true;
      showToast(`📦 正在通过 Winget 静默安装: ${pkg.name}...`, 'info', 3000);
      try {
        const res = await fetch('/api/apps/install_online', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ package_id: pkg.id })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success', 5000);
        } else {
          showToast(data.message, 'error');
        }
      } catch (e) {
        showToast(`安装出错: ${e}`, 'error');
      } finally {
        setTimeout(() => {
          installingMap.value[pkg.id] = false;
        }, 5000);
      }
    };

    const loadGuardianLogs = async () => {
      try {
        const res = await fetch('/api/apps/guardian_logs');
        guardianLogs.value = await res.json();
      } catch (e) {}
    };

    onMounted(async () => {
      await Promise.all([
        fetchOmniHubProject(),
        fetchStats(),
        fetchServices(),
        fetchMCPServers(),
        fetchMCPTools(),
        loadSettings(),
        loadApps(true),
        loadGuardianLogs()
      ]);

      pollInterval = setInterval(async () => {
        await fetchStats();
        await fetchServices();
        if (currentTab.value === 'apps') {
          await loadApps(true);
          await loadGuardianLogs();
        }
      }, 3000);
    });

    onUnmounted(() => {
      if (pollInterval) clearInterval(pollInterval);
      if (logWs) logWs.close();
    });

    return {
      currentTab,
      toasts,
      showToast,
      omnihubProject,
      copyText,
      revealService,
      stats,
      services,
      serviceFilter,
      filteredServices,
      actionLoading,
      logsModalOpen,
      activeLogService,
      logLines,
      openLogs,
      closeLogs,
      startService,
      stopService,
      restartService,
      deleteService,
      editServiceModalOpen,
      editServiceForm,
      openEditService,
      saveEditService,
      mcpServers,
      mcpToolsMap,
      selectedMCPServer,
      selectedTool,
      toolArgs,
      toolCallLoading,
      toolCallResult,
      selectMCPServer,
      selectTool,
      executeTool,
      saveNewMCP,
      deleteMCPServer,
      workspaceServices,
      currentWorkspaceId,
      currentWorkspaceService,
      openInWorkspace,
      isQwenRunning,
      aiMessages,
      aiInput,
      aiLoading,
      enableAITools,
      sendChatMessage,
      settings,
      loadSettings,
      newServiceModalOpen,
      newServiceForm,
      saveNewService,
      newMCPModalOpen,
      newMCPForm,
      apps,
      appsLoading,
      appsSearch,
      appsFilter,
      appsDiskFilter, appsDiskMin, appsDiskMax, formatDisk,
      runningAppsCount,
      limitedAppsCount,
      filteredApps,
      loadApps,
      launchApp,
      killApp,
      trimAppMemory,
      trimAllAppsMemory,
      memoryModalOpen,
      memoryModalForm,
      openMemoryModal,
      setQuickMemory,
      saveMemoryLimit,
      removeMemoryLimit,
      onlineInstallModalOpen,
      onlineSearchQuery,
      onlineSearchResults,
      onlineSearching,
      installingMap,
      openOnlineInstallModal,
      searchOnlineApps,
      installOnlineApp,
      guardianLogs,
      guardianLogsOpen,
      appsViewMode,
      appsSortBy,
      appsSortOrder,
      toggleSort,
      openAppDir,
      uninstallApp, uninstallPlan, cleanupSize, toggleCleanup, confirmMacUninstall, selectedAppPaths, selectedApps, canSelectApp, selectVisibleApps, openMacUninstall
    };
  }
});

app.mount('#app');
