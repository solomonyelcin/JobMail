"use strict";
// All user/email text is inserted with textContent (never innerHTML), so email content cannot inject markup.
const $ = (id) => document.getElementById(id);
const AUTO_SYNC_MS = 5 * 60 * 1000;

const S = {
  statuses: [], categories: [], view: "board", apps: [], statusFilter: "", sort: "recent",
  emailPage: 1, emailCat: "", unreadOnly: false, editing: null, drawerId: null, syncing: false, analyzing: false,
  lastSync: null, aiEnabled: false, canDraft: false, profile: null,
};

// ---------- utilities ----------
async function api(method, url, body) {
  const opts = { method, headers: { "X-Requested-With": "JobMail" }, credentials: "same-origin" };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (res.status === 401 && url !== "/api/me") showLogin("Please sign in again.");
  if (!res.ok) { const e = new Error(data.error || res.statusText); e.status = res.status; e.data = data; throw e; }
  return data;
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const statusColor = (s) => `var(--${s})`;
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (_) { /* private mode */ } return null; }
function debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function parseTs(iso) { const d = new Date(iso); return isNaN(d) ? null : d; }
function fmtDate(iso) { const d = parseTs(iso); return d ? d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : ""; }
function ago(iso) {
  const d = parseTs(iso); if (!d) return "";
  const m = Math.max(0, Math.round((Date.now() - d) / 60000));
  if (m < 1) return "just now"; if (m < 60) return m + "m ago";
  const h = Math.round(m / 60); if (h < 24) return h + "h ago";
  const days = Math.round(h / 24); if (days < 30) return days + "d ago";
  return fmtDate(iso);
}
function staleDays(a) {
  if (!["applied", "assessment", "interview"].includes(a.status)) return 0;
  const d = parseTs(a.last_activity_at); if (!d) return 0;
  const days = Math.floor((Date.now() - d) / 86400000);
  return days >= 14 ? days : 0;
}
function avatar(name) {
  const a = el("div", "avatar", (name || "?").trim()[0].toUpperCase());
  let h = 0; for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
  a.style.background = `hsl(${h} 55% 46%)`;
  return a;
}
function badge(label) { return el("span", "badge " + label, label); }
function fillSelect(sel, values, allLabel) {
  sel.replaceChildren();
  if (allLabel !== undefined) sel.append(new Option(allLabel, ""));
  values.forEach((v) => sel.append(new Option(cap(v), v)));
}
function terms() { return $("q").value.trim().split(/\s+/).filter(Boolean); }
function appendHighlighted(parent, text, ts) {
  if (!ts.length || !text) { parent.append(text || ""); return; }
  const re = new RegExp("(" + ts.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "ig");
  text.split(re).forEach((part, i) => { if (i % 2) parent.append(el("mark", "", part)); else if (part) parent.append(part); });
}
function toast(msg, kind) {
  const t = el("div", "toast " + (kind || ""), msg);
  $("toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 6000 : 3500);
}
function skeleton(box, n = 3) { box.replaceChildren(); for (let i = 0; i < n; i++) box.append(el("div", "skel")); }

// ---------- theme ----------
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
applyTheme(store("jm-theme"));
$("themeBtn").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark"; applyTheme(next); store("jm-theme", next);
});

// ---------- screens ----------
function authErrorText(code) {
  return ({
    account_not_allowed: "That Google account is not allowed to use this JobMail instance.",
    no_refresh_token: "Google did not return offline access. Remove JobMail at myaccount.google.com/permissions and sign in again.",
    state_mismatch: "Sign-in expired. Please try again.",
    google_request_failed: "Could not reach Google. Please try again.",
    access_denied: "Sign-in was cancelled.",
  })[code] || "Sign-in failed (" + code + ").";
}
function showLogin(msg) {
  $("app").classList.add("hidden"); $("userbar").classList.add("hidden"); $("login").classList.remove("hidden");
  const err = new URLSearchParams(location.search).get("auth_error");
  const text = msg || (err && authErrorText(err));
  $("loginError").textContent = text || ""; $("loginError").classList.toggle("hidden", !text);
}

async function boot() {
  const me = await api("GET", "/api/me");
  if (!me.authenticated) return showLogin();
  S.statuses = me.statuses; S.categories = me.categories;
  S.lastSync = me.last_sync_at ? parseTs(me.last_sync_at) : null;
  S.aiEnabled = !!me.ai_enabled; S.canDraft = !!me.can_draft;
  fillSelect($("fStatus"), S.statuses);
  buildCatChips();
  $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("userbar").classList.remove("hidden");
  setPill(S.syncing ? "syncing" : "ok");
  skeleton($("boardView"), 1);
  await refreshAll();
  maybeAutoSync();
}
function refreshAll() {
  const extra = S.view === "emails" ? loadEmails(true) : S.view === "matches" ? loadMatches() : Promise.resolve();
  return Promise.all([loadStats(), loadApps(), extra]);
}

// ---------- sync pill + auto sync ----------
function setPill(state, text) {
  const pill = $("syncPill");
  pill.className = "pill " + (state === "ok" ? "" : state);
  $("syncText").textContent = text || (state === "syncing" ? "Syncing…" : S.lastSync ? "Synced " + ago(S.lastSync.toISOString()) : "Not synced");
  $("syncBtn").disabled = S.syncing;
}
setInterval(() => { if (!S.syncing && !$("app").classList.contains("hidden")) setPill("ok"); }, 30000);

async function sync(opts = {}) {
  if (S.syncing) return;
  S.syncing = true; setPill("syncing");
  let checked = 0, stored = 0;
  try {
    let first = true;
    for (;;) {
      const r = await api("POST", "/api/sync", first && opts.rescan ? { rescan: true } : {});
      first = false;
      checked += r.checked; stored += r.stored;
      setPill("syncing", `Syncing… ${checked}`);
      if (r.stored > 0) refreshAll();
      if (!r.remaining) break;
    }
    S.lastSync = new Date();
    await refreshAll();
    if (stored > 0) toast(`${stored} new job email${stored === 1 ? "" : "s"} found`, "ok");
    else if (!opts.silent) toast("Up to date", "ok");
    setPill("ok");
    S.syncing = false;
    await runAnalysis();
  } catch (err) {
    setPill("error", "Sync failed");
    if (err.data && err.data.error === "reauth") { showLogin("Google access expired. Please sign in again."); }
    else if (!opts.silent) toast("Sync failed: " + err.message, "error");
  } finally { S.syncing = false; $("syncBtn").disabled = false; }
}
function maybeAutoSync() {
  if (document.visibilityState !== "visible" || S.syncing || $("app").classList.contains("hidden")) return;
  if (!S.lastSync || Date.now() - S.lastSync > AUTO_SYNC_MS) sync({ silent: true });
}
setInterval(maybeAutoSync, 60 * 1000);
document.addEventListener("visibilitychange", maybeAutoSync);
$("syncBtn").addEventListener("click", () => sync({}));

// ---------- stats ----------
async function loadStats() {
  const s = await api("GET", "/api/stats");
  const box = $("funnel"); box.replaceChildren();
  const chip = (label, n, status, color) => {
    const b = el("button", "chip-stat" + (S.statusFilter === status ? " active" : ""));
    b.style.setProperty("--c", color);
    b.append(el("b", "", String(n)), el("span", "", label));
    b.addEventListener("click", () => { S.statusFilter = S.statusFilter === status ? "" : status; if (!["board", "list"].includes(S.view)) setView("board"); loadStats(); loadApps(); });
    box.append(b);
  };
  $("unreadBadge").textContent = String(s.unread); $("unreadBadge").classList.toggle("hidden", !s.unread);
  chip("All", s.total_applications, "", "var(--brand)");
  ["saved", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"].forEach((k) => {
    if (k === "withdrawn" && !(s.applications[k])) return;
    chip(k, s.applications[k] || 0, k, statusColor(k));
  });

  const a = s.applications, ins = $("insights"); ins.replaceChildren();
  const card = (k, v, sub) => { const c = el("div", "insight"); c.append(el("div", "k", k), el("div", "v", v)); if (sub) c.append(el("div", "s", sub)); ins.append(c); return c; };
  const active = (a.applied || 0) + (a.assessment || 0) + (a.interview || 0);
  card("Active applications", String(active), `${s.total_emails} job emails tracked`);
  const sent = (a.applied || 0) + (a.assessment || 0) + (a.interview || 0) + (a.offer || 0) + (a.rejected || 0);
  const replied = sent - (a.applied || 0);
  card("Response rate", sent ? Math.round((replied / sent) * 100) + "%" : "–", sent ? `${replied} of ${sent} moved past “applied”` : "Apply to get started");
  const st = card("Needs follow-up", String(s.stale), "quiet for 14+ days");
  if (s.strong_matches) { const m = card("Strong job matches", String(s.strong_matches), "fit score 70+ — tap to view"); m.style.cursor = "pointer"; m.addEventListener("click", () => setView("matches")); }
  if (s.stale) { st.style.cursor = "pointer"; st.addEventListener("click", () => { S.sort = "recent"; $("sort").value = "recent"; setView("list"); toast("Oldest activity is at the bottom"); }); }
  const w = card("Emails per week", String(s.weekly.reduce((n, x) => n + x.count, 0)), "last 8 weeks");
  w.append(sparkline(s.weekly));
}
function sparkline(weekly) {
  const NS = "http://www.w3.org/2000/svg", max = Math.max(1, ...weekly.map((x) => x.count));
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 160 38"); svg.setAttribute("preserveAspectRatio", "none");
  weekly.forEach((x, i) => {
    const h = Math.max(2, (x.count / max) * 34);
    const r = document.createElementNS(NS, "rect");
    r.setAttribute("x", String(i * 20 + 2)); r.setAttribute("y", String(36 - h)); r.setAttribute("width", "15"); r.setAttribute("height", String(h));
    r.setAttribute("rx", "3"); r.setAttribute("fill", "currentColor"); r.setAttribute("opacity", x.count ? "0.9" : "0.25");
    const t = document.createElementNS(NS, "title"); t.textContent = `Week of ${x.week_start}: ${x.count}`; r.append(t);
    svg.append(r);
  });
  return svg;
}

// ---------- applications ----------
async function loadApps() {
  const p = new URLSearchParams({ status: S.statusFilter, sort: S.sort });
  if (S.view !== "emails") p.set("q", $("q").value);
  const { items } = await api("GET", "/api/applications?" + p);
  S.apps = items; renderApps();
}
function appCard(a) {
  const card = el("div", "card"); card.tabIndex = 0; card.dataset.id = a.id;
  card.append(avatar(a.company));
  const body = el("div");
  const t = el("div", "t"); appendHighlighted(t, a.company, terms()); body.append(t);
  if (a.role) { const r = el("div", "r"); appendHighlighted(r, a.role, terms()); body.append(r); }
  const m = el("div", "m");
  if (S.view === "list") m.append(badge(a.status));
  m.append(el("span", "", ago(a.last_activity_at)));
  if (a.email_count) m.append(el("span", "tag", `✉ ${a.email_count}`));
  if (a.source === "manual") m.append(el("span", "tag", "manual"));
  const sd = staleDays(a); if (sd) m.append(el("span", "tag warn", `⏳ ${sd}d quiet`));
  body.append(m); card.append(body);
  card.addEventListener("click", () => openDrawer(a.id));
  card.addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawer(a.id); });
  card.draggable = true;
  card.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; card.classList.add("dragging"); });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));
  return card;
}
function renderApps() {
  if (S.view === "board") renderBoard(); else if (S.view === "list") renderList();
}
function renderBoard() {
  const box = $("boardView"); box.replaceChildren();
  const cols = S.statuses.filter((s) => s !== "withdrawn" || S.apps.some((a) => a.status === s));
  cols.forEach((st) => {
    const col = el("div", "col"); col.style.setProperty("--c", statusColor(st));
    const items = S.apps.filter((a) => a.status === st);
    const head = el("div", "col-head"); head.append(el("span", "dot"), el("span", "", st), el("span", "count", String(items.length)));
    col.append(head);
    if (!items.length) col.append(el("div", "col-empty", "Drop here"));
    items.forEach((a) => col.append(appCard(a)));
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault(); col.classList.remove("over");
      const id = Number(e.dataTransfer.getData("text/plain")); const a = S.apps.find((x) => x.id === id);
      if (a && a.status !== st) await setStatus(a, st);
    });
    box.append(col);
  });
  if (!S.apps.length) box.prepend(el("div", "empty", "No applications yet. Sync is running automatically, or press “Add”."));
}
function renderList() {
  const box = $("listView"); box.replaceChildren();
  box.classList.add("list-wide");
  if (!S.apps.length) { box.classList.remove("list-wide"); box.append(el("div", "empty", "No applications match.")); return; }
  S.apps.forEach((a) => box.append(appCard(a)));
}
async function setStatus(a, status) {
  const prev = a.status; a.status = status; renderApps();
  try { await api("PATCH", "/api/applications/" + a.id, { status }); toast(`${a.company} → ${cap(status)}`, "ok"); loadStats(); if (S.drawerId === a.id) openDrawer(a.id, true); }
  catch (e) { a.status = prev; renderApps(); toast("Could not update status", "error"); }
}

// ---------- drawer ----------
async function openDrawer(id, keepScroll) {
  S.drawerId = id;
  const drawer = $("drawer");
  let a;
  try { a = await api("GET", "/api/applications/" + id); } catch (_) { return; }
  const body = $("drawerBody"); body.replaceChildren();
  const inner = el("div", "drawer-inner");

  const head = el("div", "drawer-head"); head.append(avatar(a.company));
  const title = el("div"); title.append(el("h2", "", a.company), el("div", "muted", a.role || "No role detected"));
  const close = el("button", "btn", "✕"); close.setAttribute("aria-label", "Close"); close.addEventListener("click", closeDrawer);
  head.append(title, close); inner.append(head);

  inner.append(el("h4", "", "Status"));
  const row = el("div", "status-row");
  S.statuses.forEach((st) => {
    const b = el("button", "status-btn" + (a.status === st ? " active" : ""), st); b.style.setProperty("--c", statusColor(st));
    b.addEventListener("click", () => { const known = S.apps.find((x) => x.id === a.id) || a; setStatus(known, st); });
    row.append(b);
  });
  inner.append(row);
  inner.append(el("div", "muted", `First seen ${fmtDate(a.first_seen_at)} · last activity ${ago(a.last_activity_at)}`));

  inner.append(el("h4", "", "Notes"));
  const notes = el("textarea"); notes.rows = 3; notes.maxLength = 2000; notes.value = a.notes || ""; notes.placeholder = "Recruiter name, salary, next steps…";
  notes.addEventListener("blur", async () => {
    if (notes.value === (a.notes || "")) return;
    try { await api("PATCH", "/api/applications/" + a.id, { notes: notes.value }); a.notes = notes.value; toast("Notes saved", "ok"); loadApps(); } catch (_) { toast("Could not save notes", "error"); }
  });
  inner.append(notes);

  const actions = el("div", "row");
  const edit = el("button", "btn", "Edit details"); edit.addEventListener("click", () => openDialog(a));
  const del = el("button", "btn danger", "Delete"); del.addEventListener("click", async () => {
    if (!confirm("Delete this application? Its emails are kept.")) return;
    await api("DELETE", "/api/applications/" + a.id); closeDrawer(); refreshAll(); toast("Application deleted");
  });
  actions.append(edit, el("span", "spacer"), del); inner.append(actions);

  inner.append(el("h4", "", `Email timeline (${a.emails.length})`));
  const tl = el("div", "timeline");
  if (!a.emails.length) tl.append(el("div", "muted", "No emails linked yet."));
  a.emails.forEach((e) => {
    const it = el("div", "tl-item"); it.style.setProperty("--c", statusColor(e.category));
    it.append(el("div", "when", `${fmtDate(e.received_at)} · ${cap(e.category)}`));
    const subj = el("div", "subj", e.subject || "(no subject)"); it.append(subj);
    let bodyEl = null;
    subj.addEventListener("click", async () => {
      if (bodyEl) { bodyEl.remove(); bodyEl = null; return; }
      const full = await api("GET", "/api/emails/" + e.id);
      bodyEl = el("div", "email-body", full.body_text || full.snippet); it.append(bodyEl);
    });
    tl.append(it);
  });
  inner.append(tl);

  body.append(inner);
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); $("drawerBackdrop").classList.remove("hidden");
  if (!keepScroll) drawer.scrollTop = 0;
}
function closeDrawer() {
  S.drawerId = null; $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); $("drawerBackdrop").classList.add("hidden");
}
$("drawerBackdrop").addEventListener("click", closeDrawer);

// ---------- emails ----------
function buildCatChips() {
  const box = $("catChips"); box.replaceChildren();
  ["", ...S.categories].forEach((c) => {
    const b = el("button", "chip" + (S.emailCat === c ? " active" : ""), c || "all");
    b.addEventListener("click", () => { S.emailCat = c; buildCatChips(); loadEmails(true); });
    box.append(b);
  });
  const u = el("button", "chip" + (S.unreadOnly ? " active" : ""), "unread");
  u.addEventListener("click", () => { S.unreadOnly = !S.unreadOnly; buildCatChips(); loadEmails(true); });
  box.append(u);
}
async function loadEmails(reset) {
  if (reset) S.emailPage = 1;
  const p = new URLSearchParams({ q: $("q").value, category: S.emailCat, from: $("emailFrom").value, to: $("emailTo").value, page: S.emailPage });
  if (S.statusFilter) p.set("status", S.statusFilter);
  if (S.unreadOnly) p.set("unread", "1");
  const box = $("emailList");
  if (reset) skeleton(box);
  const data = await api("GET", "/api/emails?" + p);
  if (reset) box.replaceChildren();
  if (reset && !data.items.length) box.append(el("div", "empty", "No emails match your filters."));
  data.items.forEach((e) => box.append(emailCard(e)));
  $("moreBtn").classList.toggle("hidden", S.emailPage * data.page_size >= data.total);
}
function emailCard(e) {
  const card = el("div", "email" + (e.is_unread ? " unread" : "")), ts = terms();
  const head = el("div", "head"); const left = el("div");
  const h = el("h3"); if (e.is_unread) h.append(el("span", "unread-dot")); appendHighlighted(h, e.subject || "(no subject)", ts);
  const sub = el("div", "sub"); appendHighlighted(sub, e.sender, ts); sub.append(" · " + ago(e.received_at));
  const right = el("div", "badges");
  if (e.fit_score !== null && e.fit_score !== undefined) right.append(fitBadge(e.fit_score));
  right.append(badge(e.category));
  left.append(h, sub); head.append(left, right); card.append(head);
  if (e.ai_summary) { const ai = el("div", "ai"); appendHighlighted(ai, e.ai_summary, ts); card.append(ai); }
  const sn = el("div", "snip"); appendHighlighted(sn, e.snippet, ts); card.append(sn);
  let body = null;
  const actions = el("div", "actions");
  if (e.application_id) {
    const open = el("button", "link", "Open application" + (e.company ? " · " + e.company : ""));
    open.addEventListener("click", () => openDrawer(e.application_id)); actions.append(open);
  }
  if (S.aiEnabled) { const reply = el("button", "link", "✦ Reply with AI"); reply.addEventListener("click", () => openCompose(e)); actions.append(reply); }
  const not = el("button", "link", "Not job-related");
  not.addEventListener("click", async () => {
    if (!confirm("Remove this email from JobMail? It will not be imported again.")) return;
    await api("DELETE", "/api/emails/" + e.id); card.remove(); toast("Email removed"); loadStats();
  });
  actions.append(not); card.append(actions);
  head.addEventListener("click", async () => {
    if (body) { body.remove(); body = null; return; }
    const full = await api("GET", "/api/emails/" + e.id);
    body = el("div", "email-body"); appendHighlighted(body, full.body_text || full.snippet, ts); card.insertBefore(body, actions);
  });
  return card;
}

// ---------- add / edit dialog ----------
function openDialog(a) {
  S.editing = a || null;
  $("dlgTitle").textContent = a ? "Edit application" : "Add application";
  $("fCompany").value = a ? a.company : ""; $("fRole").value = a ? a.role : "";
  $("fStatus").value = a ? a.status : "applied"; $("fNotes").value = a ? a.notes : "";
  $("dlgError").classList.add("hidden"); $("dlg").showModal();
}
$("dlgForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = { company: $("fCompany").value, role: $("fRole").value, status: $("fStatus").value, notes: $("fNotes").value };
  try {
    if (S.editing) await api("PATCH", "/api/applications/" + S.editing.id, payload); else await api("POST", "/api/applications", payload);
    $("dlg").close(); toast("Saved", "ok"); await refreshAll(); if (S.drawerId) openDrawer(S.drawerId, true);
  } catch (err) {
    $("dlgError").textContent = err.status === 409 ? "That company and role already exist." : "Could not save: " + err.message;
    $("dlgError").classList.remove("hidden");
  }
});
$("dlgCancel").addEventListener("click", () => $("dlg").close());
$("addBtn").addEventListener("click", () => openDialog(null));

// ---------- AI analysis ----------
async function runAnalysis(opts = {}) {
  if (!S.aiEnabled || S.analyzing || S.syncing) return;
  S.analyzing = true;
  let analyzed = 0, errors = 0, first = true;
  try {
    for (;;) {
      const r = await api("POST", "/api/ai/analyze", first ? opts : {});
      first = false;
      analyzed += r.analyzed; errors += r.errors;
      if (r.remaining) setPill("syncing", `AI sorting… ${r.remaining} left`);
      if (r.analyzed || r.removed) refreshAll();
      if (!r.remaining || r.analyzed + r.removed === 0) break;
    }
    await refreshAll();
    if (analyzed) toast(`AI sorted ${analyzed} email${analyzed === 1 ? "" : "s"}`, "ok");
    if (errors) toast(`${errors} email${errors === 1 ? "" : "s"} could not be analysed. Use “Re-score” on the Profile page to retry.`, "error");
  } catch (err) { toast("AI analysis failed: " + err.message, "error"); }
  finally { S.analyzing = false; setPill("ok"); }
}

// ---------- matches ----------
function fitBadge(score) {
  return el("span", "fit " + (score >= 75 ? "high" : score >= 50 ? "mid" : "low"), String(score));
}
async function loadMatches() {
  const box = $("matchesList"); skeleton(box, 2);
  const { items } = await api("GET", "/api/matches");
  box.replaceChildren();
  $("matchesNote").textContent = !S.aiEnabled
    ? "Turn on AI (Profile page) to score job openings against your profile."
    : items.length ? `${items.length} scored opening${items.length === 1 ? "" : "s"}, best first.` : "No scored openings yet. They appear after the next sync.";
  items.forEach((m) => box.append(matchCard(m)));
}
function matchCard(m) {
  const card = el("div", "match");
  const sc = el("div", "score"); sc.style.setProperty("--p", String(m.fit_score));
  sc.style.setProperty("--c", m.fit_score >= 75 ? "var(--offer)" : m.fit_score >= 50 ? "var(--interview)" : "var(--withdrawn)");
  sc.append(el("span", "", String(m.fit_score))); card.append(sc);
  const body = el("div");
  const title = m.role ? m.role + (m.company ? " at " + m.company : "") : (m.subject || "(no subject)");
  const h = el("h3"); if (m.is_unread) h.append(el("span", "unread-dot")); h.append(title); body.append(h);
  if (m.fit_reason) body.append(el("div", "why", m.fit_reason));
  if (m.ai_summary) body.append(el("div", "muted", m.ai_summary));
  body.append(el("div", "muted small", `${m.sender} · ${ago(m.received_at)} · ${cap(m.category)}`));
  const actions = el("div", "row wrap");
  const reply = el("button", "btn primary", "✦ Reply / apply with AI"); reply.addEventListener("click", () => openCompose(m));
  const view = el("button", "btn", "View email");
  view.addEventListener("click", () => { S.emailCat = ""; $("q").value = m.subject || ""; setView("emails"); });
  actions.append(reply, view); body.append(actions); card.append(body);
  return card;
}

// ---------- profile & resume ----------
async function loadProfile() {
  const p = await api("GET", "/api/profile"); S.profile = p;
  $("pName").value = p.full_name; $("pText").value = p.profile_text;
  const info = $("resumeInfo");
  if (p.resume) {
    info.textContent = `${p.resume.filename} · ${Math.max(1, Math.round(p.resume.size / 1024))} KB · updated ${ago(p.resume.updated_at)}` +
      (p.resume.text_extracted ? "" : ". Could not read text from this file, so paste a short profile below for the AI.");
  } else info.textContent = "No resume uploaded.";
  $("resumeDownload").classList.toggle("hidden", !p.resume); $("resumeDelete").classList.toggle("hidden", !p.resume);
  $("aiStatus").textContent = (S.aiEnabled
    ? "AI is on: emails are sorted, openings are scored against your profile and replies can be drafted."
    : "AI is off. To enable it, add an ANTHROPIC_API_KEY environment variable on your host (see docs/DEPLOYMENT.md).") +
    (S.canDraft ? "" : " Reply drafts need one more Google permission.");
  $("reanalyzeBtn").classList.toggle("hidden", !S.aiEnabled);
  $("reconnectBtn").classList.toggle("hidden", S.canDraft);
}
$("pSave").addEventListener("click", async () => {
  try {
    await api("PUT", "/api/profile", { full_name: $("pName").value, profile_text: $("pText").value });
    $("pMsg").textContent = "Saved."; toast("Profile saved", "ok");
    if (S.aiEnabled) toast("Use “Re-score all emails” to apply it to existing emails");
  } catch (e) { toast("Could not save profile", "error"); }
});
$("resumeFile").addEventListener("change", async () => {
  const f = $("resumeFile").files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { await api("POST", "/api/resume", fd); toast("Resume uploaded", "ok"); await loadProfile(); }
  catch (e) {
    toast(({ unsupported_type: "Use a PDF, DOCX or TXT file.", too_large: "File is larger than 2 MB.", not_a_pdf: "That is not a valid PDF.",
      not_a_docx: "That is not a valid DOCX.", empty_file: "The file is empty." })[e.message] || "Upload failed", "error");
  }
  $("resumeFile").value = "";
});
$("resumeDelete").addEventListener("click", async () => {
  if (!confirm("Remove your resume? Reply drafts will no longer attach it.")) return;
  await api("DELETE", "/api/resume"); toast("Resume removed"); loadProfile();
});
$("reanalyzeBtn").addEventListener("click", () => runAnalysis({ reanalyze: true, retry: true }));
$("rescanBtn").addEventListener("click", () => { toast("Rescanning the last 3 months…"); sync({ rescan: true }); });

// ---------- reply with AI ----------
const C = { emailId: null };
function composeReset() {
  ["composeForm", "composeDone", "cRewrite", "cCreate"].forEach((id) => $(id).classList.add("hidden"));
  $("composeStatus").classList.remove("hidden"); $("composeStatus").textContent = "Writing a draft…"; $("composeWarn").classList.add("hidden");
}
async function openCompose(e) {
  if (!S.aiEnabled) { toast("AI is off. See the Profile page.", "error"); return; }
  C.emailId = e.id; composeReset(); $("cInstr").value = ""; $("composeDlg").showModal();
  await generateDraft("");
}
async function generateDraft(instructions) {
  composeReset();
  try {
    const r = await api("POST", `/api/emails/${C.emailId}/compose`, { instructions });
    $("cTo").value = r.to; $("cSubject").value = r.subject; $("cBody").value = r.body;
    $("cAttach").checked = r.has_resume; $("cAttach").disabled = !r.has_resume;
    $("cAttachLabel").textContent = r.has_resume ? "Attach my resume" : "Attach my resume (upload one on the Profile page first)";
    const warns = [];
    if (r.no_reply) warns.push("This sender looks like a no-reply address, so a reply may never be read.");
    if (!r.to) warns.push("No reply address found. Enter one in the To field.");
    $("composeWarn").textContent = warns.join(" "); $("composeWarn").classList.toggle("hidden", !warns.length);
    $("composeStatus").classList.add("hidden");
    ["composeForm", "cRewrite", "cCreate"].forEach((id) => $(id).classList.remove("hidden"));
  } catch (err) { $("composeStatus").textContent = "Could not write a draft right now. Please try again."; }
}
$("cRewrite").addEventListener("click", () => generateDraft($("cInstr").value));
$("cClose").addEventListener("click", () => $("composeDlg").close());
$("cCreate").addEventListener("click", async () => {
  $("cCreate").disabled = true;
  try {
    const r = await api("POST", `/api/emails/${C.emailId}/draft`, {
      to: $("cTo").value, subject: $("cSubject").value, body: $("cBody").value, attach_resume: $("cAttach").checked,
    });
    ["composeForm", "cRewrite", "cCreate"].forEach((id) => $(id).classList.add("hidden"));
    $("composeDone").classList.remove("hidden");
    const ok = typeof r.url === "string" && r.url.startsWith("https://mail.google.com/");
    $("composeLink").href = ok ? r.url : "https://mail.google.com/mail/u/0/#drafts";
    toast(r.attached ? "Draft created with your resume attached" : "Draft created", "ok");
  } catch (err) {
    $("composeWarn").textContent = err.data && err.data.error === "reauth_scope"
      ? "JobMail needs permission to create drafts. Open the Profile page and use “Re-connect Google”."
      : "Could not create the draft: " + err.message;
    $("composeWarn").classList.remove("hidden");
  } finally { $("cCreate").disabled = false; }
});

// ---------- views & wiring ----------
const VIEWS = {
  board: ["boardView", "viewBoard"], list: ["listView", "viewList"], emails: ["emailsView", "viewEmails"],
  matches: ["matchesView", "viewMatches"], profile: ["profileView", "viewProfile"],
};
function setView(v, load = true) {
  S.view = v;
  Object.entries(VIEWS).forEach(([k, [vid, bid]]) => { $(vid).classList.toggle("hidden", k !== v); $(bid).classList.toggle("active", k === v); });
  const apps = v === "board" || v === "list";
  $("sort").classList.toggle("hidden", !apps); $("addBtn").classList.toggle("hidden", !apps);
  $("searchBox").classList.toggle("hidden", !(apps || v === "emails"));
  $("q").placeholder = v === "emails" ? "Search emails…  ( press / )" : "Search applications…  ( press / )";
  if (!load) return;
  ({ board: loadApps, list: loadApps, emails: () => loadEmails(true), matches: loadMatches, profile: loadProfile })[v]();
}
$("viewBoard").addEventListener("click", () => setView("board"));
$("viewList").addEventListener("click", () => setView("list"));
$("viewEmails").addEventListener("click", () => setView("emails"));
$("viewMatches").addEventListener("click", () => setView("matches"));
$("viewProfile").addEventListener("click", () => setView("profile"));
$("sort").addEventListener("change", () => { S.sort = $("sort").value; loadApps(); });
const onSearch = debounce(() => (S.view === "emails" ? loadEmails(true) : loadApps()));
$("q").addEventListener("input", onSearch);
["emailFrom", "emailTo"].forEach((id) => $(id).addEventListener("change", () => loadEmails(true)));
$("moreBtn").addEventListener("click", () => { S.emailPage += 1; loadEmails(false); });
$("logoutBtn").addEventListener("click", async () => { await api("POST", "/auth/logout", {}); location.href = "/"; });
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); $("q").focus(); }
  if (e.key === "Escape") closeDrawer();
});

setView("board", false);
boot().catch(() => showLogin("Could not reach the server."));
