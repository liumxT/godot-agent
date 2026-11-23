"""管理界面（E4-T23 / E6-T18）。

以单页 HTML 形式提供项目、任务、Workflow、审批、工具、模型与 Agent 运行监控入口。
页面本身不含任何凭证；用户在页面内输入 Access Token 或 Session Token，
之后所有数据访问都通过 ``/api/v1`` 受保护接口完成。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["management"])


@router.get(
    "/manage",
    summary="管理界面",
    description="返回项目管理单页；数据通过 /api/v1 受保护接口按用户输入的 Token 读取。",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}}},
)
async def management_page() -> HTMLResponse:
    return HTMLResponse(_PAGE)


_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>Godot AI Agent 管理</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #14161a;
    --panel: #1d2026;
    --line: #2c313a;
    --text: #e6e8ec;
    --muted: #9aa1ad;
    --accent: #4f8cff;
    --ok: #3fb950;
    --warn: #d29922;
    --err: #f85149;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 "Segoe UI", sans-serif; }
  header { padding: 16px 20px; border-bottom: 1px solid var(--line); display: flex; gap: 12px; align-items: center; }
  header h1 { font-size: 16px; margin: 0 12px 0 0; }
  input[type=password], input[type=text] { background: var(--panel); border: 1px solid var(--line); color: var(--text); padding: 6px 10px; border-radius: 6px; }
  input[type=password] { width: 320px; }
  button { background: var(--panel); color: var(--text); border: 1px solid var(--line); padding: 5px 10px; border-radius: 6px; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button.primary { border-color: var(--accent); }
  main { display: grid; grid-template-columns: 280px 1fr; min-height: calc(100vh - 62px); }
  aside { border-right: 1px solid var(--line); padding: 14px; }
  section { padding: 14px 18px; }
  h2 { font-size: 14px; color: var(--muted); margin: 18px 0 8px; text-transform: uppercase; letter-spacing: .04em; }
  h2:first-child { margin-top: 0; }
  .project { padding: 8px 10px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
  .project:hover { border-color: var(--line); }
  .project.active { border-color: var(--accent); background: var(--panel); }
  .project small { display: block; color: var(--muted); }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 500; }
  .actions { display: flex; flex-wrap: wrap; gap: 4px; }
  .pill { display: inline-block; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--line); font-size: 12px; }
  .pill.ok { color: var(--ok); border-color: var(--ok); }
  .pill.warn { color: var(--warn); border-color: var(--warn); }
  .pill.err { color: var(--err); border-color: var(--err); }
  .muted { color: var(--muted); }
  .banner { margin: 10px 18px 0; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--err); color: var(--err); display: none; }
  .empty { color: var(--muted); padding: 10px 0; }
  details { margin-top: 6px; }
  pre { background: var(--panel); border: 1px solid var(--line); padding: 10px; border-radius: 6px; overflow: auto; max-height: 280px; }
</style>
</head>
<body>
<header>
  <h1>Godot AI Agent 管理</h1>
  <input id="token" type="password" placeholder="Access Token (gda_) 或 Session Token (gds_)" />
  <button class="primary" id="connect">加载项目</button>
  <button id="refresh">刷新</button>
  <span class="muted" id="who">未连接</span>
</header>
<div class="banner" id="banner"></div>
<main>
  <aside>
    <h2>项目</h2>
    <div id="projects" class="empty">输入 Token 后加载</div>
  </aside>
  <section>
    <h2>项目详情</h2>
    <div id="project-detail" class="empty">未选择项目</div>
    <h2>任务</h2>
    <div id="tasks" class="empty">未选择项目</div>
    <h2>待处理审批</h2>
    <div id="approvals" class="empty">未选择项目</div>
    <h2>工具</h2>
    <div id="tools" class="empty">未选择项目</div>
    <h2>工具执行</h2>
    <div id="executions" class="empty">未选择项目</div>
    <h2>模型</h2>
    <div id="models" class="empty">未选择项目</div>
    <h2>Agent 概览</h2>
    <div id="agent-metrics" class="empty">未选择项目</div>
    <h2>Agent 实例</h2>
    <div id="agent-instances" class="empty">未选择项目</div>
    <h2>Agent 执行监控</h2>
    <div id="agent-executions" class="empty">选择实例后查看</div>
    <h2>Agent 预算</h2>
    <div id="agent-budget" class="empty">未选择项目</div>
    <h2>Multi-Agent Team</h2>
    <div id="multi-agent-teams" class="empty">未选择项目</div>
    <h2>Agent Team 详情</h2>
    <div id="multi-agent-detail" class="empty">选择 Team 后查看</div>
    <h2>Agent 能力</h2>
    <div id="agent-capabilities" class="empty">未选择项目</div>
    <h2>恢复监控</h2>
    <div id="agent-recovery" class="empty">未选择项目</div>
  </section>
</main>
<script>
(() => {
  const state = { token: sessionStorage.getItem("godot_ai_token") || "", projectId: "" };
  const base = window.location.origin + "/api/v1";
  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(message) {
    const banner = $("banner");
    banner.textContent = message || "";
    banner.style.display = message ? "block" : "none";
  }

  async function api(path, options = {}) {
    if (!state.token) throw new Error("请先输入 Token");
    const response = await fetch(base + path, {
      ...options,
      headers: {
        "Authorization": "Bearer " + state.token,
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    if (response.status === 204) return null;
    const text = await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch (_) { body = text; }
    if (!response.ok) {
      const detail = body && body.error ? body.error.message : (body ? body.detail : "");
      throw new Error(`${response.status} ${detail || response.statusText}`);
    }
    return body;
  }

  function statusClass(status) {
    if (["ACTIVE", "COMPLETED", "APPLIED", "APPROVED", "SUCCEEDED", "READY"].includes(status)) return "ok";
    if (["FAILED", "REJECTED", "EXPIRED", "CANCELLED", "BLOCKED", "UNKNOWN"].includes(status)) return "err";
    return "warn";
  }

  async function loadProjects() {
    const data = await api("/projects?limit=100");
    const items = data.items || [];
    if (!items.length) {
      $("projects").className = "empty";
      $("projects").textContent = "暂无项目";
      return;
    }
    $("projects").className = "";
    $("projects").innerHTML = items.map((project) => `
      <div class="project ${project.project_id === state.projectId ? "active" : ""}" data-id="${esc(project.project_id)}">
        ${esc(project.name || project.project_id)}
        <small>${esc(project.status)} · ${esc(project.project_id)}</small>
      </div>`).join("");
    $("projects").querySelectorAll(".project").forEach((node) => {
      node.addEventListener("click", () => selectProject(node.dataset.id));
    });
    if (!state.projectId || !items.some((project) => project.project_id === state.projectId)) {
      await selectProject(items[0].project_id);
    }
  }

  async function selectProject(projectId) {
    state.projectId = projectId;
    await Promise.all([
      loadDetail(), loadTasks(), loadApprovals(), loadTools(), loadExecutions(), loadModels(),
      loadAgents(), loadMultiAgent()
    ]);
    await loadProjects();
  }

  async function loadDetail() {
    if (!state.projectId) return;
    const project = await api(`/projects/${state.projectId}`);
    let config = null;
    try { config = await api(`/projects/${state.projectId}/configuration`); } catch (_) {}
    $("project-detail").className = "";
    $("project-detail").innerHTML = `
      <table>
        <tr><th>名称</th><td>${esc(project.name)}</td></tr>
        <tr><th>标识</th><td>${esc(project.project_id)}</td></tr>
        <tr><th>状态</th><td><span class="pill ${statusClass(project.status)}">${esc(project.status)}</span></td></tr>
        <tr><th>根目录</th><td>${esc(project.project_root)}</td></tr>
        <tr><th>类型</th><td>${esc(project.project_type)} · Godot ${esc(project.godot_version)}</td></tr>
        <tr><th>配置</th><td><details><summary>展开</summary><pre>${esc(JSON.stringify(config, null, 2))}</pre></details></td></tr>
      </table>`;
  }

  async function loadTasks() {
    if (!state.projectId) return;
    const data = await api(`/projects/${state.projectId}/tasks?limit=100`);
    const items = data.items || [];
    if (!items.length) {
      $("tasks").className = "empty";
      $("tasks").textContent = "暂无任务";
      return;
    }
    $("tasks").className = "";
    $("tasks").innerHTML = `
      <table>
        <thead><tr><th>任务</th><th>状态</th><th>优先级</th><th>Workflow</th><th>操作</th></tr></thead>
        <tbody>${items.map(taskRow).join("")}</tbody>
      </table>`;
    $("tasks").querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => runTaskAction(button.dataset.id, button.dataset.action));
    });
    $("tasks").querySelectorAll("button[data-workflow]").forEach((button) => {
      button.addEventListener("click", () => showWorkflow(button.dataset.workflow, button.dataset.id));
    });
  }

  function taskRow(task) {
    const running = ["CREATED", "READY", "QUEUED", "RUNNING", "PAUSING", "RESUMING"].includes(task.status);
    const paused = task.status === "PAUSED";
    const review = task.status === "REVIEW_PENDING";
    const retry = ["FAILED", "NEEDS_REVISION", "REJECTED"].includes(task.status);
    const buttons = [];
    if (running || paused) {
      buttons.push(`<button data-action="pause" data-id="${esc(task.task_id)}" ${paused ? "disabled" : ""}>暂停</button>`);
      buttons.push(`<button data-action="cancel" data-id="${esc(task.task_id)}">取消</button>`);
    }
    if (paused) buttons.push(`<button data-action="resume" data-id="${esc(task.task_id)}">恢复</button>`);
    if (review) {
      buttons.push(`<button class="primary" data-action="accept" data-id="${esc(task.task_id)}">验收通过</button>`);
      buttons.push(`<button data-action="reject" data-id="${esc(task.task_id)}">驳回</button>`);
    }
    if (retry) buttons.push(`<button data-action="retry" data-id="${esc(task.task_id)}">重试</button>`);
    const workflow = task.workflow_instance_id
      ? `<button data-workflow="${esc(task.workflow_instance_id)}" data-id="${esc(task.task_id)}">查看</button>`
      : `<span class="muted">无</span>`;
    return `<tr>
      <td>${esc(task.title)}<br /><small class="muted">${esc(task.task_id)}</small></td>
      <td><span class="pill ${statusClass(task.status)}">${esc(task.status)}</span></td>
      <td>${esc(task.priority)}</td>
      <td>${workflow}</td>
      <td><div class="actions">${buttons.join("") || '<span class="muted">-</span>'}</div></td>
    </tr>`;
  }

  async function runTaskAction(taskId, action) {
    showError("");
    try {
      const options = { method: "POST" };
      if (action === "reject") {
        const reason = window.prompt("驳回原因", "需要修改");
        if (reason === null) return;
        options.body = JSON.stringify({ reason });
      }
      await api(`/tasks/${taskId}/${action}`, options);
      await loadTasks();
    } catch (error) {
      showError(`任务操作失败：${error.message}`);
    }
  }

  async function showWorkflow(instanceId, taskId) {
    showError("");
    try {
      const instance = await api(`/workflows/${instanceId}`);
      const nodes = await api(`/workflows/${instanceId}/nodes`);
      const phases = await api(`/workflows/${instanceId}/phases`);
      const task = await api(`/tasks/${taskId}`);
      const rows = (nodes.items || []).map((node) => `
        <tr><td>${esc(node.node_key)}</td><td>${esc(node.node_type)}</td>
        <td><span class="pill ${statusClass(node.status)}">${esc(node.status)}</span></td></tr>`).join("");
      const phaseRows = (phases.items || []).map((phase) => `
        <tr><td>${esc(phase.phase_key)}</td><td>${esc(phase.name)}</td>
        <td><span class="pill ${statusClass(phase.status)}">${esc(phase.status)}</span></td></tr>`).join("");
      const detail = $("project-detail");
      detail.className = "";
      detail.innerHTML = `
        <div class="muted">任务 ${esc(task.title)} · 实例 ${esc(instance.instance_id)} · 状态
          <span class="pill ${statusClass(instance.status)}">${esc(instance.status)}</span></div>
        <h2>节点</h2><table><thead><tr><th>节点</th><th>类型</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table>
        <h2>阶段</h2><table><thead><tr><th>阶段</th><th>名称</th><th>状态</th></tr></thead><tbody>${phaseRows}</tbody></table>`;
    } catch (error) {
      showError(`读取 Workflow 失败：${error.message}`);
    }
  }

  async function loadApprovals() {
    if (!state.projectId) return;
    const data = await api(`/approvals?project_id=${encodeURIComponent(state.projectId)}&status=PENDING&limit=100`);
    const items = data.items || [];
    if (!items.length) {
      $("approvals").className = "empty";
      $("approvals").textContent = "没有待处理审批";
      return;
    }
    $("approvals").className = "";
    $("approvals").innerHTML = `
      <table>
        <thead><tr><th>类型</th><th>目标</th><th>哈希</th><th>过期时间</th><th>操作</th></tr></thead>
        <tbody>${items.map((approval) => `
          <tr>
            <td>${esc(approval.approval_type)}</td>
            <td>${esc(approval.target_id)}<br /><small class="muted">${esc(approval.target_type)}</small></td>
            <td><small class="muted">${esc(String(approval.target_hash || "").slice(0, 16))}…</small></td>
            <td>${esc(approval.expires_at)}</td>
            <td><div class="actions">
              <button class="primary" data-approve="${esc(approval.approval_id)}">批准</button>
              <button data-reject="${esc(approval.approval_id)}">拒绝</button>
            </div></td>
          </tr>`).join("")}</tbody>
      </table>`;
    $("approvals").querySelectorAll("button[data-approve]").forEach((button) => {
      button.addEventListener("click", () => decide(button.dataset.approve, "approve"));
    });
    $("approvals").querySelectorAll("button[data-reject]").forEach((button) => {
      button.addEventListener("click", () => decide(button.dataset.reject, "reject"));
    });
  }

  async function decide(approvalId, action) {
    showError("");
    try {
      const reason = window.prompt("审批备注（可留空）", "");
      if (reason === null) return;
      await api(`/approvals/${approvalId}/${action}`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await loadApprovals();
    } catch (error) {
      showError(`审批操作失败：${error.message}`);
    }
  }

  async function loadTools() {
    if (!state.projectId) return;
    const query = `?project_id=${encodeURIComponent(state.projectId)}&limit=200`;
    const data = await api(`/tools${query}`);
    const items = data.items || [];
    if (!items.length) {
      $("tools").className = "empty";
      $("tools").textContent = "暂无工具";
      return;
    }
    $("tools").className = "";
    $("tools").innerHTML = `
      <table>
        <thead><tr><th>工具</th><th>分类</th><th>风险</th><th>版本</th><th>状态</th></tr></thead>
        <tbody>${items.map((tool) => `
          <tr>
            <td>${esc(tool.name)}<br /><small class="muted">${esc(tool.tool_id)}</small></td>
            <td>${esc(tool.category)}</td>
            <td><span class="pill ${tool.risk_level === "R0" ? "ok" : "warn"}">${esc(tool.risk_level)}</span></td>
            <td>v${esc(tool.version)}</td>
            <td>${tool.enabled ? '<span class="pill ok">启用</span>' : '<span class="pill err">停用</span>'}</td>
          </tr>`).join("")}</tbody>
      </table>`;
  }

  async function loadExecutions() {
    if (!state.projectId) return;
    const query = `?project_id=${encodeURIComponent(state.projectId)}&limit=50`;
    const data = await api(`/tool-executions${query}`);
    const items = data.items || [];
    if (!items.length) {
      $("executions").className = "empty";
      $("executions").textContent = "暂无工具执行";
      return;
    }
    $("executions").className = "";
    $("executions").innerHTML = `
      <table>
        <thead><tr><th>执行</th><th>工具</th><th>状态</th><th>验证</th><th>时间</th></tr></thead>
        <tbody>${items.map((item) => `
          <tr>
            <td>${esc(item.execution_id)}</td>
            <td>${esc(item.tool_name)} v${esc(item.tool_version)}<br /><small class="muted">${esc(item.risk_level)}</small></td>
            <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td>
            <td>${esc(item.verification_status)}</td>
            <td><small class="muted">${esc(item.created_at)}</small></td>
          </tr>`).join("")}</tbody>
      </table>`;
  }

  async function loadModels() {
    if (!state.projectId) return;
    const query = `?project_id=${encodeURIComponent(state.projectId)}`;
    try {
      const data = await api(`/models${query}`);
      const usage = await api(`/model-usage${query}`);
      const cost = await api(`/model-cost${query}`);
      const items = data.items || [];
      const rows = items.map((model) => `
        <tr>
          <td>${esc(model.model_key)}<br /><small class="muted">${esc(model.model_id)}</small></td>
          <td>${esc(model.context_window)}</td>
          <td><span class="pill ${statusClass(model.status)}">${esc(model.status)}</span></td>
        </tr>`).join("");
      $("models").className = "";
      $("models").innerHTML = `
        <div class="muted">Token：${esc(usage.total_tokens)}（输入 ${esc(usage.input_tokens)} / 输出 ${esc(usage.output_tokens)}）
          · 费用：${esc(cost.total_cost)} ${esc((cost.currencies || []).join(", "))}</div>
        <table>
          <thead><tr><th>模型</th><th>上下文</th><th>状态</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="3" class="empty">暂无模型</td></tr>'}</tbody>
        </table>`;
    } catch (error) {
      $("models").className = "empty";
      $("models").textContent = `模型信息不可用：${error.message}`;
    }
  }

  function pct(value) {
    return `${(Number(value || 0) * 100).toFixed(1)}%`;
  }

  async function loadAgents() {
    if (!state.projectId) return;
    try {
      const query = `?project_id=${encodeURIComponent(state.projectId)}`;
      const metrics = await api(`/agents/metrics${query}`);
      $("agent-metrics").className = "";
      $("agent-metrics").innerHTML = `<div class="muted">实例 ${esc(metrics.agent_instance_count)} · 运行中执行 ${esc(metrics.running_execution_count)} · 平均迭代 ${esc(Number(metrics.average_iterations).toFixed(1))} · 失败率 ${esc(pct(metrics.failure_rate))} · 恢复成功率 ${esc(pct(metrics.recovery_success_rate))} · UNKNOWN ${esc(metrics.unknown_count)}</div>`;
      $("agent-budget").className = "";
      $("agent-budget").innerHTML = `<div class="muted">Token ${esc(metrics.total_tokens)}（输入 ${esc(metrics.input_tokens)} / 输出 ${esc(metrics.output_tokens)}）· 成本 ${esc(metrics.cost_total)} · 模型调用 ${esc(metrics.model_call_count)} · 工具调用 ${esc(metrics.tool_call_count)} · 重试 ${esc(metrics.retry_count)} · 等待审批 ${esc(metrics.approval_waiting_count)}</div>`;

      const data = await api(`/agents/instances${query}&limit=100`);
      const items = data.items || [];
      if (!items.length) {
        $("agent-instances").className = "empty";
        $("agent-instances").textContent = "暂无 Agent 实例";
        $("agent-recovery").className = "empty";
        $("agent-recovery").textContent = "暂无需要关注的实例";
        return;
      }
      $("agent-instances").className = "";
      $("agent-instances").innerHTML = `
        <table>
          <thead><tr><th>实例</th><th>状态</th><th>Task</th><th>操作</th></tr></thead>
          <tbody>${items.map((item) => `
            <tr>
              <td>${esc(item.instance_id)}<br /><small class="muted">${esc(item.agent_definition_id)} v${esc(item.agent_version)}</small></td>
              <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td>
              <td><small class="muted">${esc(item.task_id || "-")}</small></td>
              <td><div class="actions">
                <button data-agent-view="${esc(item.instance_id)}">执行</button>
                ${agentButtons(item)}
              </div></td>
            </tr>`).join("")}</tbody>
        </table>`;
      $("agent-instances").querySelectorAll("button[data-agent-view]").forEach((button) => {
        button.addEventListener("click", () => showAgentExecution(button.dataset.agentView));
      });
      $("agent-instances").querySelectorAll("button[data-agent-action]").forEach((button) => {
        button.addEventListener("click", () => runAgentAction(button.dataset.agentAction, button.dataset.id));
      });

      const attention = items.filter((item) => ["UNKNOWN", "PAUSED", "FAILED", "WAITING_APPROVAL"].includes(item.status));
      if (!attention.length) {
        $("agent-recovery").className = "empty";
        $("agent-recovery").textContent = "暂无需要关注的实例";
      } else {
        $("agent-recovery").className = "";
        $("agent-recovery").innerHTML = `
          <table>
            <thead><tr><th>实例</th><th>状态</th><th>原因</th></tr></thead>
            <tbody>${attention.map((item) => `
              <tr><td>${esc(item.instance_id)}</td>
              <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td>
              <td>${esc(item.termination_reason || (item.status === "PAUSED" ? "等待恢复" : "需要人工确认"))}</td></tr>`).join("")}</tbody>
          </table>`;
      }
    } catch (error) {
      showError(`读取 Agent 失败：${error.message}`);
    }
  }

  function agentButtons(item) {
    const buttons = [];
    if (["CREATED", "READY"].includes(item.status)) {
      buttons.push(`<button class="primary" data-agent-action="start" data-id="${esc(item.instance_id)}">启动</button>`);
    }
    if (["RUNNING", "WAITING_TOOL", "WAITING_APPROVAL", "WAITING_INPUT"].includes(item.status)) {
      buttons.push(`<button data-agent-action="pause" data-id="${esc(item.instance_id)}">暂停</button>`);
    }
    if (item.status === "PAUSED") {
      buttons.push(`<button class="primary" data-agent-action="resume" data-id="${esc(item.instance_id)}">恢复</button>`);
    }
    if (!["STOPPED", "COMPLETED", "FAILED"].includes(item.status)) {
      buttons.push(`<button data-agent-action="stop" data-id="${esc(item.instance_id)}">停止</button>`);
    }
    return buttons.join("");
  }

  async function runAgentAction(action, instanceId) {
    showError("");
    try {
      await api(`/agents/instances/${encodeURIComponent(instanceId)}/${action}`, {
        method: "POST",
        body: "{}",
      });
      await loadAgents();
    } catch (error) {
      showError(`Agent 操作失败：${error.message}`);
    }
  }

  async function showAgentExecution(instanceId) {
    showError("");
    try {
      const executions = (await api(`/agents/instances/${encodeURIComponent(instanceId)}/executions`)).items || [];
      const container = $("agent-executions");
      if (!executions.length) {
        container.className = "empty";
        container.textContent = "该实例暂无执行记录";
        return;
      }
      const latest = executions[executions.length - 1];
      const plan = await api(`/agents/executions/${encodeURIComponent(latest.execution_id)}/plan`).catch(() => null);
      const trace = await api(`/agents/executions/${encodeURIComponent(latest.execution_id)}/trace`).catch(() => null);
      const executionRows = executions.map((execution) => `
        <tr>
          <td>${esc(execution.execution_id)}<br /><small class="muted">#${esc(execution.execution_number)}</small></td>
          <td><span class="pill ${statusClass(execution.status)}">${esc(execution.status)}</span></td>
          <td>${esc((execution.budget_usage || {}).iterations || 0)} / ${esc((execution.budget_usage || {}).model_calls || 0)} / ${esc((execution.budget_usage || {}).tool_calls || 0)}</td>
          <td>${esc(execution.termination_reason || "-")}</td>
        </tr>`).join("");
      const stepRows = plan ? (plan.steps || []).map((step) => `
        <tr><td>#${esc(step.step_number)}</td><td>${esc(step.step_type)}</td><td>${esc(step.description)}</td>
        <td><span class="pill ${statusClass(step.status)}">${esc(step.status)}</span></td></tr>`).join("") : "";
      container.className = "";
      container.innerHTML = `
        <table>
          <thead><tr><th>执行</th><th>状态</th><th>迭代 / 模型 / 工具</th><th>结束原因</th></tr></thead>
          <tbody>${executionRows}</tbody>
        </table>
        <h2>计划步骤</h2>
        <table>
          <thead><tr><th>#</th><th>类型</th><th>描述</th><th>状态</th></tr></thead>
          <tbody>${stepRows || '<tr><td colspan="4" class="empty">暂无计划</td></tr>'}</tbody>
        </table>
        <details><summary>追踪（脱敏）</summary><pre>${esc(JSON.stringify(trace, null, 2))}</pre></details>`;
    } catch (error) {
      showError(`读取执行监控失败：${error.message}`);
    }
  }

  async function loadMultiAgent() {
    if (!state.projectId) return;
    try {
      const query = `?project_id=${encodeURIComponent(state.projectId)}`;
      const teams = (await api(`/agent-teams${query}&limit=50`)).items || [];
      const capabilities = (await api(`/agent-capabilities${query}&limit=200`)).items || [];
      $("agent-capabilities").className = capabilities.length ? "" : "empty";
      $("agent-capabilities").innerHTML = capabilities.length
        ? `<table><thead><tr><th>能力</th><th>分类</th><th>说明</th></tr></thead><tbody>${capabilities.map((item) => `
            <tr><td>${esc(item.name)}</td><td>${esc(item.category)}</td><td>${esc(item.description)}</td></tr>`).join("")}</tbody></table>`
        : "暂无能力";
      if (!teams.length) {
        $("multi-agent-teams").className = "empty";
        $("multi-agent-teams").textContent = "暂无 Agent Team";
        $("multi-agent-detail").className = "empty";
        $("multi-agent-detail").textContent = "选择 Team 后查看";
        return;
      }
      $("multi-agent-teams").className = "";
      $("multi-agent-teams").innerHTML = `
        <table>
          <thead><tr><th>Team</th><th>Task</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${teams.map((team) => `
            <tr>
              <td>${esc(team.team_id)}<br /><small class="muted">${esc(team.project_id)}</small></td>
              <td><small class="muted">${esc(team.task_id)}</small></td>
              <td><span class="pill ${statusClass(team.status)}">${esc(team.status)}</span></td>
              <td><div class="actions"><button data-team-view="${esc(team.team_id)}">查看</button></div></td>
            </tr>`).join("")}</tbody>
        </table>`;
      $("multi-agent-teams").querySelectorAll("button[data-team-view]").forEach((button) => {
        button.addEventListener("click", () => showMultiAgentTeam(button.dataset.teamView));
      });
    } catch (error) {
      showError(`读取 Multi-Agent 失败：${error.message}`);
    }
  }

  async function showMultiAgentTeam(teamId) {
    showError("");
    try {
      const dashboard = await api(`/agent-teams/${encodeURIComponent(teamId)}`);
      const counts = Object.entries(dashboard.assignment_counts || {})
        .map(([key, value]) => `${esc(key)} ${esc(value)}`).join(" · ") || "无";
      const budget = dashboard.budget
        ? `状态 ${esc(dashboard.budget.status)} · 用量 ${esc(JSON.stringify(dashboard.budget.usage))}`
        : "未分配";
      const assignmentRows = (dashboard.assignments || []).map((item) => `
        <tr>
          <td>${esc(item.objective)}<br /><small class="muted">${esc(item.assignment_id)}</small></td>
          <td><small class="muted">${esc(item.agent_definition_id)}</small></td>
          <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td>
          <td>${esc((item.dependencies || []).join(", ") || "-")}</td>
        </tr>`).join("");
      const handoffRows = (dashboard.handoffs || []).map((item) => `
        <tr><td>${esc(item.handoff_id)}</td><td>${esc(item.handoff_type)}</td>
        <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td></tr>`).join("");
      const conflictRows = (dashboard.conflicts || []).map((item) => `
        <tr><td>${esc(item.conflict_id)}</td><td>${esc(item.conflict_type)}</td>
        <td>${esc(item.severity)}</td>
        <td><span class="pill ${statusClass(item.resolution_status)}">${esc(item.resolution_status)}</span></td></tr>`).join("");
      const integrationRows = (dashboard.integrations || []).map((item) => `
        <tr><td>${esc(item.integration_id)}</td>
        <td><span class="pill ${statusClass(item.status)}">${esc(item.status)}</span></td>
        <td>${esc(item.verification_reference || "-")}</td></tr>`).join("");
      const edges = (dashboard.graph && dashboard.graph.edges || [])
        .map((edge) => `${esc(edge.from)} → ${esc(edge.to)}`).join("<br />") || "无依赖";
      $("multi-agent-detail").className = "";
      $("multi-agent-detail").innerHTML = `
        <div class="muted">Team ${esc(dashboard.team.team_id)} · 状态
          <span class="pill ${statusClass(dashboard.team.status)}">${esc(dashboard.team.status)}</span>
          · Assignment ${counts}</div>
        <div class="muted">成员：${(dashboard.members || []).map((member) => esc(member.role)).join(", ") || "-"}
          · 预算：${budget}</div>
        <h2>Assignment</h2>
        <table><thead><tr><th>目标</th><th>Agent</th><th>状态</th><th>依赖</th></tr></thead>
          <tbody>${assignmentRows || '<tr><td colspan="4" class="empty">暂无 Assignment</td></tr>'}</tbody></table>
        <h2>依赖图</h2><div class="muted">${edges}</div>
        <h2>Handoff</h2>
        <table><thead><tr><th>Handoff</th><th>类型</th><th>状态</th></tr></thead>
          <tbody>${handoffRows || '<tr><td colspan="3" class="empty">暂无 Handoff</td></tr>'}</tbody></table>
        <h2>冲突</h2>
        <table><thead><tr><th>冲突</th><th>类型</th><th>严重级别</th><th>状态</th></tr></thead>
          <tbody>${conflictRows || '<tr><td colspan="4" class="empty">暂无冲突</td></tr>'}</tbody></table>
        <h2>结果集成</h2>
        <table><thead><tr><th>集成</th><th>状态</th><th>验证引用</th></tr></thead>
          <tbody>${integrationRows || '<tr><td colspan="3" class="empty">暂无集成</td></tr>'}</tbody></table>`;
    } catch (error) {
      showError(`读取 Team 失败：${error.message}`);
    }
  }

  async function refreshAll() {
    showError("");
    try {
      await loadProjects();
      if (state.projectId) {
        await Promise.all([
          loadDetail(), loadTasks(), loadApprovals(), loadTools(), loadExecutions(), loadModels(),
          loadAgents(), loadMultiAgent()
        ]);
      }
    } catch (error) {
      showError(`加载失败：${error.message}`);
    }
  }

  $("token").value = state.token;
  $("connect").addEventListener("click", () => {
    state.token = $("token").value.trim();
    sessionStorage.setItem("godot_ai_token", state.token);
    $("who").textContent = state.token ? "已输入 Token" : "未连接";
    refreshAll();
  });
  $("refresh").addEventListener("click", refreshAll);
  if (state.token) {
    $("who").textContent = "已输入 Token";
    refreshAll();
  }
})();
</script>
</body>
</html>
"""
