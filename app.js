// ============================================================
// MetroReport — App front-end (vanilla JS, sem build step)
// ============================================================

const API_BASE = ""; // mesmo host (backend serve o front também)

const state = {
  token: localStorage.getItem("metro_token") || null,
  user: null,
  lines: [],
};

// ---------------------------------------------------------- helpers ----

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }

async function api(path, { method = "GET", body = null, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* sem corpo */ }
  if (!res.ok) {
    const msg = (data && data.detail) ? data.detail : "Ocorreu um erro. Tente novamente.";
    throw new Error(msg);
  }
  return data;
}

function toast(msg) {
  const el = $("#toast");
  $("#toast-text").textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2800);
}

function initials(name) {
  return name.split(" ").filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("");
}

const STATUS_COLOR = {
  normal: "var(--accent)",
  reduzida: "var(--warn)",
  parcial: "var(--danger)",
  paralisada: "var(--crit)",
};

// =========================================================
// AUTENTICAÇÃO
// =========================================================

function showAuthError(msg) {
  const el = $("#auth-error");
  el.textContent = msg;
  el.classList.add("show");
}
function hideAuthError() {
  $("#auth-error").classList.remove("show");
}

let authMode = "login";

function showAuthForm(mode) {
  authMode = mode;
  hideAuthError();
  $all("#auth-screen form").forEach(f => f.classList.add("hidden"));
  const switchRow = $(".auth-switch");
  if (mode === "login") {
    $("#login-form").classList.remove("hidden");
    $("#auth-subtitle").textContent = "Entre para ver o status das linhas em tempo real.";
    switchRow.classList.remove("hidden");
    $("#switch-text").textContent = "Ainda não tem conta?";
    $("#switch-btn").textContent = "Cadastre-se";
  } else if (mode === "register") {
    $("#register-form").classList.remove("hidden");
    $("#auth-subtitle").textContent = "Crie sua conta para acompanhar suas linhas.";
    switchRow.classList.remove("hidden");
    $("#switch-text").textContent = "Já tem conta?";
    $("#switch-btn").textContent = "Entrar";
  } else if (mode === "forgot") {
    $("#forgot-form").classList.remove("hidden");
    $("#auth-subtitle").textContent = "Informe seu e-mail para receber o link de redefinição.";
    switchRow.classList.add("hidden");
  } else if (mode === "reset") {
    $("#reset-form").classList.remove("hidden");
    $("#auth-subtitle").textContent = "Escolha sua nova senha.";
    switchRow.classList.add("hidden");
  }
}

$("#switch-btn").addEventListener("click", () => {
  showAuthForm(authMode === "login" ? "register" : "login");
});

$("#forgot-link").addEventListener("click", () => showAuthForm("forgot"));
$("#back-to-login-link").addEventListener("click", () => showAuthForm("login"));

$("#forgot-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();
  try {
    const data = await api("/api/auth/forgot-password", {
      method: "POST",
      auth: false,
      body: { email: $("#forgot-email").value.trim() },
    });
    toast(data.message || "Se esse e-mail estiver cadastrado, enviamos um link.");
    showAuthForm("login");
  } catch (err) {
    showAuthError(err.message);
  }
});

let resetToken = null;

$("#reset-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();
  try {
    await api("/api/auth/reset-password", {
      method: "POST",
      auth: false,
      body: { token: resetToken, new_password: $("#reset-password").value },
    });
    toast("Senha redefinida! Já pode entrar.");
    resetToken = null;
    history.replaceState(null, "", window.location.pathname);
    showAuthForm("login");
  } catch (err) {
    showAuthError(err.message);
  }
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      auth: false,
      body: { email: $("#login-email").value.trim(), password: $("#login-password").value },
    });
    onAuthSuccess(data);
  } catch (err) {
    showAuthError(err.message);
  }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      auth: false,
      body: {
        name: $("#register-name").value.trim(),
        email: $("#register-email").value.trim(),
        password: $("#register-password").value,
      },
    });
    onAuthSuccess(data);
  } catch (err) {
    showAuthError(err.message);
  }
});

function onAuthSuccess(data) {
  state.token = data.token;
  state.user = data.user;
  localStorage.setItem("metro_token", data.token);
  bootApp();
}

$("#logout-btn").addEventListener("click", () => {
  localStorage.removeItem("metro_token");
  state.token = null;
  state.user = null;
  $("#app-shell").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
});

// =========================================================
// SIDEBAR / NAVEGAÇÃO
// =========================================================

$all(".nav-item[data-page]").forEach(item => {
  item.addEventListener("click", () => {
    $all(".nav-item[data-page]").forEach(n => n.classList.remove("active"));
    item.classList.add("active");
    $all(".page").forEach(p => p.classList.remove("active"));
    $(`#page-${item.dataset.page}`).classList.add("active");
    $("#app-shell").classList.remove("mobile-open");
    if (item.dataset.page === "notifications") loadNotifications();
    if (item.dataset.page === "profile") loadProfile();
  });
});

$("#toggle-sidebar").addEventListener("click", () => {
  $("#app-shell").classList.toggle("sidebar-collapsed");
});

$("#mobile-menu-btn").addEventListener("click", () => {
  $("#app-shell").classList.add("mobile-open");
});
$("#overlay-scrim").addEventListener("click", () => {
  $("#app-shell").classList.remove("mobile-open");
});

// =========================================================
// RELÓGIO
// =========================================================
function tickClock() {
  const now = new Date();
  $("#clock").textContent = now.toLocaleTimeString("pt-BR");
}
setInterval(tickClock, 1000);

// =========================================================
// DASHBOARD — LINHAS
// =========================================================

function renderLineBubble(line) {
  const color = STATUS_COLOR[line.status] || "var(--accent)";
  const pulsing = line.status !== "normal";
  return `
    <div class="line-bubble" style="--line-color:${line.color}">
      <div class="line-top">
        <div class="line-badge" style="--line-color:${line.color}">${line.number}</div>
        <div class="line-meta">
          <div class="line-name">${line.name}</div>
          <div class="line-type">${line.type === "metro" ? "Metrô" : "CPTM"}</div>
        </div>
      </div>
      <div class="status-pill" style="--status-color:${color}">
        <span class="status-dot ${pulsing ? "pulsing" : ""}" style="--status-color:${color}"></span>
        <span>${line.status_label}</span>
      </div>
      ${line.detail ? `<div class="line-detail">${line.detail}</div>` : ""}
    </div>
  `;
}

async function loadLines() {
  const lines = await api("/api/lines/status", { auth: false });
  state.lines = lines;
  const metro = lines.filter(l => l.type === "metro");
  const cptm = lines.filter(l => l.type === "cptm");
  $("#grid-metro").innerHTML = metro.map(renderLineBubble).join("");
  $("#grid-cptm").innerHTML = cptm.map(renderLineBubble).join("");
  populateLineSelects(lines);
}

// =========================================================
// NOTIFICAÇÕES
// =========================================================

async function loadNotifications() {
  const prefs = await api("/api/me/notifications");
  const lineMap = Object.fromEntries(state.lines.map(l => [l.id, l]));

  $("#notif-list").innerHTML = prefs.map(p => {
    const line = lineMap[p.line_id] || {};
    const hasWindow = !!(p.start_time && p.end_time);
    return `
      <div class="notif-row" data-line="${p.line_id}">
        <div class="notif-row-head">
          <div class="notif-line-info">
            <div class="mini-badge" style="--line-color:${line.color || '#555'}">${line.number || p.line_id}</div>
            <span>Linha ${p.name}</span>
          </div>
          <label class="switch">
            <input type="checkbox" class="notif-enable" data-line="${p.line_id}" ${p.enabled ? "checked" : ""}>
            <span class="switch-track"></span>
          </label>
        </div>
        <div class="notif-panel ${p.enabled ? "open" : ""}">
          <div class="notif-panel-hint">Só avisamos essa linha dentro do horário abaixo. Deixe em branco pra ser avisado a qualquer hora.</div>
          <div class="notif-panel-inner">
            <div class="time-field">
              <label>A partir de</label>
              <input type="time" class="notif-start" data-line="${p.line_id}" value="${p.start_time || ""}">
            </div>
            <div class="time-field">
              <label>Até</label>
              <input type="time" class="notif-end" data-line="${p.line_id}" value="${p.end_time || ""}">
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");

  function currentPrefsPayload() {
    return $all(".notif-row").map(row => {
      const lineId = row.dataset.line;
      const enabled = row.querySelector(".notif-enable").checked;
      const start = row.querySelector(".notif-start").value || null;
      const end = row.querySelector(".notif-end").value || null;
      return { line_id: lineId, enabled, start_time: start, end_time: end };
    });
  }

  async function saveNotifications() {
    try {
      await api("/api/me/notifications", { method: "PUT", body: { prefs: currentPrefsPayload() } });
      toast("Preferências salvas");
    } catch (e) {
      toast(e.message || "Não foi possível salvar agora");
    }
  }

  $all(".notif-enable").forEach(input => {
    input.addEventListener("change", () => {
      const panel = input.closest(".notif-row").querySelector(".notif-panel");
      panel.classList.toggle("open", input.checked);
      saveNotifications();
    });
  });

  $all(".notif-start, .notif-end").forEach(input => {
    input.addEventListener("change", saveNotifications);
  });
}

// Mantido por compatibilidade: hoje não há mais nenhum <select> de linha
// no front, mas se algum dia voltar a existir, é só chamar essa função de novo.
function populateLineSelects(lines) { /* no-op por enquanto */ }

// =========================================================
// PERFIL
// =========================================================

function renderAvatarInto(el, user) {
  if (user.avatar_base64) {
    el.innerHTML = `<img src="${user.avatar_base64}" alt="Foto de perfil">`;
  } else {
    el.textContent = initials(user.name);
  }
}

function loadProfile() {
  $("#profile-name").textContent = state.user.name;
  $("#profile-email").textContent = state.user.email;
  $("#profile-name-input").value = state.user.name;
  $("#profile-phone-input").value = state.user.phone || "";
  $("#profile-notify-channel").value = state.user.notify_channel || "email";
  renderAvatarInto($("#profile-avatar"), state.user);
}

$("#avatar-edit").addEventListener("click", () => $("#avatar-input").click());

$("#avatar-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    toast("Escolha uma imagem de até 2MB");
    return;
  }
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const updated = await api("/api/me/profile", { method: "PUT", body: { avatar_base64: reader.result } });
      state.user = updated;
      renderAvatarInto($("#profile-avatar"), state.user);
      renderAvatarInto($("#sidebar-avatar"), state.user);
      toast("Foto atualizada");
    } catch (err) {
      toast(err.message);
    }
  };
  reader.readAsDataURL(file);
});

$("#profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const updated = await api("/api/me/profile", { method: "PUT", body: { name: $("#profile-name-input").value.trim() } });
    state.user = updated;
    $("#profile-name").textContent = updated.name;
    $("#sidebar-username").textContent = updated.name;
    renderAvatarInto($("#sidebar-avatar"), updated);
    renderAvatarInto($("#profile-avatar"), updated);
    toast("Perfil atualizado");
  } catch (err) {
    toast(err.message);
  }
});

$("#notify-channel-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const updated = await api("/api/me/profile", {
      method: "PUT",
      body: {
        phone: $("#profile-phone-input").value.trim(),
        notify_channel: $("#profile-notify-channel").value,
      },
    });
    state.user = updated;
    toast("Preferências de notificação salvas");
  } catch (err) {
    toast(err.message);
  }
});

$("#dev-test-btn").addEventListener("click", async () => {
  const btn = $("#dev-test-btn");
  btn.disabled = true;
  btn.textContent = "Enviando…";
  try {
    const result = await api("/api/dev/test-notification", { method: "POST" });
    if (result.bad_lines.length === 0) {
      toast(`Push de teste enviado (${result.sent}/${result.total_devices} aparelho(s)): todas as linhas OK`);
    } else {
      toast(`Push de teste enviado: ${result.bad_lines.length} linha(s) com problema — confira a notificação`);
    }
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "TESTE";
  }
});

// =========================================================
// BOOT
// =========================================================

async function bootApp() {
  try {
    const user = await api("/api/me");
    state.user = user;
  } catch (e) {
    localStorage.removeItem("metro_token");
    state.token = null;
    $("#app-shell").classList.add("hidden");
    $("#auth-screen").classList.remove("hidden");
    return;
  }

  $("#auth-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");

  $("#sidebar-username").textContent = state.user.name;
  renderAvatarInto($("#sidebar-avatar"), state.user);

  tickClock();
  await loadLines();
  setupPush();

  if (localStorage.getItem("metro_dev") === "1") {
    $("#dev-tools-card").classList.remove("hidden");
  }

  setInterval(loadLines, 30000);
}

// =========================================================
// PUSH (PWA) — canal principal de notificação
// =========================================================

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function setupPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return; // navegador não suporta (raro hoje em dia, mas não quebra o resto do app)
  }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const existing = await reg.pushManager.getSubscription();
    if (existing || Notification.permission === "denied") {
      $("#push-banner").classList.remove("show");
      if (existing) sendSubscriptionToServer(existing); // mantém sincronizado
      return;
    }
    $("#push-banner").classList.add("show");
  } catch (e) {
    // silencioso — não é crítico pro resto do app funcionar
  }
}

async function sendSubscriptionToServer(subscription) {
  const json = subscription.toJSON();
  try {
    await api("/api/me/push-subscribe", {
      method: "POST",
      body: {
        endpoint: json.endpoint,
        p256dh: json.keys.p256dh,
        auth: json.keys.auth,
      },
    });
  } catch (e) { /* silencioso */ }
}

$("#push-enable-btn").addEventListener("click", async () => {
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      toast("Notificações não autorizadas — você pode ativar depois nas configurações do navegador.");
      $("#push-banner").classList.remove("show");
      return;
    }
    const { public_key } = await api("/api/push/vapid-public-key");
    const reg = await navigator.serviceWorker.ready;
    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    });
    await sendSubscriptionToServer(subscription);
    $("#push-banner").classList.remove("show");
    toast("Notificações ativadas!");
  } catch (err) {
    toast("Não deu pra ativar agora: " + err.message);
  }
});

(function init() {
  const params = new URLSearchParams(window.location.search);

  if (params.get("dev") === "1") localStorage.setItem("metro_dev", "1");
  if (params.get("dev") === "0") localStorage.removeItem("metro_dev");

  const tokenFromUrl = params.get("reset_token");
  if (tokenFromUrl) {
    resetToken = tokenFromUrl;
    showAuthForm("reset");
    return; // não tenta logar automaticamente enquanto a pessoa não redefinir a senha
  }
  if (state.token) {
    bootApp();
  }
})();
