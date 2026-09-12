/**
 * 管理员用户管理 — 列表、创建、重置密码、调整权限与删除。
 */

import { state } from "./state.js";
import { apiGet, apiPost, apiPatch, apiDelete } from "./api.js";
import { showToast } from "./toast.js";
import { showConfirm } from "./confirm.js";
import { escapeHtml } from "./utils.js";

let resetUserId = null;

function isAdmin() {
  return !!state.user?.is_admin;
}

function syncAdminButtons() {
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.classList.toggle("hidden", !isAdmin());
  });
}

export function openAdminModal() {
  const modal = document.getElementById("admin-modal");
  if (!modal || !isAdmin()) return;
  modal.classList.remove("hidden");
  hideResetPanel();
  loadUsers();
  document.getElementById("admin-new-username")?.focus();
}

export function closeAdminModal() {
  document.getElementById("admin-modal")?.classList.add("hidden");
  hideResetPanel();
}

function hideResetPanel() {
  resetUserId = null;
  document.getElementById("admin-reset-panel")?.classList.add("hidden");
  const form = document.getElementById("admin-reset-form");
  if (form) form.reset();
}

function showResetPanel(userId, username) {
  resetUserId = userId;
  const panel = document.getElementById("admin-reset-panel");
  const hint = document.getElementById("admin-reset-hint");
  if (hint) hint.textContent = `正在重置「${username}」的密码`;
  panel?.classList.remove("hidden");
  document.getElementById("admin-reset-password")?.focus();
}

function validPair(pw, pw2) {
  if (!pw || pw.length < 6) {
    showToast("密码至少需要 6 位", "warning");
    return false;
  }
  if (pw !== pw2) {
    showToast("两次输入的密码不一致", "warning");
    return false;
  }
  return true;
}

async function loadUsers() {
  const list = document.getElementById("admin-user-list");
  if (!list) return;
  try {
    const users = await apiGet("/api/admin/users");
    renderUsers(users);
  } catch (e) {
    list.innerHTML = `<div class="admin-empty">${escapeHtml(e.message || "加载失败")}</div>`;
  }
}

function renderUsers(users) {
  const list = document.getElementById("admin-user-list");
  if (!list) return;
  if (!users.length) {
    list.innerHTML = `<div class="admin-empty">暂无用户</div>`;
    return;
  }
  const me = state.user?.id;
  const adminCount = users.filter((u) => u.is_admin).length;
  list.innerHTML = users.map((u) => {
    const mine = u.id === me;
    const created = (u.created_at || "").slice(0, 10);
    const badge = u.is_admin
      ? `<span class="admin-badge">管理员</span>`
      : `<span class="admin-badge user">用户</span>`;
    const roleBtn = u.is_admin
      ? (adminCount > 1
        ? `<button type="button" class="admin-row-btn" data-act="demote" data-id="${u.id}" data-name="${escapeHtml(u.username)}">取消管理员</button>`
        : "")
      : `<button type="button" class="admin-row-btn" data-act="promote" data-id="${u.id}">设为管理员</button>`;
    const delBtn = mine
      ? ""
      : `<button type="button" class="admin-row-btn danger" data-act="delete" data-id="${u.id}" data-name="${escapeHtml(u.username)}">删除</button>`;
    return `<div class="admin-user-row">
      <div class="admin-user-info">
        <div class="admin-user-name">${escapeHtml(u.username)}${mine ? '<span class="admin-you">（我）</span>' : ""}</div>
        <div class="admin-user-meta">${badge}<span>存档 ${u.slot_count ?? 0}</span>${created ? `<span>${escapeHtml(created)}</span>` : ""}</div>
      </div>
      <div class="admin-user-actions">
        <button type="button" class="admin-row-btn" data-act="reset" data-id="${u.id}" data-name="${escapeHtml(u.username)}">重置密码</button>
        ${roleBtn}
        ${delBtn}
      </div>
    </div>`;
  }).join("");
}

async function handleCreate(event) {
  event.preventDefault();
  const username = document.getElementById("admin-new-username")?.value.trim() || "";
  const password = document.getElementById("admin-new-password")?.value || "";
  const password2 = document.getElementById("admin-new-password2")?.value || "";
  const makeAdmin = !!document.getElementById("admin-new-is-admin")?.checked;
  if (!username) {
    showToast("请输入用户名", "warning");
    return;
  }
  if (!validPair(password, password2)) return;
  const btn = document.getElementById("admin-create-submit");
  if (btn) btn.disabled = true;
  try {
    await apiPost("/api/admin/users", { username, password, is_admin: makeAdmin });
    document.getElementById("admin-create-form")?.reset();
    showToast("账号已创建", "success");
    await loadUsers();
  } catch (e) {
    showToast(e.message || "创建失败", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleReset(event) {
  event.preventDefault();
  if (resetUserId == null) return;
  const password = document.getElementById("admin-reset-password")?.value || "";
  const password2 = document.getElementById("admin-reset-password2")?.value || "";
  if (!validPair(password, password2)) return;
  const btn = document.getElementById("admin-reset-submit");
  if (btn) btn.disabled = true;
  try {
    await apiPatch(`/api/admin/users/${resetUserId}`, { password });
    showToast("密码已重置", "success");
    hideResetPanel();
  } catch (e) {
    showToast(e.message || "重置失败", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleListClick(event) {
  const btn = event.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const id = parseInt(btn.dataset.id, 10);
  if (Number.isNaN(id)) return;
  const name = btn.dataset.name || "";

  if (act === "reset") {
    showResetPanel(id, name);
    return;
  }
  if (act === "promote") {
    try {
      await apiPatch(`/api/admin/users/${id}`, { is_admin: true });
      showToast("已设为管理员", "success");
      await loadUsers();
    } catch (e) {
      showToast(e.message || "操作失败", "error");
    }
    return;
  }
  if (act === "demote") {
    const ok = await showConfirm(`确定取消「${name || "该用户"}」的管理员身份？`);
    if (!ok) return;
    try {
      await apiPatch(`/api/admin/users/${id}`, { is_admin: false });
      showToast("已取消管理员", "success");
      if (id === state.user?.id) {
        state.user.is_admin = false;
        syncAdminButtons();
        closeAdminModal();
        return;
      }
      await loadUsers();
    } catch (e) {
      showToast(e.message || "操作失败", "error");
    }
    return;
  }
  if (act === "delete") {
    const ok = await showConfirm(`确定删除账号「${name}」？其存档、模型配置与背景图将一并删除，且不可恢复。`, true);
    if (!ok) return;
    try {
      await apiDelete(`/api/admin/users/${id}`);
      showToast("账号已删除", "success");
      if (resetUserId === id) hideResetPanel();
      await loadUsers();
    } catch (e) {
      showToast(e.message || "删除失败", "error");
    }
  }
}

export function bindAdminUi() {
  syncAdminButtons();
  if (!isAdmin()) return;

  document.getElementById("admin-btn-slot")?.addEventListener("click", openAdminModal);
  document.getElementById("admin-btn-chat")?.addEventListener("click", openAdminModal);
  document.getElementById("admin-close-btn")?.addEventListener("click", closeAdminModal);
  document.getElementById("admin-modal")?.addEventListener("click", (e) => {
    if (e.target.id === "admin-modal") closeAdminModal();
  });
  document.getElementById("admin-create-form")?.addEventListener("submit", handleCreate);
  document.getElementById("admin-reset-form")?.addEventListener("submit", handleReset);
  document.getElementById("admin-reset-cancel")?.addEventListener("click", hideResetPanel);
  document.getElementById("admin-user-list")?.addEventListener("click", handleListClick);
}
