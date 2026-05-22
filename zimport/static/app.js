const CHUNK = 10 * 1024 * 1024; // 10MB
let pollTimer = null;

function $(id) { return document.getElementById(id); }

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error("未登录"); }
  return r;
}

function showLogin() {
  $("login").classList.remove("hidden");
  $("main").classList.add("hidden");
}

function showMain(account, isAdmin) {
  $("login").classList.add("hidden");
  $("main").classList.remove("hidden");
  $("who").textContent = account;
  $("adminBox").classList.toggle("hidden", !isAdmin);
  refreshTasks();
}

$("loginBtn").onclick = async () => {
  $("loginErr").textContent = "";
  const r = await fetch("/api/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: $("username").value,
                          password: $("password").value})
  });
  const data = await r.json();
  if (!r.ok) { $("loginErr").textContent = data.error || "登录失败"; return; }
  showMain(data.account, data.is_admin);
};

$("logoutBtn").onclick = async () => {
  await fetch("/api/logout", {method: "POST"});
  showLogin();
};

$("refreshBtn").onclick = refreshTasks;

async function uploadFile(uploadId, fileIndex, file) {
  const total = Math.ceil(file.size / CHUNK);
  for (let i = 0; i < total; i++) {
    const blob = file.slice(i * CHUNK, (i + 1) * CHUNK);
    const fd = new FormData();
    fd.append("upload_id", uploadId);
    fd.append("file_index", fileIndex);
    fd.append("chunk_index", i);
    fd.append("blob", blob);
    await api("/api/upload/chunk", {method: "POST", body: fd});
    $("uploadProgress").textContent =
      `上传 ${file.name}: ${i + 1}/${total} 片`;
  }
  return total;
}

$("startBtn").onclick = async () => {
  const files = $("files").files;
  if (!files.length) { alert("请先选择文件"); return; }
  const init = await (await api("/api/upload/init",
    {method: "POST", headers: {"Content-Type": "application/json"},
     body: "{}"})).json();
  const uploadId = init.upload_id;
  const meta = [];
  for (let idx = 0; idx < files.length; idx++) {
    const chunks = await uploadFile(uploadId, idx, files[idx]);
    meta.push({index: idx, name: files[idx].name, chunks: chunks});
  }
  const body = {upload_id: uploadId, files: meta, folder: $("folder").value};
  const ta = $("targetAccount").value.trim();
  if (ta) body.account = ta;
  const r = await api("/api/import", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok) { alert(data.error || "导入失败"); return; }
  $("uploadProgress").textContent = "上传完成,任务已进入队列: " + data.task_id;
  refreshTasks();
};

async function refreshTasks() {
  const tasks = await (await api("/api/tasks")).json();
  const tbody = $("tasks").querySelector("tbody");
  tbody.innerHTML = "";
  let anyActive = false;
  for (const t of tasks) {
    if (t.status === "queued" || t.status === "running") anyActive = true;
    const pct = t.total ? Math.round(100 * t.done / t.total) : 0;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${t.id.slice(0, 8)}</td><td>${t.account}</td>` +
      `<td>${statusText(t.status)}</td>` +
      `<td><div class="bar"><div style="width:${pct}%"></div></div>` +
      `${t.done}/${t.total}</td><td>${t.failed}</td>`;
    tbody.appendChild(tr);
  }
  if (anyActive && !pollTimer) {
    pollTimer = setInterval(refreshTasks, 3000);
  } else if (!anyActive && pollTimer) {
    clearInterval(pollTimer); pollTimer = null;
  }
}

function statusText(s) {
  return {queued: "排队中", running: "进行中", done: "完成",
          failed: "失败", interrupted: "中断"}[s] || s;
}

// 启动时探测是否已登录
fetch("/api/me").then(r => {
  if (r.ok) return r.json().then(d => showMain(d.account, d.is_admin));
  showLogin();
}).catch(() => showLogin());
