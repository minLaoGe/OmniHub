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

    // --- Methods ---
    const fetchStats = async () => {
      try {
        const res = await fetch('/api/system/stats');
        if (res.ok) {
          stats.value = await res.json();
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

    onMounted(async () => {
      await Promise.all([
        fetchStats(),
        fetchServices(),
        fetchMCPServers(),
        fetchMCPTools(),
        loadSettings()
      ]);

      pollInterval = setInterval(async () => {
        await fetchStats();
        await fetchServices();
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
      newMCPForm
    };
  }
});

app.mount('#app');
