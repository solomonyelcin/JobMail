"use strict";
// All text is inserted with textContent (never innerHTML) so email content cannot inject markup.
const $ = (id) => document.getElementById(id);
const state = { statuses: [], categories: [], emailPage: 1, editing: null };

async function api(method, url, body) {
  const opts = { method, headers: { "X-Requested-With": "JobMail" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (res.status === 401 && url !== "/api/me") { showLogin("Please sign in again."); }
  if (!res.ok) { const e = new Error(data.error || res.statusText); e.status = res.status; e.data = data; throw e; }
  return data;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
function badge(label) { return el("span", "badge " + label, label); }
function fillSelect(sel, values, allLabel) {
  sel.replaceChildren();
  if (allLabel !== undefined) sel.append(new Option(allLabel, ""));
  values.forEach((v) => sel.append(new Option(v[0].toUpperCase() + v.slice(1), v)));
}
function debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ---------- screens ----------
function showLogin(msg) {
  $("app").classList.add("hidden");
  $("userbar").classList.add("hidden");
  $("login").classList.remove("hidden");
  const err = new URLSearchParams(location.search).get("auth_error");
  const text = msg || (err && authErrorText(err));
  $("loginError").textContent = text || "";
  $("loginError").classList.toggle("hidden", !text);
}
function authErrorText(code) {
  return ({
    account_not_allowed: "That Google account is not allowed to use this JobMail instance.",
    no_refresh_token: "Google did not return offline access. Remove JobMail at myaccount.google.com/permissions and sign in again.",
    state_mismatch: "Sign-in expired. Please try again.",
    google_request_failed: "Could not reach Google. Please try again.",
    access_denied: "Sign-in was cancelled.",
  })[code] || "Sign-in failed (" + code + ").";
}

async function boot() {
  const me = await api("GET", "/api/me");
  if (!me.authenticated) return showLogin();
  state.statuses = me.statuses; state.categories = me.categories;
  fillSelect($("appStatus"), state.statuses, "All statuses");
  fillSelect($("emailStatus"), state.statuses, "Any application status");
  fillSelect($("emailCat"), state.categories, "All categories");
  fillSelect($("fStatus"), state.statuses);
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("userbar").classList.remove("hidden");
  setSyncInfo(me.last_sync_at);
  await Promise.all([loadStats(), loadApps(), loadEmails(true)]);
}
function setSyncInfo(ts) { $("syncinfo").textContent = ts ? "Last sync " + fmtDate(ts) : "Not synced yet"; }

// ---------- stats ----------
async function loadStats() {
  const s = await api("GET", "/api/stats");
  const box = $("stats");
  box.replaceChildren();
  const add = (label, n, cls) => { const d = el("div", "stat " + (cls || "")); d.append(el("b", "", String(n)), el("span", "", label)); box.append(d); };
  add("applications", s.total_applications);
  ["applied", "assessment", "interview", "offer", "rejected"].forEach((k) => add(k, s.applications[k] || 0, k));
  add("job emails", s.total_emails);
}

// ---------- applications ----------
async function loadApps() {
  const p = new URLSearchParams({ q: $("appQ").value, status: $("appStatus").value });
  const { items } = await api("GET", "/api/applications?" + p);
  const box = $("appList");
  box.replaceChildren();
  if (!items.length) box.append(el("p", "muted", "No applications yet. Sync Gmail or add one manually."));
  items.forEach((a) => box.append(appCard(a)));
}
function appCard(a) {
  const card = el("div", "item");
  const head = el("div", "head");
  const left = el("div");
  left.append(el("h3", "", a.company + (a.role ? " — " + a.role : "")));
  left.append(el("div", "sub", `${a.email_count} email${a.email_count === 1 ? "" : "s"} · last activity ${fmtDate(a.last_activity_at)}${a.source === "manual" ? " · manual" : ""}`));
  head.append(left, badge(a.status));
  card.append(head);
  if (a.notes) card.append(el("div", "sub", a.notes));
  const actions = el("div", "actions");
  const sel = el("select"); fillSelect(sel, state.statuses); sel.value = a.status;
  sel.addEventListener("change", async () => { await api("PATCH", "/api/applications/" + a.id, { status: sel.value }); refresh(); });
  const edit = el("button", "", "Edit"); edit.addEventListener("click", () => openDialog(a));
  const emails = el("button", "", "View emails");
  emails.addEventListener("click", () => { showTab("emails"); $("emailQ").value = a.company; $("emailStatus").value = ""; loadEmails(true); });
  actions.append(sel, edit, emails);
  card.append(actions);
  return card;
}

// ---------- emails ----------
async function loadEmails(reset) {
  if (reset) state.emailPage = 1;
  const p = new URLSearchParams({
    q: $("emailQ").value, category: $("emailCat").value, status: $("emailStatus").value,
    from: $("emailFrom").value, to: $("emailTo").value, page: state.emailPage,
  });
  const data = await api("GET", "/api/emails?" + p);
  const box = $("emailList");
  if (reset) box.replaceChildren();
  if (reset && !data.items.length) box.append(el("p", "muted", "No emails match."));
  data.items.forEach((e) => box.append(emailCard(e)));
  $("moreBtn").classList.toggle("hidden", state.emailPage * data.page_size >= data.total);
}
function emailCard(e) {
  const card = el("div", "item");
  const head = el("div", "head email-head");
  const left = el("div");
  left.append(el("h3", "", e.subject || "(no subject)"), el("div", "sub", `${e.sender} · ${fmtDate(e.received_at)}`));
  const right = el("div");
  right.append(badge(e.category));
  head.append(left, right);
  card.append(head, el("div", "sub", e.snippet));
  let body = null;
  head.addEventListener("click", async () => {
    if (body) { body.remove(); body = null; return; }
    const full = await api("GET", "/api/emails/" + e.id);
    body = el("div", "body", full.body_text || full.snippet);
    card.append(body);
  });
  return card;
}

// ---------- sync ----------
async function sync() {
  const btn = $("syncBtn");
  btn.disabled = true;
  let checked = 0, stored = 0;
  try {
    for (;;) {
      $("syncMsg").textContent = `Syncing… checked ${checked}, kept ${stored}`;
      const r = await api("POST", "/api/sync", {});
      checked += r.checked; stored += r.stored;
      if (!r.remaining) break;
    }
    $("syncMsg").textContent = `Sync complete: checked ${checked} new messages, kept ${stored} job-related.`;
    setSyncInfo(new Date().toISOString());
    await Promise.all([loadStats(), loadApps(), loadEmails(true)]);
  } catch (err) {
    $("syncMsg").textContent = err.data && err.data.error === "reauth"
      ? "Google access expired. Sign out and sign in again." : "Sync failed: " + err.message;
  } finally { btn.disabled = false; }
}

// ---------- dialog ----------
function openDialog(a) {
  state.editing = a || null;
  $("dlgTitle").textContent = a ? "Edit application" : "Add application";
  $("fCompany").value = a ? a.company : ""; $("fRole").value = a ? a.role : "";
  $("fStatus").value = a ? a.status : "applied"; $("fNotes").value = a ? a.notes : "";
  $("dlgDelete").classList.toggle("hidden", !a);
  $("dlgError").classList.add("hidden");
  $("dlg").showModal();
}
$("dlgForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = { company: $("fCompany").value, role: $("fRole").value, status: $("fStatus").value, notes: $("fNotes").value };
  try {
    if (state.editing) await api("PATCH", "/api/applications/" + state.editing.id, payload);
    else await api("POST", "/api/applications", payload);
    $("dlg").close(); refresh();
  } catch (err) {
    $("dlgError").textContent = err.status === 409 ? "That company and role already exist." : "Could not save: " + err.message;
    $("dlgError").classList.remove("hidden");
  }
});
$("dlgCancel").addEventListener("click", () => $("dlg").close());
$("dlgDelete").addEventListener("click", async () => {
  if (!confirm("Delete this application? Its emails are kept.")) return;
  await api("DELETE", "/api/applications/" + state.editing.id); $("dlg").close(); refresh();
});

// ---------- wiring ----------
function refresh() { loadStats(); loadApps(); loadEmails(true); }
function showTab(which) {
  $("appsView").classList.toggle("hidden", which !== "apps");
  $("emailsView").classList.toggle("hidden", which !== "emails");
  $("tabApps").classList.toggle("active", which === "apps");
  $("tabEmails").classList.toggle("active", which === "emails");
}
$("tabApps").addEventListener("click", () => showTab("apps"));
$("tabEmails").addEventListener("click", () => showTab("emails"));
$("addBtn").addEventListener("click", () => openDialog(null));
$("syncBtn").addEventListener("click", sync);
$("logoutBtn").addEventListener("click", async () => { await api("POST", "/auth/logout", {}); location.href = "/"; });
$("moreBtn").addEventListener("click", () => { state.emailPage += 1; loadEmails(false); });
const reloadApps = debounce(loadApps), reloadEmails = debounce(() => loadEmails(true));
$("appQ").addEventListener("input", reloadApps); $("appStatus").addEventListener("change", loadApps);
["emailQ"].forEach((id) => $(id).addEventListener("input", reloadEmails));
["emailCat", "emailStatus", "emailFrom", "emailTo"].forEach((id) => $(id).addEventListener("change", () => loadEmails(true)));

boot().catch(() => showLogin("Could not reach the server."));
