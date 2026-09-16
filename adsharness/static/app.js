const $ = (s) => document.querySelector(s);
const labels = {mcp: "MCP server", skill: "Skill", harness: "Harness", instruction: "Instructions"};
const state = {items: [], view: "all", token: "", selected: null, revision: "", original: "", request: 0, document: null, mode: "read", proposalJob: null, authJob: null};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(path, body) {
  const response = await fetch(path, {headers: {"X-adsharness-token": state.token, "Content-Type": "application/json"}, ...(body ? {method: "POST", body: JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Could not access the environment");
  return data;
}
function toast(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(state.timer); state.timer = setTimeout(() => $("#toast").hidden = true, 4500); }
async function refresh() {
  $("#refresh").disabled = true;
  try {
    const result = await api("/api/inventory");
    state.items = result.items;
    $("#issues").textContent = result.issues.join(" · ");
    render();
  } catch (error) { toast(error.message); $("#list").textContent = "Could not load the inventory. Try refreshing."; }
  finally { $("#refresh").disabled = false; }
}
function render() {
  const totals = [["mcp", "MCP servers", "Configured connections"], ["skill", "Available skills", "Knowledge within reach"], ["harness", "Harness settings", "Detected preferences"], ["favorites", "Your favorites", "Keep essentials close"]];
  $("#stats").innerHTML = totals.map(([kind, title, sub], index) => `<button class="stat" data-stat="${kind}"><span>${title}<b>0${index + 1}</b></span><strong>${state.items.filter(i => kind === "favorites" ? i.favorite : i.kind === kind).length}</strong><small>${sub} ↗</small></button>`).join("");
  const query = $("#search").value.toLocaleLowerCase();
  const provider = $("#provider").value;
  const scope = $("#scope-filter").value;
  const items = state.items.filter(i => (state.view === "all" || (state.view === "favorites" ? i.favorite : state.view === "harness" ? ["harness", "instruction"].includes(i.kind) : i.kind === state.view)) && (provider === "all" || i.provider === provider) && (scope === "all" || i.scope.startsWith(scope)) && [i.name, i.description, ...(i.tags || [])].join(" ").toLocaleLowerCase().includes(query)).sort((a,b) => Number(!!b.favorite) - Number(!!a.favorite) || a.name.localeCompare(b.name));
  $("#count").textContent = `${items.length} items`;
  $("#list").innerHTML = items.length ? items.map(i => `<article class="card"><div class="card-top"><span class="item-icon ${i.kind}">${({mcp:"⌘",skill:"◇",harness:"▤",instruction:"≡"})[i.kind]}</span><span class="kind">${labels[i.kind]}</span><button class="star ${i.favorite ? "selected" : ""}" data-favorite="${i.id}" aria-label="${i.favorite ? "Remove from" : "Add to"} favorites: ${escapeHtml(i.name)}" aria-pressed="${!!i.favorite}">${i.favorite ? "★" : "☆"}</button></div><button class="card-title" data-detail="${i.id}">${escapeHtml(i.name)}</button><p class="description">${escapeHtml(i.description)}</p><div class="tags">${(i.tags || []).map(t => `<span>${escapeHtml(t)}</span>`).join("")}</div><div class="card-bottom"><span class="provider ${i.provider}">${escapeHtml(i.provider)}</span><span>${escapeHtml(i.scope)}</span>${i.kind === "mcp" ? `<span class="status">${i.enabled ? "Configured" : "Disabled"}</span>` : ""}</div></article>`).join("") : '<div class="empty"><span>◇</span><h3>No items here yet</h3><p>Try another search or select a different agent. Items come from detected local files.</p></div>';
}
function setView(view) {
  state.view = view;
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  const name = ({all:"Overview", mcp:"MCP servers", skill:"Skill library", harness:"Harness and instructions", favorites:"Favorites"})[view];
  $("#breadcrumb").textContent = `Workspace / ${name}`;
  $("#section-title").textContent = view === "all" ? "Your environment" : name;
  render();
}
function dirty() { return state.document && $("#editor").value !== state.original; }
function showMode(mode) {
  state.mode = mode;
  $("#read-panel").hidden = mode !== "read";
  $("#editor-wrap").hidden = mode !== "edit";
  $("#agent-panel").hidden = mode !== "agent";
  document.querySelectorAll("[data-mode]").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
}
function renderSource(doc) {
  state.document = doc;
  state.revision = doc.revision;
  state.original = doc.content;
  $("#editor").value = doc.content;
  $("#editor").readOnly = !doc.editable;
  $("#source-viewer").replaceChildren();
  doc.content.split("\n").forEach((text, index) => {
    const line = document.createElement("span");
    line.className = "source-line";
    line.dataset.line = index + 1;
    line.textContent = text || " ";
    $("#source-viewer").append(line);
  });
  $("#document-wrap").hidden = false;
  $("#reveal-original").hidden = !doc.configuration;
  $("#reveal-original").textContent = doc.revealed ? "Hide protected values" : "Reveal original";
  $("#save-document").hidden = !doc.editable;
  $("#request-edit").disabled = !doc.editable;
  $("#source-status").textContent = doc.error || `${doc.format.toUpperCase()} · ${doc.content.split("\n").length} lines · ${doc.revealed ? "Original values visible locally" : doc.masked ? `${doc.protected_values} protected values masked` : "Original file contents"}${doc.editable ? "" : " · Read-only"}`;
}
async function loadSource(reveal = false) {
  const ticket = state.request;
  const doc = await api(`/api/document?id=${state.selected.id}&reveal=${reveal ? 1 : 0}`);
  if (ticket === state.request && $("#detail").open) renderSource(doc);
}
async function closeDetail(event) {
  event?.preventDefault();
  if (dirty() && !confirm("Discard unsaved changes?")) return;
  if (state.proposalJob && !confirm("Cancel this agent request and close the file?")) return;
  if (state.proposalJob) {
    try { await api("/api/agents/cancel", {job_id:state.proposalJob}); }
    catch (error) { toast(error.message); return; }
  }
  state.proposalJob = null;
  state.request++;
  $("#detail").close();
}
async function openDetail(id) {
  state.request++;
  const item = state.items.find(i => i.id === id);
  state.selected = item;
  state.document = null;
  state.proposalJob = null;
  $("#detail-title").textContent = item.name;
  $("#detail-kind").textContent = `${labels[item.kind]} / ${item.provider}`;
  $("#detail-source").textContent = item.source;
  $("#tags").value = (item.tags || []).join(", ");
  $("#detail-message").textContent = "";
  $("#document-wrap").hidden = true;
  $("#detail-info").textContent = item.kind === "mcp" ? `${item.description}. Transport: ${item.transport}. This source file can contain other servers and settings.` : item.description;
  $("#proposal").hidden = true;
  $("#agent-progress").textContent = "";
  $("#edit-instruction").value = "";
  $("#request-edit").disabled = false;
  $("#cancel-edit").hidden = true;
  showMode("read");
  $("#detail").showModal();
  try { await loadSource(); }
  catch (error) { $("#detail-message").textContent = error.message; }
}
document.addEventListener("click", async (event) => {
  const view = event.target.closest("[data-view], [data-stat]"); if (view) setView(view.dataset.view || view.dataset.stat);
  const detail = event.target.closest("[data-detail]"); if (detail) openDetail(detail.dataset.detail);
  const favorite = event.target.closest("[data-favorite]");
  if (favorite) {
    favorite.disabled = true;
    const item = state.items.find(i => i.id === favorite.dataset.favorite);
    try { await api("/api/organize", {id:item.id, favorite:!item.favorite, tags:item.tags || []}); await refresh(); }
    catch (error) { toast(error.message); favorite.disabled = false; }
  }
});
$("#search").addEventListener("input", render);
$("#provider").addEventListener("change", render);
$("#scope-filter").addEventListener("change", render);
$("#refresh").addEventListener("click", refresh);
$("#close").addEventListener("click", closeDetail);
$("#detail").addEventListener("cancel", closeDetail);
$("#save-tags").addEventListener("click", async () => {
  const item = state.selected;
  try { await api("/api/organize", {id:item.id, favorite:!!item.favorite, tags:$("#tags").value.split(",").map(t => t.trim()).filter(Boolean)}); await refresh(); state.selected = state.items.find(i => i.id === item.id); $("#detail-message").textContent = "Tags saved."; }
  catch (error) { $("#detail-message").textContent = error.message; }
});
$("#save-document").addEventListener("click", async () => {
  const content = $("#editor").value;
  $("#save-document").disabled = true;
  try { const result = await api("/api/document", {id:state.selected.id, revision:state.revision, content, reveal:!!state.document?.revealed}); await loadSource(!!state.document?.revealed); $("#detail-message").textContent = `Saved. Backup: ${result.backup}`; await refresh(); }
  catch (error) { $("#detail-message").textContent = error.message; }
  finally { $("#save-document").disabled = false; }
});
window.addEventListener("beforeunload", event => { if ($("#detail").open && (dirty() || state.proposalJob)) { event.preventDefault(); event.returnValue = ""; } });
(async () => { try { state.token = (await api("/api/session")).token; await refresh(); } catch (error) { toast(error.message); } })();

document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => showMode(button.dataset.mode)));
$("#reveal-original").addEventListener("click", async () => {
  if (dirty() && !confirm("Discard unsaved changes and reload the source?")) return;
  const reveal = !state.document.revealed;
  if (reveal && !confirm("Show the original configuration, including credential values, in this browser?")) return;
  try { await loadSource(reveal); } catch (error) { $("#detail-message").textContent = error.message; }
});
function setAccountsBusy(busy) {
  document.querySelectorAll("[data-login], [data-check]").forEach(button => {
    button.disabled = busy || button.dataset.installed !== "true";
  });
}
async function renderAccounts() {
  const agents = await api("/api/agents");
  const active = agents.find(agent => agent.active_job)?.active_job;
  $("#account-list").innerHTML = agents.map(agent => `<article class="account-card"><div><h3>${agent.provider === "codex" ? "Codex" : "Antigravity"}</h3><span class="connection-state ${escapeHtml(agent.state)}">${escapeHtml(agent.state)}</span></div><p>${escapeHtml(agent.message)}</p><div class="agent-actions"><button class="primary" data-installed="${agent.installed}" data-login="${agent.provider}" ${agent.installed ? "" : "disabled"}>${agent.provider === "codex" ? "Sign in with device code" : "Sign in via Terminal"}</button><button class="quiet" data-installed="${agent.installed}" data-check="${agent.provider}" ${agent.installed ? "" : "disabled"}>Check connection</button></div></article>`).join("");
  setAccountsBusy(!!active);
  if (active && state.authJob !== active.id) {
    state.authJob = active.id;
    pollAuth(active.id);
  }
}
$("#connections").addEventListener("click", async () => { $("#accounts").showModal(); try { await renderAccounts(); } catch (error) { toast(error.message); } });
$("#close-accounts").addEventListener("click", () => $("#accounts").close());
async function pollAuth(id) {
  if (state.authJob !== id) return;
  try {
    const job = await api(`/api/job?id=${id}`);
    if (state.authJob !== id) return;
    $("#auth-progress").hidden = false;
    $("#auth-message").textContent = `${job.provider === "codex" ? "Codex" : "Antigravity"} ${job.kind}: ${job.message}`;
    setAccountsBusy(job.status === "running");
    $("#auth-link").hidden = !job.url || job.status !== "running";
    if (job.url) $("#auth-link").href = job.url;
    $("#auth-code-wrap").hidden = !job.code || job.status !== "running";
    $("#auth-code").textContent = job.code || "";
    $("#cancel-auth").hidden = job.status !== "running";
    if (job.status === "running") setTimeout(() => pollAuth(id), 1000);
    else { state.authJob = null; await renderAccounts(); }
  } catch (error) {
    if (state.authJob !== id) return;
    $("#auth-message").textContent = `${error.message} Retrying operation status…`;
    setTimeout(() => pollAuth(id), 2000);
  }
}
$("#accounts").addEventListener("click", async event => {
  const button = event.target.closest("[data-login], [data-check]");
  if (!button) return;
  const action = button.dataset.login ? "login" : "check";
  const provider = button.dataset.login || button.dataset.check;
  setAccountsBusy(true);
  $("#auth-progress").hidden = false;
  $("#auth-link").hidden = true;
  $("#auth-code-wrap").hidden = true;
  $("#auth-message").textContent = "Starting…";
  try {
    const result = await api(`/api/agents/${action}`, {provider});
    if (result.id) { state.authJob = result.id; pollAuth(result.id); }
    else $("#auth-message").textContent = result.message;
  } catch (error) { $("#auth-message").textContent = error.message; }
  finally { try { await renderAccounts(); } catch (error) { toast(error.message); } }
});
$("#cancel-auth").addEventListener("click", async () => { try { if (state.authJob) await api("/api/agents/cancel", {job_id:state.authJob}); } catch (error) { toast(error.message); } });
async function pollProposal(id, ticket) {
  if (state.proposalJob !== id || state.request !== ticket) return;
  try {
    const job = await api(`/api/job?id=${id}`);
    if (state.proposalJob !== id || state.request !== ticket) return;
    $("#agent-progress").textContent = job.message;
    if (job.status === "running") { setTimeout(() => pollProposal(id, ticket), 1000); return; }
    state.proposalJob = null;
    $("#cancel-edit").hidden = true;
    $("#request-edit").disabled = false;
    if (job.status === "ready") {
      $("#proposal").hidden = false;
      $("#proposal-summary").textContent = job.summary;
      $("#proposal-diff").textContent = job.diff || "No changes proposed.";
      $("#apply-proposal").dataset.job = id;
      $("#apply-proposal").disabled = !job.diff;
    }
  } catch (error) { $("#agent-progress").textContent = error.message; $("#request-edit").disabled = false; $("#cancel-edit").hidden = true; state.proposalJob = null; }
}
$("#request-edit").addEventListener("click", async () => {
  if (dirty()) { $("#agent-progress").textContent = "Save or discard your manual edits before requesting an agent proposal."; return; }
  $("#request-edit").disabled = true;
  $("#proposal").hidden = true;
  const ticket = state.request;
  try {
    const result = await api("/api/agents/propose", {provider:$("#edit-agent").value, id:state.selected.id, revision:state.revision, instruction:$("#edit-instruction").value, model:$("#edit-model").value.trim()});
    if (ticket !== state.request || !$("#detail").open) { await api("/api/agents/cancel", {job_id:result.id}); return; }
    state.proposalJob = result.id;
    $("#cancel-edit").hidden = false;
    pollProposal(result.id, ticket);
  } catch (error) { $("#agent-progress").textContent = error.message; $("#request-edit").disabled = false; }
});
$("#cancel-edit").addEventListener("click", async () => { try { if (state.proposalJob) await api("/api/agents/cancel", {job_id:state.proposalJob}); } catch (error) { toast(error.message); } });
$("#apply-proposal").addEventListener("click", async () => {
  if (dirty()) { $("#agent-progress").textContent = "Save or discard your manual edits before applying this proposal."; return; }
  $("#apply-proposal").disabled = true;
  try {
    const result = await api("/api/agents/apply", {job_id:$("#apply-proposal").dataset.job});
    $("#agent-progress").textContent = `Applied to the original file. Backup: ${result.backup}`;
    $("#proposal").hidden = true;
    await loadSource();
    await refresh();
  } catch (error) { $("#agent-progress").textContent = error.message; $("#apply-proposal").disabled = false; }
});
