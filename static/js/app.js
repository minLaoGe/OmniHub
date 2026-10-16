const { createApp, ref, computed, onMounted, onUnmounted, nextTick } = Vue;

const app = createApp({
  setup() {
    // Current Active View
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab') || 'dashboard';
    const currentTab = ref(initialTab);

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
          services.value = await res.json();
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
      if (s) s.status = 'STARTING';
      try {
        const res = await fetch(`/api/services/${id}/start`, { method: 'POST' });
        const data = await res.json();
        await fetchServices();

        // 延迟 1.5 秒二次确认是否成功运行，如果异常退出则自动弹出错误日志
        setTimeout(async () => {
          await fetchServices();
          const updated = services.value.find(item => item.id === id);
          if (updated && updated.status === 'ERROR') {
            openLogs(updated);
          }
        }, 1500);

        return data;
      } catch (e) {
        alert("启动服务请求失败: " + e);
      }
    };

    const stopService = async (id) => {
      try {
        const res = await fetch(`/api/services/${id}/stop`, { method: 'POST' });
        await fetchServices();
      } catch (e) {
        alert("停止服务失败: " + e);
      }
    };

    const restartService = async (id) => {
      try {
        await fetch(`/api/services/${id}/restart`, { method: 'POST' });
        await fetchServices();
      } catch (e) {
        alert("重启服务失败: " + e);
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
        alert("请输入有效的端口号！");
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
        } else {
          alert("保存修改失败");
        }
      } catch (e) {
        alert("请求异常: " + e);
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
        if (selectedTool.value.name.startsWith('omnihub_')) {
          await fetchServices();
        }
      } catch (e) {
        toolCallResult.value = { success: false, error: String(e) };
      } finally {
        toolCallLoading.value = false;
      }
    };

    const openInWorkspace = (service) => {
      currentWorkspaceId.value = service.id;
      currentTab.value = 'workspace';
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
              if (chunk.type === 'message') {
                assistantMsg.content += chunk.content;
              } else if (chunk.type === 'tool_call_start') {
                assistantMsg.tool_calls.push({
                  server_id: chunk.server_id,
                  tool_name: chunk.tool_name,
                  arguments: chunk.arguments,
                  status: 'running'
                });
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
              }
            } catch (err) {
              console.error("Parse line error:", err, line);
            }
          }
        }
      } catch (e) {
        assistantMsg.content += `\n> ⚠️ 发送消息发生网络异常: ${e}`;
      } finally {
        aiLoading.value = false;
        fetchServices();
      }
    };

    const saveNewService = async () => {
      const form = newServiceForm.value;
      if (!form.id || !form.name || !form.command) {
        alert("请完整填写必填字段！");
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
      }
    };

    const deleteService = async (id) => {
      if (!confirm(`确定要移除服务 ${id} 吗？`)) return;
      await fetch(`/api/services/${id}`, { method: 'DELETE' });
      await fetchServices();
    };

    const saveNewMCP = async () => {
      const form = newMCPForm.value;
      if (!form.id || !form.name || !form.command) {
        alert("请完整填写必填字段！");
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
      }
    };

    const deleteMCPServer = async (id) => {
      if (!confirm(`确定要移除 MCP 服务器 ${id} 吗？`)) return;
      await fetch(`/api/mcp/servers/${id}`, { method: 'DELETE' });
      await fetchMCPServers();
      await fetchMCPTools();
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
      stats,
      services,
      serviceFilter,
      filteredServices,
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
