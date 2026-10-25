"use strict";
// All user/email text is inserted with textContent (never innerHTML), so email content cannot inject markup.
const $ = (id) => document.getElementById(id);
const AUTO_SYNC_MS = 5 * 60 * 1000;

const S = {
  statuses: [], categories: [], view: "dashboard", apps: [], statusFilter: "", sort: "recent",
  emailPage: 1, emailCat: "", unreadOnly: false, emailReq: 0, selectedId: null, editing: null, drawerId: null,
  syncing: false, analyzing: false, lastSync: null, aiEnabled: false, canDraft: false, profile: null, stats: null,
  aiWarned: {},
};

// ---------- icons (stroke style, 24x24) ----------
const ICONS = {
  menu: "M3 6h18|M3 12h18|M3 18h18",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z|M21 21l-4.3-4.3",
  refresh: "M23 4v6h-6|M20.5 15a9 9 0 1 1-2.1-9.4L23 10",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2|M5.5 5.1L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z",
  mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z|M22 6l-10 7L2 6",
  star: "M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21.1 7 14.2 2 9.3l6.9-1z",
  board: "M4 4h6v16H4z|M14 4h6v10h-6z",
  list: "M8 6h13|M8 12h13|M8 18h13|M3 6h.01|M3 12h.01|M3 18h.01",
  dashboard: "M3 3h7v9H3z|M14 3h7v5h-7z|M14 12h7v9h-7z|M3 16h7v5H3z",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2|M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  plus: "M12 5v14|M5 12h14",
  palette: "M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.8 1.2-1.6-.4-.9.1-1.9 1.2-1.9H17a4 4 0 0 0 4-4c0-5-4-9-9-9z|M7.5 11.5h.01|M10 7.5h.01|M14.5 7.5h.01",
  help: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z|M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3|M12 17h.01",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4|M7 10l5 5 5-5|M12 15V3",
  x: "M18 6L6 18|M6 6l12 12",
  back: "M19 12H5|M12 19l-7-7 7-7",
  reply: "M9 14L4 9l5-5|M20 20v-7a4 4 0 0 0-4-4H4",
  ban: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z|M5.6 5.6l12.8 12.8",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z|M19 16v4|M17 18h4",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4|M16 17l5-5-5-5|M21 12H9",
  check: "M20 6L9 17l-5-5",
  alert: "M12 3l10 18H2z|M12 10v5|M12 18h.01",
};
function icon(name) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  (ICONS[name] || "").split("|").forEach((d) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); svg.append(p); });
  return svg;
}
function ic(name) { const s = document.createElement("span"); s.dataset.icon = name; s.append(icon(name)); return s; }
function hydrateIcons(root) { (root || document).querySelectorAll("[data-icon]").forEach((n) => { if (!n.firstChild) n.append(icon(n.dataset.icon)); }); }

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
function fmtShort(iso) {
  const d = parseTs(iso); if (!d) return "";
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return d.toLocaleDateString(undefined, { year: "2-digit", month: "short", day: "numeric" });
}
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
function senderName(raw) {
  const m = /^\s*"?([^"<]*?)"?\s*<([^>]+)>/.exec(raw || "");
  return (m && m[1].trim()) || (m && m[2]) || (raw || "").trim();
}
function avatar(name) {
  const a = el("div", "avatar", ((name || "?").trim()[0] || "?").toUpperCase());
  let h = 0; for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) % 360;
  a.style.background = `hsl(${h} 50% 42%)`;
  return a;
}
function chip(label) { return el("span", "chip " + label, label); }
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
  setTimeout(() => t.remove(), kind === "error" ? 7000 : 3500);
}
function skeleton(box, n = 3) { box.replaceChildren(); for (let i = 0; i < n; i++) box.append(el("div", "skel")); }
function iconBtn(name, title, fn) {
  const b = el("button", "icon-btn"); b.title = title; b.setAttribute("aria-label", title); b.append(icon(name));
  b.addEventListener("click", fn); return b;
}
function emptyState(iconName, title, text, btnLabel, btnFn) {
  const d = el("div", "empty"); d.append(ic(iconName), el("b", "", title), el("div", "", text));
  if (btnLabel) { const b = el("button", "btn primary", btnLabel); b.style.marginTop = "12px"; b.addEventListener("click", btnFn); d.append(b); }
  return d;
}
const isNarrow = () => matchMedia("(max-width: 900px)").matches;

// ---------- themes & density (Gmail-style) ----------
const THEMES = [
  { id: "auto", name: "Auto", sw: "linear-gradient(135deg,#f6f8fc 50%,#1e1f20 50%)" },
  { id: "light", name: "Light", sw: "#ffffff" },
  { id: "dark", name: "Dark", sw: "#1e1f20" },
  { id: "ocean", name: "Ocean", sw: "linear-gradient(135deg,#d6efff,#9fd5f1)" },
  { id: "forest", name: "Forest", sw: "linear-gradient(135deg,#e3f3e8,#a9dbb9)" },
  { id: "sunset", name: "Sunset", sw: "linear-gradient(135deg,#ffeedf,#f7bfd0)" },
  { id: "lavender", name: "Lavender", sw: "linear-gradient(135deg,#f1ebff,#c9b9f3)" },
  { id: "midnight", name: "Midnight", sw: "linear-gradient(135deg,#0a0f1f,#2a3f7a)" },
];
const DENSITIES = [["default", "Default", "Roomy rows"], ["comfortable", "Comfortable", "A bit tighter"], ["compact", "Compact", "Fit more on screen"]];
const THEME_COLORS = { light: "#f6f8fc", dark: "#131314", ocean: "#d6efff", forest: "#e3f3e8", sunset: "#ffeedf", lavender: "#f1ebff", midnight: "#0a0f1f" };
function applyTheme(id) {
  const root = document.documentElement;
  if (!id || id === "auto" || !THEMES.some((t) => t.id === id)) { delete root.dataset.theme; id = "auto"; } else root.dataset.theme = id;
  const dark = id === "dark" || id === "midnight" || (id === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]').setAttribute("content", THEME_COLORS[id] || (dark ? "#131314" : "#f6f8fc"));
  store("jm-theme", id); buildThemePopover();
}
function applyDensity(d) {
  const root = document.documentElement;
  if (!d || d === "default") delete root.dataset.density; else root.dataset.density = d;
  store("jm-density", d || "default"); buildThemePopover();
}
function buildThemePopover() {
  const cur = store("jm-theme") || "auto", dens = store("jm-density") || "default";
  const sw = $("swatches"); sw.replaceChildren();
  THEMES.forEach((t) => {
    const b = el("button", "swatch" + (cur === t.id ? " active" : "")); b.title = t.name;
    const i = el("i"); i.style.setProperty("--sw", t.sw); b.append(i, t.name);
    b.addEventListener("click", () => applyTheme(t.id)); sw.append(b);
  });
  const dr = $("densityRow"); dr.replaceChildren();
  DENSITIES.forEach(([id, name, hint]) => {
    const b = el("button", dens === id ? "active" : ""); b.append(el("span", "", name), el("span", "muted small", " · " + hint));
    b.addEventListener("click", () => applyDensity(id)); dr.append(b);
  });
}
$("themeBtn").addEventListener("click", (e) => { e.stopPropagation(); $("themePop").classList.toggle("hidden"); });
document.addEventListener("click", (e) => { if (!$("themePop").contains(e.target) && !$("themeBtn").contains(e.target)) $("themePop").classList.add("hidden"); });

// ---------- sidebar & overlays ----------
function syncBackdrop() {
  const pane = $("emailPane");
  const show = (isNarrow() && $("sidebar").classList.contains("open")) || S.drawerId !== null ||
    (pane.classList.contains("overlay") && pane.classList.contains("open"));
  $("backdrop").classList.toggle("hidden", !show);
}
function toggleSidebar() {
  const sb = $("sidebar");
  if (isNarrow()) sb.classList.toggle("open");
  else { sb.classList.toggle("collapsed"); store("jm-side", sb.classList.contains("collapsed") ? "1" : "0"); }
  syncBackdrop();
}
function closeSidebarIfNarrow() { if (isNarrow()) { $("sidebar").classList.remove("open"); syncBackdrop(); } }
$("menuBtn").addEventListener("click", toggleSidebar);
$("backdrop").addEventListener("click", () => {
  $("sidebar").classList.remove("open"); closeDrawer();
  if ($("emailPane").classList.contains("overlay")) closeEmailPane(); syncBackdrop();
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (b) { setView(b.dataset.view); closeSidebarIfNarrow(); }
});

// ---------- signed-out screen ----------
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
  $("appShell").classList.add("hidden"); $("login").classList.remove("hidden");
  const err = new URLSearchParams(location.search).get("auth_error");
  const text = msg || (err && authErrorText(err));
  $("loginError").textContent = text || ""; $("loginError").classList.toggle("hidden", !text);
}

// ---------- views ----------
const VIEW_TYPE = { dashboard: "dashboard", inbox: "emails", unread: "emails", matches: "matches", board: "apps", list: "apps", profile: "profile" };
const viewType = (k) => (k.startsWith("label:") ? "emails" : VIEW_TYPE[k] || "dashboard");
function setView(key, load = true) {
  S.view = key; const type = viewType(key);
  S.unreadOnly = key === "unread"; S.emailCat = key.startsWith("label:") ? key.slice(6) : "";
  ["dashboard", "emails", "matches", "apps", "profile"].forEach((t) => $(t + "View").classList.toggle("hidden", t !== type));
  $("boardView").classList.toggle("hidden", key !== "board"); $("listView").classList.toggle("hidden", key !== "list");
  $("segBoard").classList.toggle("active", key === "board"); $("segList").classList.toggle("active", key === "list");
  $("appsTitle").textContent = key === "list" ? "Applications" : "Board";
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === key));
  $("emailTitle").textContent = key === "unread" ? "Unread" : S.emailCat ? cap(S.emailCat) : "Inbox";
  $("q").placeholder = type === "apps" ? "Search applications…" : "Search job emails…";
  closeEmailPane(); placePane(); $("content").scrollTop = 0;
  if (!load) return;
  ({ dashboard: loadDashboard, emails: () => loadEmails(true), matches: loadMatches, apps: loadApps, profile: loadProfile })[type]();
}
function refreshAll() {
  const t = viewType(S.view), jobs = [loadStats()];
  if (t === "apps") jobs.push(loadApps());
  if (t === "emails" && S.emailPage === 1) jobs.push(loadEmails(true));
  if (t === "matches") jobs.push(loadMatches());
  if (t === "dashboard") jobs.push(loadDashboardLists());
  return Promise.all(jobs);
}

async function boot() {
  hydrateIcons(); buildThemePopover(); buildLabelNav();
  if (store("jm-side") === "1" && !isNarrow()) $("sidebar").classList.add("collapsed");
  const me = await api("GET", "/api/me");
  if (!me.authenticated) return showLogin();
  S.statuses = me.statuses; S.categories = me.categories;
  S.lastSync = me.last_sync_at ? parseTs(me.last_sync_at) : null;
  S.aiEnabled = !!me.ai_enabled; S.aiProvider = me.ai_provider || ""; S.canDraft = !!me.can_draft;
  fillSelect($("fStatus"), S.statuses); fillSelect($("statusFilter"), S.statuses, "All statuses");
  buildLabelNav();
  $("login").classList.add("hidden"); $("appShell").classList.remove("hidden");
  setPill("ok"); setView("dashboard");
  maybeAutoSync();
  if (!store("jm-tour-done")) setTimeout(startTour, 1200);
}

// ---------- sync pill + auto sync ----------
function setPill(state, text) {
  $("syncPill").className = "pill " + (state === "ok" ? "" : state);
  $("syncText").textContent = text || (state === "syncing" ? "Syncing…" : S.lastSync ? "Synced " + ago(S.lastSync.toISOString()) : "Not synced");
  $("syncBtn").disabled = S.syncing; $("syncBtn").classList.toggle("spinning", S.syncing || S.analyzing);
}
setInterval(() => { if (!S.syncing && !S.analyzing && !$("appShell").classList.contains("hidden")) setPill("ok"); }, 30000);

async function sync(opts = {}) {
  if (S.syncing) return;
  S.syncing = true; setPill("syncing");
  let checked = 0, stored = 0, first = true;
  try {
    for (;;) {
      const r = await api("POST", "/api/sync", first && opts.rescan ? { rescan: true } : {});
      first = false; checked += r.checked; stored += r.stored;
      setPill("syncing", `Syncing… ${checked}`);
      if (r.stored > 0) refreshAll();
      if (!r.remaining) break;
    }
    S.lastSync = new Date();
    await refreshAll();
    if (stored > 0) toast(`${stored} new job email${stored === 1 ? "" : "s"} found`, "ok");
    else if (!opts.silent) toast("Up to date", "ok");
    S.syncing = false; setPill("ok");
    await runAnalysis();
  } catch (err) {
    S.syncing = false; setPill("error", "Sync failed");
    if (err.data && err.data.error === "reauth") showLogin("Google access expired. Please sign in again.");
    else if (!opts.silent) toast("Sync failed: " + err.message, "error");
  } finally { S.syncing = false; $("syncBtn").disabled = false; }
}
function maybeAutoSync() {
  if (document.visibilityState !== "visible" || S.syncing || $("appShell").classList.contains("hidden")) return;
  if (!S.lastSync || Date.now() - S.lastSync > AUTO_SYNC_MS) sync({ silent: true });
}
setInterval(maybeAutoSync, 60 * 1000);
document.addEventListener("visibilitychange", maybeAutoSync);
$("syncBtn").addEventListener("click", () => sync({}));
$("exportBtn").addEventListener("click", () => { location.href = "/api/export.csv"; });

// ---------- AI analysis ----------
async function runAnalysis(opts = {}) {
  if (!S.aiEnabled || S.analyzing || S.syncing) return;
  S.analyzing = true; setPill("syncing", "AI sorting…");
  let analyzed = 0, errors = 0, first = true;
  try {
    for (;;) {
      const r = await api("POST", "/api/ai/analyze", first ? opts : {});
      first = false; analyzed += r.analyzed; errors += r.errors;
      if (r.error_kind && !S.aiWarned[r.error_kind]) { S.aiWarned[r.error_kind] = true; toast(r.help || "AI request failed.", "error"); }
      if (r.remaining) setPill("syncing", `AI sorting… ${r.remaining} left`);
      if (r.analyzed || r.removed) refreshAll();
      if (!r.remaining || r.analyzed + r.removed === 0) break;
    }
    await refreshAll();
    if (analyzed) toast(`AI sorted ${analyzed} email${analyzed === 1 ? "" : "s"}`, "ok");
  } catch (err) { toast("AI analysis failed: " + err.message, "error"); }
  finally { S.analyzing = false; setPill("ok"); }
}

// ---------- stats, sidebar counts, banner ----------
function buildLabelNav() {
  const box = $("labelNav"); if (box.dataset.built === (S.categories.join() || "none")) return;
  box.replaceChildren();
  const cats = S.categories.length ? S.categories : ["applied", "assessment", "interview", "offer", "rejected", "opening", "recruiter"];
  cats.forEach((c) => {
    const b = el("button", "nav-item"); b.dataset.view = "label:" + c;
    const d = el("span", "ldot"); d.style.setProperty("--c", statusColor(c));
    const n = el("span", "nl", cap(c)), k = el("span", "count"); k.id = "lc-" + c;
    b.append(d, n, k); box.append(b);
  });
  box.dataset.built = S.categories.join() || "none";
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === S.view));
}
function setCount(id, n) { const c = $(id); if (c) c.textContent = n ? String(n) : ""; }
async function loadStats() {
  const s = await api("GET", "/api/stats"); S.stats = s;
  setCount("cInbox", s.total_emails); setCount("cUnread", s.unread); setCount("cMatches", s.strong_matches); setCount("cBoard", s.total_applications);
  S.categories.forEach((c) => setCount("lc-" + c, s.emails[c] || 0));
  updateAiChip(s);

  const box = $("funnel"); box.replaceChildren();
  const fchip = (label, n, status, color) => {
    const b = el("button", "chip-stat"); b.style.setProperty("--c", color);
    b.append(el("b", "", String(n)), el("span", "", label));
    b.addEventListener("click", () => { S.statusFilter = status; $("statusFilter").value = status; setView("board"); });
    box.append(b);
  };
  fchip("All applications", s.total_applications, "", "var(--brand)");
  ["saved", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"].forEach((k) => {
    if (k === "withdrawn" && !s.applications[k]) return;
    fchip(k, s.applications[k] || 0, k, statusColor(k));
  });

  const a = s.applications, ins = $("insights"); ins.replaceChildren();
  const card = (k, v, sub) => { const c = el("div", "insight"); c.append(el("div", "k", k), el("div", "v", v)); if (sub) c.append(el("div", "s", sub)); ins.append(c); return c; };
  const active = (a.applied || 0) + (a.assessment || 0) + (a.interview || 0);
  card("Active applications", String(active), `${s.total_emails} job emails tracked`);
  const sent = active + (a.offer || 0) + (a.rejected || 0), replied = sent - (a.applied || 0);
  card("Response rate", sent ? Math.round((replied / sent) * 100) + "%" : "–", sent ? `${replied} of ${sent} moved past “applied”` : "Apply to get started");
  if (s.strong_matches) { const m = card("Strong job matches", String(s.strong_matches), "fit score 70+, click to view"); m.classList.add("click"); m.addEventListener("click", () => setView("matches")); }
  const st = card("Needs follow-up", String(s.stale), "quiet for 14+ days");
  if (s.stale) { st.classList.add("click"); st.addEventListener("click", () => { S.sort = "recent"; $("sort").value = "recent"; setView("list"); }); }
  const w = card("Emails per week", String(s.weekly.reduce((n, x) => n + x.count, 0)), "last 8 weeks");
  w.append(sparkline(s.weekly));

  const banner = $("aiBanner");
  if (s.ai_error) {
    $("aiBannerText").textContent = s.ai_error.help + (s.pending_ai ? ` ${s.pending_ai} email${s.pending_ai === 1 ? " is" : "s are"} waiting for AI.` : "");
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
}
function updateAiChip(s) {
  const chipEl = $("aiChip"), t = $("aiChipText");
  chipEl.classList.remove("on", "bad");
  if (!S.aiEnabled) t.textContent = "AI is off";
  else if (s.ai_error) { t.textContent = "AI needs attention"; chipEl.classList.add("bad"); }
  else if (s.pending_ai) { t.textContent = `AI on · ${s.pending_ai} waiting`; chipEl.classList.add("on"); }
  else { t.textContent = "AI is on"; chipEl.classList.add("on"); }
}
function sparkline(weekly) {
  const NS = "http://www.w3.org/2000/svg", max = Math.max(1, ...weekly.map((x) => x.count));
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 160 38"); svg.setAttribute("preserveAspectRatio", "none");
  weekly.forEach((x, i) => {
    const h = Math.max(2, (x.count / max) * 34), r = document.createElementNS(NS, "rect");
    r.setAttribute("x", String(i * 20 + 2)); r.setAttribute("y", String(36 - h)); r.setAttribute("width", "15"); r.setAttribute("height", String(h));
    r.setAttribute("rx", "3"); r.setAttribute("fill", "currentColor"); r.setAttribute("opacity", x.count ? "0.9" : "0.25");
    const t = document.createElementNS(NS, "title"); t.textContent = `Week of ${x.week_start}: ${x.count}`; r.append(t); svg.append(r);
  });
  return svg;
}
$("aiBannerBtn").addEventListener("click", () => { setView("profile"); testAI(); });

// ---------- dashboard ----------
async function loadDashboard() { await Promise.all([loadStats(), loadDashboardLists()]); }
async function loadDashboardLists() {
  const [recent, prof] = await Promise.all([api("GET", "/api/emails?page=1"), api("GET", "/api/profile").catch(() => null)]);
  S.profile = prof || S.profile;
  const box = $("recentList"); box.replaceChildren();
  if (!recent.items.length) box.append(emptyState("inbox", "No job emails yet", "JobMail checks Gmail automatically. You can also sync right now.", "Sync now", () => sync({})));
  recent.items.slice(0, 6).forEach((e) => box.append(emailRow(e, true)));
  const list = $("setupList"); list.replaceChildren();
  const p = S.profile || {};
  const items = [
    [true, "Gmail connected", null],
    [S.canDraft, "Reply drafts allowed", ["Re-connect", () => { location.href = "/auth/login"; }]],
    [S.aiEnabled, "AI turned on", ["How?", () => setView("profile")]],
    [!!p.resume, "Resume uploaded", ["Upload", () => setView("profile")]],
    [(p.profile_text || "").length > 30, "Profile filled in", ["Edit", () => setView("profile")]],
  ];
  items.forEach(([done, text, act]) => {
    const row = el("div", "setup-item" + (done ? " done" : "")), tick = el("span", "tick"); tick.append(icon("check"));
    row.append(tick, el("span", "grow", text));
    if (!done && act) { const b = el("button", "link", act[0]); b.addEventListener("click", act[1]); row.append(b); }
    list.append(row);
  });
}

// ---------- email list (Gmail style) ----------
function fitBadge(score) { return el("span", "fit " + (score >= 75 ? "high" : score >= 50 ? "mid" : ""), String(score)); }
function emailRow(e, compact) {
  const ts = compact ? [] : terms();
  const row = el("div", "erow" + (e.is_unread ? " unread" : "")); row.tabIndex = 0; row.dataset.id = e.id;
  if (S.selectedId === e.id) row.classList.add("sel");
  const sender = el("span", "sender"); appendHighlighted(sender, senderName(e.sender), ts);
  const subj = el("span", "subj-cell"); subj.append(chip(e.category));
  const s = el("span", "s"); appendHighlighted(s, e.subject || "(no subject)", ts); subj.append(s);
  const sn = el("span", "snip"); sn.append(" – "); appendHighlighted(sn, e.ai_summary || e.snippet || "", ts); subj.append(sn);
  const fit = el("span", "fitcell"); if (e.fit_score !== null && e.fit_score !== undefined) fit.append(fitBadge(e.fit_score));
  row.append(el("span", "udot"), sender, subj, fit, el("span", "date", fmtShort(e.received_at)));
  row.addEventListener("click", () => openEmail(e.id, row));
  row.addEventListener("keydown", (ev) => { if (ev.key === "Enter") openEmail(e.id, row); });
  return row;
}
async function loadEmails(reset) {
  if (reset) S.emailPage = 1;
  const req = ++S.emailReq;
  const p = new URLSearchParams({ q: $("q").value, category: S.emailCat, from: $("emailFrom").value, to: $("emailTo").value, page: S.emailPage });
  if (S.unreadOnly) p.set("unread", "1");
  const box = $("emailList");
  if (reset) skeleton(box, 6);
  const data = await api("GET", "/api/emails?" + p);
  if (req !== S.emailReq) return;
  if (reset) box.replaceChildren();
  if (reset && !data.items.length) {
    const searching = $("q").value.trim();
    box.append(searching ? emptyState("search", "No emails match your search", "Try fewer words or clear the date filters.")
      : S.unreadOnly ? emptyState("check", "You're all caught up", "No unread job emails.")
      : emptyState("inbox", "Nothing here yet", "JobMail checks Gmail automatically. You can also sync right now.", "Sync now", () => sync({})));
  }
  data.items.forEach((e) => box.append(emailRow(e)));
  $("emailCount").textContent = data.total ? `${data.total} email${data.total === 1 ? "" : "s"}` : "";
  $("moreBtn").classList.toggle("hidden", S.emailPage * data.page_size >= data.total);
}
$("moreBtn").addEventListener("click", () => { S.emailPage += 1; loadEmails(false); });
["emailFrom", "emailTo"].forEach((id) => $(id).addEventListener("change", () => loadEmails(true)));

// ---------- reading pane ----------
function placePane() {
  const docked = viewType(S.view) === "emails" && matchMedia("(min-width: 1100px)").matches;
  $("emailPane").classList.toggle("overlay", !docked); syncBackdrop();
}
window.addEventListener("resize", debounce(() => { placePane(); if (T.open) placeTour(TOUR[T.i]); }, 120));
async function openEmail(id, row) {
  S.selectedId = id;
  document.querySelectorAll(".erow.sel").forEach((r) => r.classList.remove("sel"));
  const r = row || document.querySelector(`#emailList .erow[data-id="${id}"]`); if (r) r.classList.add("sel");
  placePane();
  let e; try { e = await api("GET", "/api/emails/" + id); } catch (_) { return; }
  renderEmailPane(e);
  const pane = $("emailPane"); pane.classList.add("open"); pane.scrollTop = 0; syncBackdrop();
}
function closeEmailPane() {
  S.selectedId = null; $("emailPane").classList.remove("open");
  document.querySelectorAll(".erow.sel").forEach((r) => r.classList.remove("sel")); syncBackdrop();
}
function renderEmailPane(e) {
  const pane = $("emailPane"); pane.replaceChildren();
  const bar = el("div", "pane-bar");
  bar.append(iconBtn("back", "Back", closeEmailPane), el("span", "spacer"));
  if (e.application_id) { const b = el("button", "btn small", "Open application"); b.addEventListener("click", () => openDrawer(e.application_id)); bar.append(b); }
  bar.append(iconBtn("ban", "Not job-related: remove from JobMail", async () => {
    if (!confirm("Remove this email from JobMail? It will not be imported again.")) return;
    await api("DELETE", "/api/emails/" + e.id); closeEmailPane();
    const r = document.querySelector(`#emailList .erow[data-id="${e.id}"]`); if (r) r.remove();
    toast("Email removed"); loadStats();
  }), iconBtn("x", "Close", closeEmailPane));
  const body = el("div", "pane-body");
  body.append(el("h2", "", e.subject || "(no subject)"));
  const tags = el("div", "row"); tags.style.marginTop = "0"; tags.append(chip(e.category));
  if (e.fit_score !== null && e.fit_score !== undefined) tags.append(fitBadge(e.fit_score), el("span", "muted small", "job fit"));
  if (e.is_unread) tags.append(el("span", "muted small", "· unread in Gmail"));
  body.append(tags);
  const meta = el("div", "pane-meta"), who = el("div", "who");
  who.append(el("b", "", senderName(e.sender)), el("span", "muted small", `${e.sender_email} · ${parseTs(e.received_at) ? parseTs(e.received_at).toLocaleString() : ""}`));
  meta.append(avatar(senderName(e.sender)), who); body.append(meta);
  if (e.company || e.role) body.append(el("div", "muted", [e.company, e.role].filter(Boolean).join(" · ")));
  if (e.ai_summary || e.fit_reason) {
    const box = el("div", "ai-box"), txt = el("div");
    if (e.ai_summary) txt.append(el("div", "", e.ai_summary));
    if (e.fit_reason) txt.append(el("div", "muted small", "Why this score: " + e.fit_reason));
    box.append(ic("sparkle"), txt); body.append(box);
  }
  body.append(el("div", "mail-body", e.body_text || e.snippet || "(no text)"));
  const actions = el("div", "row wrap");
  if (S.aiEnabled) { const r = el("button", "btn primary"); r.append(icon("sparkle"), "Reply with AI"); r.addEventListener("click", () => openCompose(e)); actions.append(r); }
  else actions.append(el("span", "muted small", "Turn on AI (Profile) to draft replies with your resume."));
  body.append(actions);
  pane.append(bar, body);
}

// ---------- matches ----------
async function loadMatches() {
  const box = $("matchesList"); skeleton(box, 2);
  const { items } = await api("GET", "/api/matches");
  box.replaceChildren();
  $("matchesNote").textContent = !S.aiEnabled ? "Turn on AI (Profile page) to score job openings against your profile."
    : items.length ? `${items.length} scored opening${items.length === 1 ? "" : "s"}, best first.` : "";
  if (!items.length) box.append(emptyState("star", "No scored openings yet", S.aiEnabled ? "They appear after the next sync, once your profile is filled in." : "AI is off, so openings are not scored."));
  items.forEach((m) => box.append(matchCard(m)));
}
function matchCard(m) {
  const card = el("div", "match");
  const sc = el("div", "score"); sc.style.setProperty("--p", String(m.fit_score));
  sc.style.setProperty("--c", m.fit_score >= 75 ? "var(--offer)" : m.fit_score >= 50 ? "var(--interview)" : "var(--withdrawn)");
  sc.append(el("span", "", String(m.fit_score))); card.append(sc);
  const body = el("div");
  const h = el("h3", "", m.role ? m.role + (m.company ? " at " + m.company : "") : (m.subject || "(no subject)")); body.append(h);
  if (m.fit_reason) body.append(el("div", "why", m.fit_reason));
  if (m.ai_summary) body.append(el("div", "muted", m.ai_summary));
  body.append(el("div", "muted small", `${senderName(m.sender)} · ${ago(m.received_at)} · ${cap(m.category)}`));
  const actions = el("div", "row wrap");
  const reply = el("button", "btn primary"); reply.append(icon("sparkle"), "Reply / apply with AI"); reply.addEventListener("click", () => openCompose(m));
  const view = el("button", "btn", "Read email"); view.addEventListener("click", () => openEmail(m.id));
  actions.append(reply, view); body.append(actions); card.append(body);
  return card;
}

// ---------- applications ----------
async function loadApps() {
  const p = new URLSearchParams({ status: S.statusFilter, sort: S.sort });
  if (viewType(S.view) === "apps") p.set("q", $("q").value);
  const { items } = await api("GET", "/api/applications?" + p);
  S.apps = items; renderApps();
}
function appCard(a) {
  const card = el("div", "card"); card.tabIndex = 0; card.dataset.id = a.id;
  card.append(avatar(a.company));
  const body = el("div"), ts = terms();
  const t = el("div", "t"); appendHighlighted(t, a.company, ts); body.append(t);
  if (a.role) { const r = el("div", "r"); appendHighlighted(r, a.role, ts); body.append(r); }
  const m = el("div", "m");
  if (S.view === "list") m.append(el("span", "badge " + a.status, a.status));
  m.append(el("span", "", ago(a.last_activity_at)));
  if (a.email_count) m.append(el("span", "tag", `✉ ${a.email_count}`));
  if (a.source === "manual") m.append(el("span", "tag", "manual"));
  const sd = staleDays(a); if (sd) m.append(el("span", "tag warn", `${sd}d quiet`));
  body.append(m); card.append(body);
  card.addEventListener("click", () => openDrawer(a.id));
  card.addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawer(a.id); });
  card.draggable = true;
  card.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; card.classList.add("dragging"); });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));
  return card;
}
function renderApps() { if (S.view === "board") renderBoard(); else if (S.view === "list") renderList(); }
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
      const id = Number(e.dataTransfer.getData("text/plain")), a = S.apps.find((x) => x.id === id);
      if (a && a.status !== st) await setStatus(a, st);
    });
    box.append(col);
  });
}
function renderList() {
  const box = $("listView"); box.replaceChildren();
  if (!S.apps.length) { box.append(emptyState("briefcase" in ICONS ? "briefcase" : "list", "No applications match", "Add one with the button on the left, or wait for the next sync.")); return; }
  S.apps.forEach((a) => box.append(appCard(a)));
}
async function setStatus(a, status) {
  const prev = a.status; a.status = status; renderApps();
  try { await api("PATCH", "/api/applications/" + a.id, { status }); toast(`${a.company} → ${cap(status)}`, "ok"); loadStats(); if (S.drawerId === a.id) openDrawer(a.id, true); }
  catch (e) { a.status = prev; renderApps(); toast("Could not update status", "error"); }
}
$("statusFilter").addEventListener("change", () => { S.statusFilter = $("statusFilter").value; loadApps(); });
$("sort").addEventListener("change", () => { S.sort = $("sort").value; loadApps(); });

// ---------- application drawer ----------
async function openDrawer(id, keepScroll) {
  S.drawerId = id;
  let a; try { a = await api("GET", "/api/applications/" + id); } catch (_) { S.drawerId = null; return; }
  const body = $("drawerBody"); body.replaceChildren();
  const inner = el("div", "drawer-inner");
  const head = el("div", "drawer-head"); head.append(avatar(a.company));
  const title = el("div"); title.append(el("h2", "", a.company), el("div", "muted", a.role || "No role detected"));
  head.append(title, iconBtn("x", "Close", closeDrawer)); inner.append(head);
  inner.append(el("h4", "", "Status"));
  const row = el("div", "status-row");
  S.statuses.forEach((st) => {
    const b = el("button", "status-btn" + (a.status === st ? " active" : ""), st); b.style.setProperty("--c", statusColor(st));
    b.addEventListener("click", () => setStatus(S.apps.find((x) => x.id === a.id) || a, st)); row.append(b);
  });
  inner.append(row, el("div", "muted", `First seen ${fmtDate(a.first_seen_at)} · last activity ${ago(a.last_activity_at)}`));
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
  inner.append(tl); body.append(inner);
  const drawer = $("drawer"); drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); syncBackdrop();
  if (!keepScroll) drawer.scrollTop = 0;
}
function closeDrawer() { S.drawerId = null; $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); syncBackdrop(); }

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
$("addBtn").addEventListener("click", () => { openDialog(null); closeSidebarIfNarrow(); });

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
    : "AI is off. To turn it on for free, create a Gemini API key at aistudio.google.com and add it as GEMINI_API_KEY on your host (see docs/DEPLOYMENT.md, section 9).") +
    (S.canDraft ? "" : " Reply drafts need one more Google permission.");
  $("reanalyzeBtn").classList.toggle("hidden", !S.aiEnabled); $("aiTestBtn").classList.toggle("hidden", !S.aiEnabled);
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
$("reanalyzeBtn").addEventListener("click", () => { S.aiWarned = {}; runAnalysis({ reanalyze: true, retry: true }); });
$("rescanBtn").addEventListener("click", () => { toast("Rescanning the last 3 months…"); sync({ rescan: true }); });
async function testAI() {
  const box = $("aiTestResult"), btn = $("aiTestBtn"); btn.disabled = true;
  box.classList.remove("hidden"); box.replaceChildren(el("div", "test-line", "Testing the AI connection…"));
  try {
    const r = await api("POST", "/api/ai/test", {});
    box.replaceChildren();
    r.results.forEach((x) => box.append(el("div", "test-line " + (x.ok ? "ok" : "bad"), x.ok ? `✓ ${x.model}: working` : `✗ ${x.model}: ${x.help || "failed"}`)));
    if (r.ok) { S.aiWarned = {}; toast("AI connection works", "ok"); loadStats(); runAnalysis(); }
  } catch (e) { box.replaceChildren(el("div", "test-line bad", e.data && e.data.error === "ai_disabled" ? "AI is not enabled on the server." : "Test failed: " + e.message)); }
  finally { btn.disabled = false; }
}
$("aiTestBtn").addEventListener("click", testAI);

// ---------- reply with AI ----------
const C = { emailId: null };
function composeReset() {
  ["composeForm", "composeDone", "cRewrite", "cCreate", "composeError"].forEach((id) => $(id).classList.add("hidden"));
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
  } catch (err) {
    $("composeStatus").textContent = "Could not write a draft.";
    $("composeError").textContent = (err.data && err.data.help) || "Please try again in a moment.";
    $("composeError").classList.remove("hidden");
  }
}
$("cRewrite").addEventListener("click", () => generateDraft($("cInstr").value));
$("cClose").addEventListener("click", () => $("composeDlg").close());
$("cCreate").addEventListener("click", async () => {
  $("cCreate").disabled = true;
  try {
    const r = await api("POST", `/api/emails/${C.emailId}/draft`, { to: $("cTo").value, subject: $("cSubject").value, body: $("cBody").value, attach_resume: $("cAttach").checked });
    ["composeForm", "cRewrite", "cCreate"].forEach((id) => $(id).classList.add("hidden"));
    $("composeDone").classList.remove("hidden");
    const ok = typeof r.url === "string" && r.url.startsWith("https://mail.google.com/");
    $("composeLink").href = ok ? r.url : "https://mail.google.com/mail/u/0/#drafts";
    toast(r.attached ? "Draft created with your resume attached" : "Draft created", "ok");
  } catch (err) {
    $("composeWarn").textContent = err.data && err.data.error === "reauth_scope"
      ? "JobMail needs permission to create drafts. Open the Profile page and use “Re-connect Google”." : "Could not create the draft: " + err.message;
    $("composeWarn").classList.remove("hidden");
  } finally { $("cCreate").disabled = false; }
});

// ---------- guided tour ----------
const TOUR = [
  { t: "Welcome to JobMail", x: "A one-minute tour. JobMail turns the job emails in your Gmail into an inbox, a pipeline board and AI-scored job matches." },
  { t: "Your sidebar", x: "Dashboard shows the big picture. Inbox has every job email from the last 3 months and Unread mirrors Gmail's unread state.", sel: "#sidebarNav", side: true },
  { t: "Labels", x: "Emails are sorted automatically into Applied, Assessment, Interview, Offer, Rejected, Opening and Recruiter. Click a label to filter.", sel: "#labelNav", side: true },
  { t: "Search", x: "Search subjects, senders and message text. Press / anywhere to jump here, and j / k to move through emails.", sel: "#searchBox" },
  { t: "Automatic sync", x: "JobMail checks Gmail when you open it and every 5 minutes. Press refresh to sync right now.", sel: "#syncBtn" },
  { t: "Best matches", x: "With AI on, every job opening and recruiter message is scored against your profile. The best fits are collected here.", sel: '#sidebar [data-view="matches"]', side: true },
  { t: "Applications board", x: "Each company becomes a card. Drag cards between columns to change their status, or click one for notes and its email timeline.", sel: '#sidebar [data-view="board"]', side: true },
  { t: "Add your own", x: "Applied somewhere JobMail cannot see? Add it by hand.", sel: "#addBtn", side: true },
  { t: "Profile & resume", x: "Upload your resume and describe what you want. The AI uses this to score jobs and to draft replies with your resume attached.", sel: '#sidebar [data-view="profile"]', side: true },
  { t: "Reply with AI", x: "Open any email and press “Reply with AI”. You get an editable message, then a Gmail draft with your resume attached. Nothing is sent until you press send in Gmail." },
  { t: "Make it yours", x: "Pick a theme and a display density, just like Gmail.", sel: "#themeBtn" },
  { t: "Replay anytime", x: "Press Tour whenever you want to see this again.", sel: "#tourBtn" },
];
const T = { i: 0, open: false };
function startTour() { if ($("appShell").classList.contains("hidden")) return; T.open = true; T.i = 0; $("tour").classList.remove("hidden"); showTour(); }
function endTour() {
  T.open = false; $("tour").classList.add("hidden"); store("jm-tour-done", "1");
  if (isNarrow()) $("sidebar").classList.remove("open"); syncBackdrop();
}
function showTour() {
  const s = TOUR[T.i];
  $("tourStep").textContent = `Step ${T.i + 1} of ${TOUR.length}`; $("tourTitle").textContent = s.t; $("tourText").textContent = s.x;
  $("tourBack").classList.toggle("hidden", T.i === 0); $("tourNext").textContent = T.i === TOUR.length - 1 ? "Done" : "Next";
  const dots = $("tourDots"); dots.replaceChildren(); TOUR.forEach((_, i) => dots.append(el("i", i === T.i ? "on" : "")));
  const sidebar = $("sidebar");
  if (isNarrow()) sidebar.classList.toggle("open", !!s.side);
  setTimeout(() => placeTour(s), isNarrow() ? 260 : 30);
}
function placeTour(s) {
  if (!T.open) return;
  const hole = $("tourHole"), card = $("tourCard"), vw = innerWidth, vh = innerHeight;
  let target = s.sel ? document.querySelector(s.sel) : null;
  if (target && target.getClientRects().length === 0) target = null;
  const cw = card.offsetWidth, ch = card.offsetHeight, clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
  card.classList.remove("top");
  if (!target) {
    hole.style.left = vw / 2 + "px"; hole.style.top = vh / 2 + "px"; hole.style.width = "0px"; hole.style.height = "0px";
    card.style.left = (vw - cw) / 2 + "px"; card.style.top = (vh - ch) / 2 + "px"; return;
  }
  target.scrollIntoView({ block: "nearest" });
  const r = target.getBoundingClientRect(), pad = 6;
  hole.style.left = r.left - pad + "px"; hole.style.top = r.top - pad + "px";
  hole.style.width = r.width + pad * 2 + "px"; hole.style.height = r.height + pad * 2 + "px";
  if (isNarrow()) { card.classList.toggle("top", r.top + r.height / 2 > vh / 2); return; }
  let left, top;
  if (target.closest("#sidebar") && r.right + 16 + cw < vw) { left = r.right + 16; top = clamp(r.top, 12, vh - ch - 12); }
  else { left = clamp(r.left, 12, vw - cw - 12); top = r.bottom + 14; if (top + ch > vh - 12) top = Math.max(12, r.top - ch - 14); }
  card.style.left = left + "px"; card.style.top = top + "px";
}
$("tourNext").addEventListener("click", () => { if (T.i >= TOUR.length - 1) endTour(); else { T.i += 1; showTour(); } });
$("tourBack").addEventListener("click", () => { if (T.i > 0) { T.i -= 1; showTour(); } });
$("tourSkip").addEventListener("click", endTour);
$("tourBtn").addEventListener("click", startTour);

// ---------- search + keyboard ----------
const onSearch = debounce(() => {
  const t = viewType(S.view);
  if (t === "emails") loadEmails(true); else if (t === "apps") loadApps(); else setView("inbox");
});
$("q").addEventListener("input", onSearch);
$("q").addEventListener("keydown", (e) => { if (e.key === "Escape") { $("q").value = ""; $("q").blur(); onSearch(); } });
$("logoutBtn").addEventListener("click", async () => { await api("POST", "/auth/logout", {}); location.href = "/"; });
document.addEventListener("keydown", (e) => {
  if (T.open) {
    if (e.key === "Escape") endTour();
    else if (e.key === "ArrowRight" || e.key === "Enter") $("tourNext").click();
    else if (e.key === "ArrowLeft") $("tourBack").click();
    return;
  }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName) || document.querySelector("dialog[open]");
  if (e.key === "/" && !typing) { e.preventDefault(); $("q").focus(); }
  else if (e.key === "Escape") { $("themePop").classList.add("hidden"); closeDrawer(); closeEmailPane(); $("sidebar").classList.remove("open"); syncBackdrop(); }
  else if ((e.key === "j" || e.key === "k") && !typing && viewType(S.view) === "emails") {
    const rows = [...document.querySelectorAll("#emailList .erow")]; if (!rows.length) return;
    const idx = rows.findIndex((r) => Number(r.dataset.id) === S.selectedId);
    const next = rows[clamp(idx + (e.key === "j" ? 1 : -1), 0, rows.length - 1)];
    if (next) { openEmail(Number(next.dataset.id), next); next.scrollIntoView({ block: "nearest" }); }
  }
});
function clamp(v, lo, hi) { return Math.max(lo, Math.min(v, hi)); }

// ---------- start ----------
hydrateIcons(); applyTheme(store("jm-theme")); applyDensity(store("jm-density"));
boot().catch(() => showLogin("Could not reach the server."));
