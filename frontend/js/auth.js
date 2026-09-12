/**
 * 账号视图 — 首次初始化 / 登录 / 邀请码注册 / 注销。
 *
 * 未登录时展示全屏认证卡片；登录成功后刷新页面进入应用。
 */

import { apiGet, apiPost } from "./api.js";
import { state } from "./state.js";

const $ = (id) => document.getElementById(id);

let authStatus = { initialized: true, registration_enabled: false };

function showError(message) {
  const el = $("auth-error");
  if (!el) return;
  el.textContent = message || "";
}

function showAuthView(mode) {
  const view = $("auth-view");
  if (!view) return;
  view.classList.remove("hidden");
  showError("");
  $("auth-setup-form").classList.toggle("hidden", mode !== "setup");
  $("auth-login-form").classList.toggle("hidden", mode !== "login");
  $("auth-register-form").classList.toggle("hidden", mode !== "register");
  $("auth-subtitle").textContent =
    mode === "setup" ? "首次使用：创建管理员账号"
    : mode === "register" ? "使用邀请码创建账号"
    : "登录以继续";
  const registerLink = $("auth-register-link");
  if (registerLink) registerLink.classList.toggle("hidden", !authStatus.registration_enabled);
  const focusTarget =
    mode === "setup" ? $("setup-username") : mode === "register" ? $("register-username") : $("login-username");
  focusTarget?.focus();
}

function hideAuthView() {
  $("auth-view")?.classList.add("hidden");
}

function validPair(pw, pw2) {
  if (!pw || pw.length < 6) {
    showError("密码至少需要 6 位");
    return false;
  }
  if (pw !== pw2) {
    showError("两次输入的密码不一致");
    return false;
  }
  return true;
}

async function submitAuth(path, body, button) {
  if (button) button.disabled = true;
  try {
    await apiPost(path, body, { skipAuthEvent: true });
    window.location.reload();
  } catch (e) {
    showError(e.message || "操作失败，请重试");
    if (button) button.disabled = false;
  }
}

async function handleSetup(event) {
  event.preventDefault();
  const username = $("setup-username").value.trim();
  const password = $("setup-password").value;
  const password2 = $("setup-password2").value;
  if (!username) return showError("请输入用户名");
  if (!validPair(password, password2)) return;
  await submitAuth("/api/auth/setup", { username, password }, $("setup-submit"));
}

async function handleLogin(event) {
  event.preventDefault();
  const username = $("login-username").value.trim();
  const password = $("login-password").value;
  if (!username || !password) return showError("请输入用户名和密码");
  await submitAuth("/api/auth/login", { username, password }, $("login-submit"));
}

async function handleRegister(event) {
  event.preventDefault();
  const username = $("register-username").value.trim();
  const password = $("register-password").value;
  const password2 = $("register-password2").value;
  const inviteCode = $("register-invite").value.trim();
  if (!username) return showError("请输入用户名");
  if (!validPair(password, password2)) return;
  if (!inviteCode) return showError("请输入邀请码");
  await submitAuth(
    "/api/auth/register",
    { username, password, invite_code: inviteCode },
    $("register-submit"),
  );
}

export function bindAuthUi() {
  $("auth-setup-form")?.addEventListener("submit", handleSetup);
  $("auth-login-form")?.addEventListener("submit", handleLogin);
  $("auth-register-form")?.addEventListener("submit", handleRegister);
  $("auth-register-link")?.addEventListener("click", () => showAuthView("register"));
  $("auth-login-link")?.addEventListener("click", () => showAuthView("login"));

  const doLogout = async () => {
    try {
      await apiPost("/api/auth/logout", {});
    } catch (_) { /* 忽略 */ }
    window.location.reload();
  };
  $("logout-btn-slot")?.addEventListener("click", doLogout);
  $("logout-btn-chat")?.addEventListener("click", doLogout);
}

export async function initAuth() {
  try {
    authStatus = await apiGet("/api/auth/status", { skipAuthEvent: true });
  } catch (_) {
    authStatus = { initialized: true, registration_enabled: false };
  }
  if (!authStatus.initialized) {
    showAuthView("setup");
    return null;
  }
  try {
    const user = await apiGet("/api/auth/me", { skipAuthEvent: true });
    state.user = user;
    hideAuthView();
    return user;
  } catch (_) {
    showAuthView("login");
    return null;
  }
}

// 会话过期（任意 API 返回 401）：切回登录视图
window.addEventListener("app-unauthorized", () => {
  showAuthView("login");
  showError("登录已过期，请重新登录");
});
