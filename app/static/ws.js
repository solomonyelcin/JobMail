"use strict";
// Workspaces: Job (see app.js), Banking and Personal. All text is inserted with textContent.
Object.assign(ICONS, {
  chevron: "M6 9l6 6 6-6",
  chart: "M4 20V10|M10 20V4|M16 20v-7|M22 20H2",
  calendar: "M4 5h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z|M3 10h18|M8 3v4|M16 3v4",
  down: "M12 5v14|M5 12l7 7 7-7",
  up: "M12 19V5|M5 12l7-7 7 7",
  briefcase: "M3 8h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z|M8 8V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3|M2 13h20",
  bank: "M3 10l9-6 9 6|M5 10v8|M9.5 10v8|M14.5 10v8|M19 10v8|M3 21h18",
  heart: "M12 20s-7-4.4-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.6-9 9-9 9z",
  external: "M14 4h6v6|M20 4l-9 9|M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  trash: "M4 7h16|M10 11v6|M14 11v6|M6 7l1 13h10l1-13|M9 7V4h6v3",
});

["chevron", "chart", "calendar", "down", "up", "briefcase", "bank", "heart", "external", "trash"].forEach((n) => {
  document.querySelectorAll(`[data-icon="${n}"]`).forEach((node) => node.replaceChildren(icon(n)));
});

const WS = {
  job: { name: "Job", sub: "Applications & openings", icon: "briefcase", home: "dashboard", ph: "Search job emails…" },
  bank: { name: "Banking", sub: "Spending, EMIs & bills", icon: "bank", home: "bank:dashboard", ph: "Search transactions…" },
  personal: { name: "Personal", sub: "Family, friends & starred", icon: "heart", home: "personal:inbox", ph: "Search personal mail…" },
};
Object.assign(S, { wsLast: { bank: null, personal: null }, jobLast: null, wsStats: null, bankDays: 90, txPage: 1, txReq: 0, txKind: "", txCat: "", pPage: 1, pReq: 0, pFilter: "inbox" });

// ---------- helpers ----------
function money(n, cur, compact) {
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: cur || "INR", maximumFractionDigits: compact ? 1 : 0, notation: compact ? "compact" : "standard" }).format(n);
  } catch (_) { return (cur || "") + " " + Math.round(n); }
}
const gmailLink = (threadId) => "https://mail.google.com/mail/u/0/#all/" + encodeURIComponent(threadId || "");
function monthLabel(ym) { const [y, m] = ym.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "short" }); }
function svgEl(tag, attrs, cls) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
  if (cls) n.setAttribute("class", cls);
  return n;
}
function extLink(href, label) {
  const a = el("a", "btn small"); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
  a.append(icon("external"), label); return a;
}

// ---------- switcher ----------
function buildWsMenu() {
  const menu = $("wsMenu"); menu.replaceChildren();
  Object.entries(WS).forEach(([key, w]) => {
    const b = el("button", "ws-item" + (key === S.ws ? " active" : "")); b.setAttribute("role", "menuitem"); b.dataset.ws = key;
    const i = el("span", "ws-ico"); i.append(icon(w.icon));
    const t = el("span", "ws-text"); t.append(el("b", "", w.name), el("small", "", w.sub));
    b.append(i, t); if (key === S.ws) b.append(icon("check"));
    b.addEventListener("click", () => { closeWsMenu(); wsSwitch(key); });
    menu.append(b);
  });
}
function closeWsMenu() { $("wsMenu").classList.add("hidden"); $("wsBtn").setAttribute("aria-expanded", "false"); }
$("wsBtn").addEventListener("click", (e) => {
  e.stopPropagation(); buildWsMenu();
  const open = $("wsMenu").classList.toggle("hidden") === false; $("wsBtn").setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (e) => { if (!e.target.closest(".ws-switch")) closeWsMenu(); });

function wsEnter(ws) {
  if (S.ws === "job") S.jobLast = S.lastSync;
  S.ws = ws; store("jm-ws", ws);
  S.lastSync = ws === "job" ? S.jobLast : S.wsLast[ws];
  document.querySelectorAll(".ws-group").forEach((g) => g.classList.toggle("hidden", g.dataset.ws !== ws));
  $("wsName").textContent = WS[ws].name; $("wsSub").textContent = WS[ws].sub;
  const ico = $("wsIco"); ico.replaceChildren(icon(WS[ws].icon)); ico.dataset.ws = ws;
  $("q").placeholder = WS[ws].ph;
  $("exportBtn").classList.toggle("hidden", ws === "personal");
  $("exportBtn").title = ws === "bank" ? "Download transactions as CSV" : "Download applications as CSV";
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  setPill(S.syncing ? "syncing" : "ok");
}
function wsSwitch(ws) {
  if (ws === S.ws) return;
  $("q").value = ""; setView(WS[ws].home); closeSidebarIfNarrow();
  if (ws !== "job") { loadWsStats(); if (!S.wsLast[ws]) sync({ silent: true }); else maybeAutoSync(); }
}
function wsInit() {
  const saved = store("jm-ws");
  loadWsStats().catch(() => {});
  const ws = WS[saved] ? saved : "job";
  if (ws === "job") { wsEnter("job"); setView("dashboard"); }
  else {
    S.ws = "job"; wsEnter("job"); // wsEnter saves jobLast first
    S.jobLast = S.lastSync; setView(WS[ws].home);
    sync({ silent: true });
  }
}

// ---------- view routing ----------
function wsSetView(key, load = true) {
  const [ws, view] = key.split(":");
  if (S.ws !== ws) wsEnter(ws);
  S.view = key;
  ["dashboard", "emails", "matches", "apps", "profile"].forEach((t) => $(t + "View").classList.add("hidden"));
  $("bankView").classList.toggle("hidden", ws !== "bank"); $("personalView").classList.toggle("hidden", ws !== "personal");
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === key));
  closeEmailPane(); closeDrawer(); placePane(); $("content").scrollTop = 0;
  if (ws === "bank") {
    S.txKind = view === "spend" ? "spend" : view === "credit" ? "credit" : ""; S.txCat = "";
    $("bankTitle").textContent = { dashboard: "Banking overview", transactions: "Transactions", bills: "Bills & EMIs", spend: "Spending", credit: "Income" }[view] || "Banking";
    $("bankRange").classList.toggle("hidden", view !== "dashboard");
  } else {
    S.pFilter = view;
    $("personalTitle").textContent = { inbox: "Personal inbox", unread: "Unread", needs_reply: "Needs reply", starred: "Starred & important", family: "Family", friend: "Friends", people: "Manage people" }[view] || "Personal";
  }
  if (load) wsLoadView();
}
function wsLoadView() {
  const [ws, view] = S.view.split(":");
  if (ws === "bank") return ({ dashboard: loadBankDashboard, bills: loadBankBills }[view] || (() => loadTransactions(true)))();
  return view === "people" ? loadPeople() : loadPersonal(true);
}
async function wsRefresh() { await Promise.all([loadWsStats(), wsLoadView()]); }
function wsSearch() {
  if (S.ws === "bank") { if (S.view === "bank:dashboard" || S.view === "bank:bills") return setView("bank:transactions"); return loadTransactions(true); }
  if (S.view === "personal:people") return setView("personal:inbox");
  return loadPersonal(true);
}

// ---------- sync + AI ----------
async function wsSync(opts = {}) {
  if (S.syncing) return;
  const ws = S.ws; S.syncing = true; setPill("syncing");
  let checked = 0, stored = 0, first = true;
  try {
    for (;;) {
      const r = await api("POST", `/api/ws/${ws}/sync`, first && opts.rescan ? { rescan: true } : {});
      first = false; checked += r.checked; stored += r.stored;
      setPill("syncing", `Syncing… ${checked}`);
      if (r.stored > 0 && S.ws === ws) wsRefresh();
      if (!r.remaining) break;
    }
    S.wsLast[ws] = new Date(); if (S.ws === ws) S.lastSync = S.wsLast[ws];
    await wsRefresh();
    if (stored > 0) toast(`${stored} new ${ws === "bank" ? "banking" : "personal"} email${stored === 1 ? "" : "s"} found`, "ok");
    else if (!opts.silent) toast("Up to date", "ok");
    S.syncing = false; setPill("ok");
    await wsAnalyze(ws);
  } catch (err) {
    S.syncing = false; setPill("error", "Sync failed");
    if (err.data && err.data.error === "reauth") showLogin("Google access expired. Please sign in again.");
    else if (!opts.silent) toast("Sync failed: " + err.message, "error");
  } finally { S.syncing = false; }
}
async function wsAnalyze(ws) {
  if (!S.aiEnabled || S.analyzing || S.syncing) return;
  S.analyzing = true; setPill("syncing", "AI sorting…");
  try {
    for (let round = 0; round < 8; round++) {
      const r = await api("POST", `/api/ws/${ws}/analyze`, {});
      if (r.error_kind && !S.aiWarned[r.error_kind]) { S.aiWarned[r.error_kind] = true; toast(r.help || "AI request failed.", "error"); }
      if (r.done && S.ws === ws) await wsRefresh();
      if (!r.remaining || !r.done) break;
    }
  } catch (err) { toast("AI step failed: " + err.message, "error"); }
  finally { S.analyzing = false; setPill("ok"); loadWsStats().catch(() => {}); }
}

async function loadWsStats() {
  const s = await api("GET", "/api/ws/stats"); S.wsStats = s;
  setCount("cBankTx", s.bank.mails); setCount("cBankDue", s.bank.upcoming);
  setCount("cPAll", s.personal.mails); setCount("cPUnread", s.personal.unread); setCount("cPReply", s.personal.needs_reply);
  setCount("cPStar", s.personal.starred); setCount("cPFam", s.personal.family); setCount("cPFri", s.personal.friend); setCount("cPPeople", s.personal.people);
  if (!S.wsLast.bank && s.bank.last_sync) S.wsLast.bank = parseTs(s.bank.last_sync);
  if (!S.wsLast.personal && s.personal.last_sync) S.wsLast.personal = parseTs(s.personal.last_sync);
  if (S.ws !== "job") {
    S.lastSync = S.wsLast[S.ws];
    const pend = S.ws === "bank" ? s.bank.pending_ai : s.personal.pending_ai;
    updateAiChip({ ai_error: s.ai_error, pending_ai: pend });
    if (s.ai_error && S.aiEnabled) {
      $("aiBannerText").textContent = s.ai_error.help + (pend ? ` ${pend} item${pend === 1 ? " is" : "s are"} waiting for AI.` : "");
      $("aiBanner").classList.remove("hidden");
    } else $("aiBanner").classList.add("hidden");
    if (typeof setPill === "function" && !S.syncing) setPill("ok");
  }
  return s;
}
$("bankRange").addEventListener("change", () => { S.bankRange = $("bankRange").value; store("jm-bank-range", S.bankRange); loadBankDashboard(); });
S.bankRange = store("jm-bank-range") || "90"; $("bankRange").value = S.bankRange;
const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
// query-string part describing the chosen period
function periodQuery() {
  const now = new Date(), r = S.bankRange;
  if (r === "mtd") return `from=${isoDate(new Date(now.getFullYear(), now.getMonth(), 1))}&to=${isoDate(now)}`;
  if (r === "lm") return `from=${isoDate(new Date(now.getFullYear(), now.getMonth() - 1, 1))}&to=${isoDate(new Date(now.getFullYear(), now.getMonth(), 0))}`;
  return "days=" + (Number(r) || 90);
}
const periodDays = () => ({ mtd: 31, lm: 31 }[S.bankRange] || Number(S.bankRange) || 90);

// ---------- Banking: charts ----------
function barChart(monthly, cur) {
  const W = 520, H = 230, L = 46, B = 28, T = 10, plotH = H - B - T, plotW = W - L - 6;
  const max = Math.max(1, ...monthly.map((m) => Math.max(m.debit, m.credit)));
  const nice = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / nice) * nice;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Income and spending by month" }, "chart");
  for (let i = 0; i <= 4; i++) {
    const y = T + plotH - (plotH * i) / 4;
    svg.append(svgEl("line", { x1: L, x2: W - 6, y1: y, y2: y }, "grid"));
    const t = svgEl("text", { x: L - 6, y: y + 4, "text-anchor": "end" }, "axis"); t.textContent = money((top * i) / 4, cur, true); svg.append(t);
  }
  const gw = plotW / monthly.length, bw = Math.min(22, gw / 3);
  monthly.forEach((m, i) => {
    const cx = L + gw * i + gw / 2;
    [["credit", -bw - 1, "bar-in"], ["debit", 1, "bar-out"]].forEach(([k, dx, cls]) => {
      const h = (m[k] / top) * plotH, r = svgEl("rect", { x: cx + dx, y: T + plotH - h, width: bw, height: Math.max(h, m[k] ? 1 : 0), rx: 3 }, cls);
      const tt = svgEl("title"); tt.textContent = `${monthLabel(m.month)} ${k === "credit" ? "income" : "spending"}: ${money(m[k], cur)}`; r.append(tt); svg.append(r);
    });
    const lb = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" }, "axis"); lb.textContent = monthLabel(m.month); svg.append(lb);
  });
  return svg;
}
function donut(items, cur, total) {
  const R = 62, C = 2 * Math.PI * R, svg = svgEl("svg", { viewBox: "0 0 180 180", role: "img", "aria-label": "Spending by category" }, "donut");
  svg.append(svgEl("circle", { cx: 90, cy: 90, r: R }, "donut-bg"));
  let acc = 0;
  items.forEach((it, i) => {
    const len = (it.amount / total) * C;
    const c = svgEl("circle", { cx: 90, cy: 90, r: R, "stroke-dasharray": `${Math.max(len - 1.5, 0.5)} ${C}`, "stroke-dashoffset": -acc, transform: "rotate(-90 90 90)" }, "donut-slice sl" + (i % 10));
    const tt = svgEl("title"); tt.textContent = `${it.name}: ${money(it.amount, cur)}`; c.append(tt); svg.append(c); acc += len;
  });
  const a = svgEl("text", { x: 90, y: 86, "text-anchor": "middle" }, "donut-v"); a.textContent = money(total, cur, true);
  const b = svgEl("text", { x: 90, y: 106, "text-anchor": "middle" }, "axis"); b.textContent = "spent";
  svg.append(a, b); return svg;
}
function hbars(items, cur, klass) {
  const box = el("div", "hbars"), max = Math.max(1, ...items.map((i) => i.amount));
  items.forEach((it) => {
    const row = el("div", "hbar"), track = el("div", "track"), fill = el("div", "fill " + (klass || ""));
    fill.style.width = Math.max(3, (it.amount / max) * 100) + "%"; track.append(fill);
    row.append(el("span", "name", it.name), track, el("span", "amt", money(it.amount, cur)));
    box.append(row);
  });
  return box;
}
function kpi(parent, label, value, sub, cls) {
  const c = el("div", "insight"); c.append(el("div", "k", label), el("div", "v " + (cls || ""), value)); if (sub) c.append(el("div", "s", sub)); parent.append(c); return c;
}
function panel(title, ...kids) { const p = el("section", "panel"); p.append(el("h3", "", title), ...kids); return p; }

// ---------- Banking: dashboard ----------
function deltaText(pct, goodWhenDown) {
  if (pct === null || pct === undefined) return "";
  const up = pct > 0, good = goodWhenDown ? !up : up;
  return `${up ? "▲" : "▼"} ${Math.abs(pct)}% vs previous period` + (pct === 0 ? "" : good ? "" : "");
}
async function loadBankDashboard() {
  const box = $("bankBody"); skeleton(box, 4);
  const s = await api("GET", "/api/bank/summary?" + periodQuery());
  if (S.view !== "bank:dashboard") return;
  S.bankCats = s.categories; box.replaceChildren();
  const cur = s.currency, t = s.totals;
  if (!t.count && !s.upcoming.length) {
    box.append(emptyState("bank", "No banking emails yet", "SmartMail looks for transaction alerts, statements and EMI reminders from your banks in Gmail. Press sync to look now.", "Sync now", () => sync({})));
    return;
  }
  if (s.due_soon.count) {
    const al = el("div", "banner soft"); al.append(ic("alert"), el("div", "banner-text", `${s.due_soon.count} payment${s.due_soon.count === 1 ? "" : "s"} due in the next 7 days, ${money(s.due_soon.total, cur)} in total.`));
    const b = el("button", "btn small", "View"); b.addEventListener("click", () => setView("bank:bills")); al.append(b); box.append(al);
  }
  const ins = el("div", "insights"); box.append(ins);
  kpi(ins, "Income", money(t.credit, cur), deltaText(s.vs_previous.credit_pct, false) || "credited in this period", "pos");
  kpi(ins, "Spending", money(t.debit, cur), deltaText(s.vs_previous.debit_pct, true) || `${t.count} transactions`, "neg");
  kpi(ins, "Net", (t.net >= 0 ? "+" : "−") + money(Math.abs(t.net), cur), t.savings_rate === null ? "" : t.net >= 0 ? `${t.savings_rate}% of income kept` : "spent more than you earned", t.net >= 0 ? "pos" : "neg");
  kpi(ins, "EMIs per month", money(t.emi_monthly, cur), s.loans.length ? `${s.loans.length} loan${s.loans.length === 1 ? "" : "s"} detected` : "none detected");
  kpi(ins, "Average per day", money(t.avg_daily_spend, cur), t.card_bills_paid ? `card bills paid ${money(t.card_bills_paid, cur, true)} (not counted)` : "spending");
  if (s.month.projection) kpi(ins, "This month so far", money(s.month.spent, cur), `on track for about ${money(s.month.projection, cur, true)}`);

  const g1 = el("div", "two-col"); box.append(g1);
  const chartPanel = panel("Income vs spending");
  const legend = el("div", "legend"); legend.append(el("span", "lg in", "Income"), el("span", "lg out", "Spending"));
  chartPanel.append(legend, barChart(s.monthly, cur)); g1.append(chartPanel);
  const up = panel("Upcoming payments");
  if (!s.upcoming.length) up.append(el("p", "muted", "No upcoming bills or EMIs found in your emails."));
  s.upcoming.slice(0, 5).forEach((u) => up.append(dueRow(u)));
  if (s.upcoming.length) { const more = el("button", "link", "See all bills & EMIs"); more.addEventListener("click", () => setView("bank:bills")); up.append(more); }
  g1.append(up);

  box.append(budgetPanel(s));

  const g2 = el("div", "two-col even"); box.append(g2);
  const catPanel = panel("Where your money went");
  if (s.by_category.length) {
    const wrap = el("div", "donut-wrap"); wrap.append(donut(s.by_category.slice(0, 10), cur, t.debit));
    const leg = el("div", "cat-list");
    s.by_category.slice(0, 10).forEach((c, i) => {
      const r = el("button", "cat-row"); r.title = "Show these transactions";
      const sw = el("i", "sw sl" + i), pct = t.debit ? Math.round((c.amount / t.debit) * 100) : 0;
      r.append(sw, el("span", "n", c.name), el("span", "p", pct + "%"), el("span", "a", money(c.amount, cur)));
      r.addEventListener("click", () => { setView("bank:transactions"); S.txCat = c.name; loadTransactions(true); });
      leg.append(r);
    });
    wrap.append(leg); catPanel.append(wrap);
  } else catPanel.append(el("p", "muted", "No spending in this period."));
  g2.append(catPanel);
  const rightCol = el("div", "stack");
  const mer = panel("Top merchants"); if (s.top_merchants.length) mer.append(hbars(s.top_merchants, cur)); else mer.append(el("p", "muted", "No merchant names found yet."));
  rightCol.append(mer);
  if (s.income.length) rightCol.append(panel("Income sources", hbars(s.income, cur, "pos")));
  g2.append(rightCol);

  const g3 = el("div", "two-col even"); box.append(g3);
  g3.append(recurringPanel(s));
  const right3 = el("div", "stack");
  right3.append(weekdayPanel(s), largestPanel(s));
  g3.append(right3);
  if (s.unusual.length) {
    const up2 = panel("Unusually large payments");
    s.unusual.forEach((u) => { const r = el("div", "due-row"), l = el("div", "due-main"); l.append(el("b", "", u.merchant || u.category), el("div", "muted small", `${fmtDate(u.date)} · ${u.times_usual}x your usual ${u.category.toLowerCase()} payment`)); r.append(l, el("span", "amt", money(u.amount, cur))); up2.append(r); });
    box.append(up2);
  }

  // insights + AI
  const ip = panel("Insights"); ip.classList.add("insight-panel");
  const list = el("ul", "bullets");
  s.insights.forEach((x) => list.append(el("li", "", x)));
  if (!s.insights.length) list.append(el("li", "muted", "More insights appear as more transactions are found."));
  ip.append(list);
  const ai = el("div", "ai-box"); ai.append(ic("sparkle"));
  const txt = el("div"); ai.append(txt);
  const fillAi = (data) => {
    txt.replaceChildren();
    (data.items || []).forEach((i) => txt.append(el("div", "ai-line", i)));
    if (data.at) txt.append(el("div", "muted small", "AI insights · " + fmtDate(data.at)));
  };
  if (s.ai_insights && s.ai_insights.items) fillAi(s.ai_insights); else txt.append(el("div", "muted", S.aiEnabled ? "Ask the AI for tailored observations about your spending, EMIs and bills." : "Turn on AI to get tailored observations."));
  if (S.aiEnabled) {
    const btn = el("button", "btn small", s.ai_insights ? "Refresh AI insights" : "Get AI insights");
    btn.addEventListener("click", async () => {
      btn.disabled = true; btn.textContent = "Thinking…";
      try { fillAi(await api("POST", "/api/bank/insights", { days: periodDays() })); btn.textContent = "Refresh AI insights"; }
      catch (err) { btn.textContent = "Try again"; toast((err.data && err.data.help) || err.message, "error"); }
      btn.disabled = false;
    });
    ai.append(btn);
  }
  ip.append(ai);
  if (S.aiEnabled) ip.append(askBox());
  box.append(ip);

  const tools = el("div", "row wrap tools-row");
  const re = el("button", "btn small", "Re-analyse bank emails");
  re.title = "Read all stored bank emails again with the latest rules. Your category edits are kept.";
  re.addEventListener("click", async () => {
    re.disabled = true; re.textContent = "Working…";
    try { const r = await api("POST", "/api/bank/reparse", {}); toast(`Re-read ${r.checked} emails, ${r.removed} removed`, "ok"); loadBankDashboard(); }
    catch (err) { toast(err.message, "error"); re.disabled = false; re.textContent = "Re-analyse bank emails"; }
  });
  const exp = el("a", "btn small", "Download CSV"); exp.href = "/api/bank/export.csv";
  tools.append(re, exp); box.append(tools);
  box.append(el("p", "muted small fine", "Figures come from the amounts in your bank emails. Duplicate alerts for one payment are counted once, and paying a credit card bill is not counted as spending (the card purchases already are). Transfers between your own accounts can still inflate income and spending: use the exclude button on a transaction to remove them."));
}
function budgetPanel(s) {
  const p = panel("Monthly budgets"); const cur = s.currency;
  p.append(el("p", "muted small", "Spending this calendar month against the limits you set."));
  if (!s.budgets.length) p.append(el("p", "muted", "No budgets yet. Set a limit for a category to get a warning before you overspend."));
  s.budgets.forEach((b) => {
    const row = el("div", "budget"), head = el("div", "budget-head");
    head.append(el("b", "", b.category), el("span", "muted small", `${money(b.spent, cur)} of ${money(b.limit, cur)}`));
    const track = el("div", "track"), fill = el("div", "fill " + (b.pct >= 100 ? "over" : b.pct >= 80 ? "warn" : "ok"));
    fill.style.width = Math.min(100, b.pct) + "%"; track.append(fill);
    const note = el("div", "small " + (b.pct >= 100 ? "neg" : "muted"), b.pct >= 100 ? `Over budget by ${money(-b.remaining, cur)}` : `${money(b.remaining, cur)} left · ${b.pct}% used`);
    const edit = el("button", "link small", "Change"); edit.addEventListener("click", () => setBudget(b.category, b.limit));
    head.append(edit); row.append(head, track, note); p.append(row);
  });
  const add = el("div", "row"); const sel = el("select"); sel.setAttribute("aria-label", "Category");
  (s.categories || []).filter((c) => !["Credit card payment", "Other", "Salary", "Refund", "Interest", "Transfer in", "Other income"].includes(c) && !s.budgets.some((b) => b.category === c))
    .forEach((c) => { const o = el("option", "", c); o.value = c; sel.append(o); });
  const btn = el("button", "btn small", "Set a budget"); btn.addEventListener("click", () => setBudget(sel.value, 0));
  if (sel.options.length) add.append(sel, btn); p.append(add); return p;
}
async function setBudget(cat, current) {
  const v = prompt(`Monthly budget for ${cat} (enter 0 to remove):`, current ? String(current) : "");
  if (v === null) return; const n = Number(v.replace(/,/g, ""));
  if (!isFinite(n) || n < 0) return toast("Enter a number", "error");
  try { await api("PUT", "/api/bank/budgets", { category: cat, amount: n }); loadBankDashboard(); } catch (err) { toast(err.message, "error"); }
}
function recurringPanel(s) {
  const p = panel("Recurring payments & subscriptions");
  if (!s.recurring.length) { p.append(el("p", "muted", "Payments that repeat every month or week (Netflix, rent, SIPs) show up here once SmartMail has seen them 3 times.")); return p; }
  const total = s.recurring.reduce((n, r) => n + r.monthly_cost, 0);
  p.append(el("p", "muted small", `About ${money(total, s.currency)} a month in total.`));
  s.recurring.slice(0, 8).forEach((r) => {
    const row = el("div", "due-row"), l = el("div", "due-main");
    l.append(el("b", "", r.merchant), el("span", "chip bill", r.every), el("div", "muted small", `${r.count} payments · next around ${fmtDate(r.next_date)}`));
    row.append(l, el("span", "amt", money(r.amount, r.currency))); p.append(row);
  });
  return p;
}
function weekdayPanel(s) {
  const p = panel("Spending by weekday"), names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const items = s.weekday.map((v, i) => ({ name: names[i], amount: v }));
  if (!items.some((i) => i.amount)) { p.append(el("p", "muted", "Not enough data yet.")); return p; }
  p.append(hbars(items, s.currency)); return p;
}
function largestPanel(s) {
  const p = panel("Largest payments");
  if (!s.largest.length) { p.append(el("p", "muted", "No spending yet.")); return p; }
  s.largest.forEach((l) => { const r = el("div", "due-row"), d = el("div", "due-main"); d.append(el("b", "", l.merchant || l.category || "Payment"), el("div", "muted small", `${fmtDate(l.date)} · ${l.category}`)); r.append(d, el("span", "amt", money(l.amount, s.currency))); p.append(r); });
  return p;
}
function askBox() {
  const box = el("div", "ask"); box.append(el("h4", "", "Ask about your spending"));
  const form = el("form", "ask-form"), inp = el("input"); inp.placeholder = "e.g. How much did I spend on food last month?"; inp.maxLength = 300; inp.setAttribute("aria-label", "Question");
  const go = el("button", "btn primary small", "Ask"); go.type = "submit"; form.append(inp, go);
  const out = el("div", "ask-out muted small");
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); if (inp.value.trim().length < 3) return;
    go.disabled = true; out.textContent = "Thinking…";
    try { const r = await api("POST", "/api/bank/ask", { question: inp.value, days: periodDays() }); out.classList.remove("muted"); out.textContent = r.answer; }
    catch (err) { out.classList.add("muted"); out.textContent = (err.data && err.data.help) || err.message; }
    go.disabled = false;
  });
  box.append(form, out); return box;
}
function dueRow(u) {
  const r = el("div", "due-row" + (u.overdue ? " overdue" : ""));
  const left = el("div", "due-main"); left.append(el("b", "", u.title || "Payment"), el("span", "chip " + (u.kind === "EMI" ? "emi" : "bill"), u.kind));
  const d = parseTs(u.due_date + "T00:00:00"), when = d ? d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) : u.due_date;
  const sub = u.overdue ? `Overdue · was due ${when}` : u.days_left === 0 ? "Due today" : `Due ${when} · in ${u.days_left} day${u.days_left === 1 ? "" : "s"}`;
  left.append(el("div", "muted small", sub + (u.min_due ? ` · minimum ${money(u.min_due, u.currency)}` : "")));
  r.append(left, el("span", "amt", money(u.amount, u.currency))); return r;
}

// ---------- Banking: bills, loans, accounts ----------
async function loadBankBills() {
  const box = $("bankBody"); skeleton(box, 3);
  const s = await api("GET", "/api/bank/summary?days=365");
  if (S.view !== "bank:bills") return;
  S.bankCats = s.categories;
  box.replaceChildren();
  const up = panel("Upcoming payments");
  if (!s.upcoming.length) up.append(el("p", "muted", "No upcoming bills or EMIs found. Statements and EMI reminders from your bank show up here."));
  s.upcoming.forEach((u) => up.append(dueRow(u))); box.append(up);
  const lp = panel("Loans & EMIs");
  if (!s.loans.length) lp.append(el("p", "muted", "No loans or EMIs detected yet."));
  s.loans.forEach((l) => {
    const r = el("div", "due-row"), left = el("div", "due-main");
    left.append(el("b", "", l.lender), el("div", "muted small", `${l.payments} EMI payment${l.payments === 1 ? "" : "s"} seen · last ${fmtDate(l.last_date)}`));
    r.append(left, el("span", "amt", money(l.emi_amount, l.currency) + " / month")); lp.append(r);
  });
  box.append(lp);
  const ap = panel("Accounts & cards (last balance seen)");
  if (!s.accounts.length) ap.append(el("p", "muted", "Balances appear when your bank alerts include “Avl Bal”."));
  s.accounts.forEach((a) => {
    const r = el("div", "due-row"), left = el("div", "due-main");
    left.append(el("b", "", "•••• " + a.account), el("div", "muted small", "as of " + fmtDate(a.as_of)));
    r.append(left, el("span", "amt", money(a.balance, a.currency))); ap.append(r);
  });
  box.append(ap);
  if (s.by_account.length) box.append(panel("Spending by account or card (last 12 months)", hbars(s.by_account.map((a) => ({ name: "•••• " + a.name, amount: a.amount })), s.currency)));
}

// ---------- Banking: transactions ----------
async function loadTransactions(reset) {
  if (reset) S.txPage = 1;
  const req = ++S.txReq, box = $("bankBody");
  if (reset) {
    box.replaceChildren(); const bar = el("div", "tx-filters");
    const kind = el("select"); kind.setAttribute("aria-label", "Type");
    [["", "All types"], ["spend", "Spending"], ["credit", "Income"], ["emi", "EMI paid"], ["due", "Bills due"], ["emi_due", "EMIs due"]].forEach(([v, l]) => { const o = el("option", "", l); o.value = v; kind.append(o); });
    kind.value = S.txKind; kind.addEventListener("change", () => { S.txKind = kind.value; loadTransactions(true); });
    const cat = el("select"); cat.setAttribute("aria-label", "Category");
    const all = el("option", "", "All categories"); all.value = ""; cat.append(all);
    (S.bankCats || []).forEach((c) => { const o = el("option", "", c); o.value = c; cat.append(o); });
    cat.value = S.txCat; cat.addEventListener("change", () => { S.txCat = cat.value; loadTransactions(true); });
    bar.append(kind, cat); box.append(bar, el("div", "rows tx-rows", ""), el("div", "more-wrap"));
    if (!S.bankCats) api("GET", "/api/bank/summary?days=30").then((s) => { S.bankCats = s.categories; if (S.view.startsWith("bank:")) loadTransactions(true); }).catch(() => {});
    skeleton(box.querySelector(".tx-rows"), 6);
  }
  const p = new URLSearchParams({ q: $("q").value, kind: S.txKind, category: S.txCat, page: S.txPage });
  const data = await api("GET", "/api/bank/transactions?" + p);
  if (req !== S.txReq) return;
  const rows = box.querySelector(".tx-rows"), more = box.querySelector(".more-wrap");
  if (!rows) return;
  if (reset) rows.replaceChildren();
  if (reset && !data.items.length) rows.append(emptyState("search", "No transactions found", "Try another filter, or sync to look for new bank emails.", "Sync now", () => sync({})));
  data.items.forEach((t) => rows.append(txRow(t)));
  more.replaceChildren();
  if (S.txPage * data.page_size < data.total) { const b = el("button", "btn", "Load more"); b.addEventListener("click", () => { S.txPage += 1; loadTransactions(false); }); more.append(b); }
}
function txRow(t) {
  const r = el("div", "tx-row"), credit = t.kind === "credit", future = t.kind === "due" || t.kind === "emi_due";
  const d = el("span", "date", fmtShort(t.txn_date));
  const m = el("span", "tx-main"); m.append(el("b", "", t.merchant || t.subject || "(no description)"));
  m.append(el("span", "muted small", [t.channel, t.account ? "•••• " + t.account : "", future ? "due " + (t.due_date || "?") : ""].filter(Boolean).join(" · ")));
  const sel = el("select", "tx-cat"); sel.setAttribute("aria-label", "Category");
  const cats = S.bankCats || [t.spend_cat || "Other"];
  (cats.includes(t.spend_cat) || !t.spend_cat ? cats : [...cats, t.spend_cat]).forEach((c) => { const o = el("option", "", c); o.value = c; sel.append(o); });
  sel.value = t.spend_cat || "Other"; if (t.cat_src === "ai") sel.title = "Categorised by AI"; if (t.cat_src === "user") sel.title = "Set by you";
  sel.addEventListener("change", async () => {
    try { const r2 = await api("PATCH", "/api/bank/transactions/" + t.id, { category: sel.value }); toast(r2.changed > 1 ? `Updated ${r2.changed} transactions from the same merchant` : "Category saved", "ok"); }
    catch (err) { toast(err.message, "error"); }
  });
  const amt = el("span", "amt " + (credit ? "pos" : future ? "" : "neg"), (credit ? "+" : future ? "" : "−") + money(t.amount, t.currency));
  const link = el("a", "icon-btn"); link.href = gmailLink(t.thread_id); link.target = "_blank"; link.rel = "noopener noreferrer"; link.title = "Open the email in Gmail"; link.append(icon("external"));
  const ex = el("button", "icon-btn"); ex.title = "Not a real transaction, or a transfer between my own accounts: exclude it"; ex.append(icon("ban"));
  ex.addEventListener("click", async () => {
    if (!confirm("Exclude this from your totals? (Use this for transfers between your own accounts or alerts that are not real payments.)")) return;
    try { await api("PATCH", "/api/bank/transactions/" + t.id, { excluded: true }); r.remove(); toast("Excluded from your totals", "ok"); loadWsStats(); } catch (err) { toast(err.message, "error"); }
  });
  const nm = m.firstChild; nm.classList.add("renamable"); nm.title = "Click to rename";
  nm.addEventListener("click", async () => {
    const v = prompt("Merchant name:", t.merchant || ""); if (v === null) return;
    try { await api("PATCH", "/api/bank/transactions/" + t.id, { merchant: v }); nm.textContent = v || t.subject || "(no description)"; } catch (err) { toast(err.message, "error"); }
  });
  r.append(d, m, sel, amt, link, ex); return r;
}

// ---------- Personal ----------
const P_CHIP = { family: "family", friend: "friend", people: "people", starred: "starred", important: "important" };
function personalRow(m) {
  const row = el("div", "erow" + (m.is_unread ? " unread" : "")); row.tabIndex = 0; row.dataset.id = m.id;
  if (S.selectedId === m.id) row.classList.add("sel");
  const subj = el("span", "subj-cell"); subj.append(el("span", "chip " + (P_CHIP[m.category] || "people"), m.category === "people" ? "contact" : m.category));
  subj.append(el("span", "s", m.subject || "(no subject)"), el("span", "snip", " – " + (m.ai_summary || m.snippet || "")));
  const flag = el("span", "fitcell"); if (m.needs_reply) flag.append(el("span", "fit mid", "reply"));
  row.append(el("span", "udot"), el("span", "sender", senderName(m.sender)), subj, flag, el("span", "date", fmtShort(m.received_at)));
  const open = () => openPersonal(m.id, row);
  row.addEventListener("click", open); row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return row;
}
async function loadPersonal(reset) {
  if (reset) S.pPage = 1;
  const req = ++S.pReq, box = $("personalBody");
  if (reset) { box.replaceChildren(el("div", "rows", "")); skeleton(box.firstChild, 5); }
  const f = S.pFilter === "inbox" ? "" : S.pFilter;
  const data = await api("GET", "/api/personal/mails?" + new URLSearchParams({ q: $("q").value, filter: f, page: S.pPage }));
  if (req !== S.pReq || !S.view.startsWith("personal:")) return;
  const rows = box.firstChild;
  if (reset) rows.replaceChildren();
  if (reset && !data.items.length) {
    const searching = $("q").value.trim();
    rows.append(searching ? emptyState("search", "No mail matches your search", "Try fewer words.")
      : emptyState("heart", "Nothing here yet", "Add family and friends under Manage people, or star a message in Gmail. SmartMail then collects their mail here.", "Manage people", () => setView("personal:people")));
  }
  data.items.forEach((m) => rows.append(personalRow(m)));
  $("personalCount").textContent = data.total ? `${data.total} email${data.total === 1 ? "" : "s"}` : "";
  $("personalMore").classList.toggle("hidden", S.pPage * data.page_size >= data.total);
  const pend = S.wsStats ? S.wsStats.personal.pending_ai : 0;
  $("personalAI").classList.toggle("hidden", !(S.aiEnabled && pend));
}
$("personalMore").addEventListener("click", () => { S.pPage += 1; loadPersonal(false); });
$("personalAI").addEventListener("click", () => wsAnalyze("personal"));
async function openPersonal(id, row) {
  S.selectedId = id;
  document.querySelectorAll(".erow.sel").forEach((r) => r.classList.remove("sel")); if (row) row.classList.add("sel");
  placePane();
  let m; try { m = await api("GET", "/api/ws/mails/" + id); } catch (_) { return; }
  const pane = $("emailPane"); pane.replaceChildren();
  const bar = el("div", "pane-bar"); bar.append(iconBtn("back", "Back", closeEmailPane), el("span", "spacer"), extLink(gmailLink(m.thread_id), "Open in Gmail"), iconBtn("x", "Close", closeEmailPane));
  const body = el("div", "pane-body"); body.append(el("h2", "", m.subject || "(no subject)"));
  const tags = el("div", "row"); tags.style.marginTop = "0"; tags.append(el("span", "chip " + (P_CHIP[m.category] || "people"), m.category === "people" ? "contact" : m.category));
  if (m.needs_reply) tags.append(el("span", "fit mid", "needs reply")); body.append(tags);
  const meta = el("div", "pane-meta"), who = el("div", "who");
  who.append(el("b", "", senderName(m.sender)), el("span", "muted small", `${m.sender_email} · ${parseTs(m.received_at) ? parseTs(m.received_at).toLocaleString() : ""}`));
  meta.append(avatar(senderName(m.sender)), who); body.append(meta);
  if (m.ai_summary) { const box = el("div", "ai-box"); box.append(ic("sparkle"), el("div", "", m.ai_summary)); body.append(box); }
  body.append(el("div", "mail-body", m.body_text || m.snippet || "(no text)"));
  if (["starred", "important"].includes(m.category)) {
    const act = el("div", "row wrap"); act.append(el("span", "muted small", "Always keep mail from this sender here:"));
    [["family", "Add as family"], ["friend", "Add as friend"]].forEach(([rel, label]) => {
      const b = el("button", "btn small", label);
      b.addEventListener("click", async () => {
        try { await api("POST", "/api/people", { email: m.sender_email, name: senderName(m.sender), relation: rel }); toast("Added to People", "ok"); closeEmailPane(); sync({ silent: true, rescan: true }); }
        catch (err) { toast(err.message, "error"); }
      });
      act.append(b);
    });
    body.append(act);
  }
  pane.append(bar, body); pane.classList.add("open"); pane.scrollTop = 0; syncBackdrop();
}

// ---------- Personal: people ----------
async function loadPeople() {
  const box = $("personalBody"); box.replaceChildren();
  $("personalCount").textContent = ""; $("personalAI").classList.add("hidden"); $("personalMore").classList.add("hidden");
  const data = await api("GET", "/api/people");
  const form = el("form", "people-form");
  const name = el("input"); name.placeholder = "Name"; name.maxLength = 80; name.setAttribute("aria-label", "Name");
  const email = el("input"); email.type = "email"; email.placeholder = "email@example.com"; email.required = true; email.setAttribute("aria-label", "Email");
  const rel = el("select"); rel.setAttribute("aria-label", "Relationship");
  [["family", "Family"], ["friend", "Friend"], ["other", "Other"]].forEach(([v, l]) => { const o = el("option", "", l); o.value = v; rel.append(o); });
  const add = el("button", "btn primary", "Add person"); add.type = "submit";
  form.append(name, email, rel, add);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); add.disabled = true;
    try { await api("POST", "/api/people", { name: name.value, email: email.value, relation: rel.value }); toast("Added. Looking for their emails…", "ok"); sync({ silent: true, rescan: true }); loadPeople(); }
    catch (err) { toast(err.message, "error"); } finally { add.disabled = false; }
  });
  const p = panel("People whose email you want here", form);
  p.append(el("p", "muted small", "Mail from these addresses, plus anything you star in Gmail or Gmail marks as important (excluding promotions), appears in your Personal workspace."));
  const list = el("div", "people-list");
  if (!data.items.length) list.append(el("p", "muted", "No one added yet."));
  data.items.forEach((x) => {
    const r = el("div", "due-row"), left = el("div", "due-main");
    left.append(avatar(x.name || x.email));
    const t = el("div"); t.append(el("b", "", x.name || x.email), el("div", "muted small", x.name ? x.email : ""));
    left.append(t, el("span", "chip " + (x.relation === "family" ? "family" : x.relation === "friend" ? "friend" : "people"), x.relation));
    const del = iconBtn("trash", "Remove", async () => {
      if (!confirm("Remove " + (x.name || x.email) + "? Their mail leaves the Personal workspace unless starred.")) return;
      await api("DELETE", "/api/people/" + x.id); loadPeople(); loadWsStats();
    });
    r.append(left, del); list.append(r);
  });
  p.append(list); box.append(p); loadWsStats();
}
