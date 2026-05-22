// 上传分片大小
const CHUNK = 10 * 1024 * 1024;

// 全局轮询定时器(登出时要清,避免跨账户残留)
let pollTimer = null;
// 账户搜索 debounce 定时器
let acctSearchTimer = null;
// 当前登录态
let me = null;

function $(id) { return document.getElementById(id); }

// ------- 网络封装 -------

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) {
    me = null;
    showLogin();
    throw new Error("未登录");
  }
  return r;
}

// ------- toast -------

function toast(msg, kind) {
  const host = $("toastHost");
  const el = document.createElement("div");
  el.className = "toast " + (kind || "");
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity .25s";
    setTimeout(() => el.remove(), 280);
  }, 3500);
}

// ------- UI 状态切换 -------

function resetUiState() {
  // 清前端所有残留(跨账户登录时必须做),后端 session 已清
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  $("files").value = "";
  $("targetAccount").value = "";
  $("accountList").innerHTML = "";
  $("folder").innerHTML = "<option value=\"Inbox\">Inbox</option>";
  $("tasks").querySelector("tbody").innerHTML = "";
  $("emptyTasks").classList.add("hidden");
  $("uploadProgress").classList.add("hidden");
  $("uploadProgress").querySelector(".upload-label").textContent = "";
  $("uploadProgress").querySelector(".bar-fill").style.width = "0";
  $("loginErr").textContent = "";
}

function showLogin() {
  resetUiState();
  $("login").classList.remove("hidden");
  $("main").classList.add("hidden");
  $("userbar").classList.add("hidden");
}

function showMain(account, isAdmin) {
  me = {account: account, isAdmin: isAdmin};
  $("login").classList.add("hidden");
  $("main").classList.remove("hidden");
  $("userbar").classList.remove("hidden");
  $("who").textContent = account;
  $("adminBadge").classList.toggle("hidden", !isAdmin);
  $("adminBox").classList.toggle("hidden", !isAdmin);
  // 初次:拉自己的文件夹列表
  loadFolders(account);
  refreshTasks();
}

// ------- 登录 / 登出 -------

$("loginBtn").onclick = doLogin;
$("password").addEventListener("keydown", e => {
  if (e.key === "Enter") doLogin();
});

async function doLogin() {
  $("loginErr").textContent = "";
  const r = await fetch("/api/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: $("username").value,
                          password: $("password").value})
  });
  const data = await r.json();
  if (!r.ok) {
    $("loginErr").textContent = data.error || "登录失败";
    return;
  }
  $("password").value = "";  // 不留密码在 DOM
  showMain(data.account, data.is_admin);
}

$("logoutBtn").onclick = async () => {
  try { await fetch("/api/logout", {method: "POST"}); } catch (_) {}
  me = null;
  showLogin();
};

// ------- 文件夹列表 -------

async function loadFolders(account) {
  const sel = $("folder");
  const current = sel.value;
  sel.innerHTML = "<option value=\"\" disabled>加载中…</option>";
  sel.disabled = true;
  try {
    const url = "/api/folders" +
                (account && account !== me.account
                 ? "?account=" + encodeURIComponent(account)
                 : "");
    const r = await api(url);
    const data = await r.json();
    if (!r.ok) {
      toast(data.error || "无法加载文件夹", "err");
      sel.innerHTML = "<option value=\"Inbox\">Inbox</option>";
      return;
    }
    const folders = data.folders && data.folders.length
                    ? data.folders : ["Inbox"];
    sel.innerHTML = "";
    for (const f of folders) {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    }
    // 尽量保留之前的选择
    if (folders.includes(current)) sel.value = current;
  } catch (e) {
    sel.innerHTML = "<option value=\"Inbox\">Inbox</option>";
  } finally {
    sel.disabled = false;
  }
}

// ------- 管理员账户搜索 (debounce + datalist) -------

$("targetAccount").addEventListener("input", () => {
  if (!me || !me.isAdmin) return;
  if (acctSearchTimer) clearTimeout(acctSearchTimer);
  acctSearchTimer = setTimeout(searchAccounts, 250);
});

// 选完账户(blur 或 change)就拉对应账户的文件夹
$("targetAccount").addEventListener("change", () => onTargetAccountChange());
$("targetAccount").addEventListener("blur", () => onTargetAccountChange());

let lastLoadedAccount = null;

function onTargetAccountChange() {
  if (!me) return;
  const v = $("targetAccount").value.trim();
  const account = v || me.account;
  if (account === lastLoadedAccount) return;
  lastLoadedAccount = account;
  loadFolders(account);
}

async function searchAccounts() {
  const q = $("targetAccount").value.trim();
  if (q.length < 2) { $("accountList").innerHTML = ""; return; }
  try {
    const r = await api("/api/admin/accounts/search?q=" +
                        encodeURIComponent(q));
    const data = await r.json();
    if (!r.ok) return;
    const dl = $("accountList");
    dl.innerHTML = "";
    for (const acc of data.accounts || []) {
      const opt = document.createElement("option");
      opt.value = acc.name;
      if (acc.display) opt.label = acc.display + " — " + acc.name;
      dl.appendChild(opt);
    }
  } catch (e) { /* 401 已被 api() 处理 */ }
}

// ------- 上传与导入 -------

$("refreshBtn").onclick = refreshTasks;

$("startBtn").onclick = doImport;

async function uploadFile(uploadId, fileIndex, file, onProgress) {
  const total = Math.ceil(file.size / CHUNK);
  for (let i = 0; i < total; i++) {
    const blob = file.slice(i * CHUNK, (i + 1) * CHUNK);
    const fd = new FormData();
    fd.append("upload_id", uploadId);
    fd.append("file_index", fileIndex);
    fd.append("chunk_index", i);
    fd.append("blob", blob);
    await api("/api/upload/chunk", {method: "POST", body: fd});
    onProgress(file.name, i + 1, total);
  }
  return total;
}

function setUploadProgress(label, ratio) {
  const wrap = $("uploadProgress");
  wrap.classList.remove("hidden");
  wrap.querySelector(".upload-label").textContent = label;
  wrap.querySelector(".bar-fill").style.width =
      Math.round(ratio * 100) + "%";
}

async function doImport() {
  const files = $("files").files;
  if (!files.length) { toast("请先选择文件", "warn"); return; }
  $("startBtn").disabled = true;
  try {
    const init = await (await api("/api/upload/init",
      {method: "POST", headers: {"Content-Type": "application/json"},
       body: "{}"})).json();
    const uploadId = init.upload_id;
    const meta = [];
    for (let idx = 0; idx < files.length; idx++) {
      const f = files[idx];
      const chunks = await uploadFile(uploadId, idx, f, (n, i, t) => {
        const overall = (idx + i / t) / files.length;
        setUploadProgress(`上传 ${n} (${i}/${t})`, overall);
      });
      meta.push({index: idx, name: f.name, chunks: chunks});
    }
    setUploadProgress("提交任务…", 1);
    const body = {upload_id: uploadId, files: meta, folder: $("folder").value};
    const ta = $("targetAccount").value.trim();
    if (ta) body.account = ta;
    const r = await api("/api/import", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok) { toast(data.error || "导入失败", "err"); return; }
    toast("已加入队列: " + data.task_id.slice(0, 8), "ok");
    $("files").value = "";
    setTimeout(() => $("uploadProgress").classList.add("hidden"), 1500);
    refreshTasks();
  } catch (e) {
    if (e.message !== "未登录") toast(e.message || "上传出错", "err");
  } finally {
    $("startBtn").disabled = false;
  }
}

// ------- 任务列表 -------

async function refreshTasks() {
  let tasks;
  try {
    tasks = await (await api("/api/tasks")).json();
  } catch (e) { return; }
  const tbody = $("tasks").querySelector("tbody");
  // 记录展开状态,刷新后保留
  const expanded = new Set();
  tbody.querySelectorAll("tr.task-detail:not(.hidden)").forEach(r => {
    if (r.dataset.id) expanded.add(r.dataset.id);
  });
  tbody.innerHTML = "";
  let anyActive = false;
  for (const t of tasks) {
    if (t.status === "queued" || t.status === "running") anyActive = true;
    const pct = t.total ? Math.round(100 * t.done / t.total) : 0;
    const tr = document.createElement("tr");
    tr.className = "task-row";
    tr.innerHTML =
      `<td><code>${t.id.slice(0, 8)}</code></td>` +
      `<td>${escapeHtml(t.account)}</td>` +
      `<td><span class="status status-${t.status}">` +
      `${statusText(t.status)}</span></td>` +
      `<td><div class="bar"><div class="bar-fill" ` +
      `style="width:${pct}%"></div></div> ${t.done}/${t.total}</td>` +
      `<td>${t.skipped || 0}</td>` +
      `<td>${t.failed}</td>`;
    const detail = document.createElement("tr");
    detail.className = "task-detail" + (expanded.has(t.id) ? "" : " hidden");
    detail.dataset.id = t.id;
    const td = document.createElement("td");
    td.colSpan = 6;
    td.appendChild(buildTaskDetail(t));
    detail.appendChild(td);
    tr.onclick = () => detail.classList.toggle("hidden");
    tbody.appendChild(tr);
    tbody.appendChild(detail);
  }
  $("emptyTasks").classList.toggle("hidden", tasks.length > 0);
  if (anyActive && !pollTimer) {
    pollTimer = setInterval(refreshTasks, 3000);
  } else if (!anyActive && pollTimer) {
    clearInterval(pollTimer); pollTimer = null;
  }
}

function buildTaskDetail(t) {
  const box = document.createElement("div");
  box.className = "task-detail-body";
  if (t.error) {
    const p = document.createElement("p");
    p.className = "err";
    p.textContent = "任务错误:" + t.error;
    box.appendChild(p);
  }
  let failures = [];
  if (t.failures) {
    try { failures = JSON.parse(t.failures) || []; } catch (_) {}
  }
  if (failures.length > 0) {
    const h = document.createElement("h4");
    h.textContent = "明细 (" + failures.length + ")";
    box.appendChild(h);
    const ul = document.createElement("ul");
    for (const f of failures) {
      const li = document.createElement("li");
      const code = document.createElement("code");
      code.textContent = f.name;
      li.appendChild(code);
      li.appendChild(document.createTextNode(" — " + (f.reason || "")));
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }
  if (t.status === "failed" || t.status === "interrupted") {
    const btn = document.createElement("button");
    btn.className = "primary";
    btn.textContent = "重试";
    btn.onclick = (ev) => { ev.stopPropagation(); doRetry(t.id); };
    box.appendChild(btn);
  }
  if (box.children.length === 0) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "无更多详情";
    box.appendChild(p);
  }
  return box;
}

async function doRetry(id) {
  try {
    const r = await api("/api/tasks/" + encodeURIComponent(id) + "/retry",
                        {method: "POST"});
    const data = await r.json();
    if (!r.ok) { toast(data.error || "重试失败", "err"); return; }
    toast("重试任务已入队: " + data.task_id.slice(0, 8), "ok");
    refreshTasks();
  } catch (e) {
    if (e.message !== "未登录") toast(e.message, "err");
  }
}

function statusText(s) {
  return {queued: "排队中", running: "进行中", done: "完成",
          failed: "失败", interrupted: "中断"}[s] || s;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    "\"": "&quot;", "'": "&#39;"}[c]));
}

// ------- 启动 -------

fetch("/api/me").then(r => {
  if (r.ok) return r.json().then(d => showMain(d.account, d.is_admin));
  showLogin();
}).catch(() => showLogin());
