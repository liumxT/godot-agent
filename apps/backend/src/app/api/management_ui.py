"""管理界面（E4-T23）。

以单页 HTML 形式提供项目、任务、Workflow 与审批的管理入口。
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
    await Promise.all([loadDetail(), loadTasks(), loadApprovals()]);
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

  async function refreshAll() {
    showError("");
    try {
      await loadProjects();
      if (state.projectId) {
        await Promise.all([loadDetail(), loadTasks(), loadApprovals()]);
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
