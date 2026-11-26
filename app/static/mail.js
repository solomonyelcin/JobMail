"use strict";
// Job-mail workflow: key details, resume match, ready-made replies and the "Needs action" list.
// Like app.js, all email text goes in with textContent / text nodes, never innerHTML.

// ---------- links ----------
const URL_RE = /https?:\/\/[^\s<>"')\]]+/gi;
function safeUrl(u) { try { const x = new URL(u); return x.protocol === "http:" || x.protocol === "https:" ? x.href : ""; } catch (_) { return ""; } }
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (_) { return u; } }
function linkEl(url, label) {
  const a = el("a", "ext", label || hostOf(url)); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
}
// Put `text` into `parent`, turning http(s) URLs into links and leaving everything else as plain text.
function linkify(parent, text) {
  let last = 0; URL_RE.lastIndex = 0;
  for (let m; (m = URL_RE.exec(text));) {
    const raw = m[0].replace(/[.,;:!?]+$/, ""), url = safeUrl(raw);
    if (!url) continue;
    parent.append(text.slice(last, m.index), linkEl(url, raw.length > 60 ? raw.slice(0, 57) + "…" : raw));
    last = m.index + raw.length; URL_RE.lastIndex = last;
  }
  parent.append(text.slice(last));
}
function copyText(text, what) {
  const done = () => toast((what || "Text") + " copied", "ok");
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => toast("Could not copy", "error"));
  else toast("Could not copy", "error");
}

// ---------- small building blocks ----------
function xpanel(title, ...kids) {
  const p = el("section", "xpanel"); if (title) p.append(el("h4", "", title)); p.append(...kids); return p;
}
function tags(items, cls) {
  const box = el("div", "tags"); items.forEach((t) => box.append(el("span", "tag " + cls, t))); return box;
}
function kv(label, ...val) {
  const r = el("div", "kv"); r.append(el("span", "k", label)); const v = el("span", "v"); v.append(...val); r.append(v); return r;
}
function daysLeft(iso) {
  const d = new Date(iso + "T00:00:00"); if (isNaN(d)) return "";
  const n = Math.round((d - new Date(new Date().toDateString())) / 86400000);
  return n === 0 ? "today" : n === 1 ? "tomorrow" : n > 1 ? `in ${n} days` : n === -1 ? "yesterday" : `${-n} days ago`;
}

// ---------- key details ----------
function detailsPanel(e, info) {
  const rows = [];
  if (info.apply_to.length) {
    const v = el("span", "v-list");
    info.apply_to.forEach((a) => { const b = el("button", "chipbtn", a); b.title = "Copy address"; b.addEventListener("click", () => copyText(a, "Address")); v.append(b); });
    rows.push(kv("Send applications to", v));
  }
  info.dates.forEach((d) => {
    const when = daysLeft(d.date), past = /ago|yesterday/.test(when);
    const label = d.kind === "deadline" ? "Deadline" : d.kind === "schedule" ? "Scheduled" : "Date";
    const r = kv(label, `${fmtDate(d.date)}${when ? " (" + when + ")" : ""}`);
    r.title = d.context; if (d.kind === "deadline" && past) r.classList.add("past"); rows.push(r);
  });
  if (info.location) rows.push(kv("Location", info.location));
  if (info.work_mode.length) rows.push(kv("Work mode", info.work_mode.join(", ")));
  if (info.experience) rows.push(kv("Experience", info.experience));
  if (info.pay) rows.push(kv("Pay", info.pay));
  if (info.notice) rows.push(kv("Notice", info.notice));
  if (info.links.length) {
    const v = el("span", "v-list");
    info.links.slice(0, 5).forEach((u) => { const x = safeUrl(u); if (x) v.append(linkEl(x, hostOf(x) + (new URL(x).pathname.length > 1 ? new URL(x).pathname.slice(0, 24) : ""))); });
    rows.push(kv("Links", v));
  }
  if (!rows.length) return null;
  return xpanel("Key details", ...rows);
}

// ---------- resume match ----------
function scoreChip(score) { return score === null || score === undefined ? null : fitBadge(score); }
function matchPanel(e, d) {
  const local = d.local_match;
  // an interview invite that names no skills has nothing to compare, so skip the panel unless AI can add something
  if (local && local.score === null && !d.ai_match && !["opening", "recruiter"].includes(e.category)) return null;
  const box = xpanel("How you fit");
  if (!d.has_resume && !local) {
    box.append(el("p", "muted small", "Upload your resume on the Profile page to compare it with this mail."));
    return box;
  }
  if (local) {
    const head = el("div", "row match-head");
    const sc = scoreChip(local.score); if (sc) head.append(sc);
    head.append(el("span", "", local.verdict)); box.append(head);
    if (local.matched.length) box.append(el("div", "lbl", "On your resume"), tags(local.matched, "ok"));
    if (local.missing.length) box.append(el("div", "lbl", "Asked for, not on your resume"), tags(local.missing, "gap"));
    if (local.soft_missing.length) box.append(el("div", "lbl", "Also mentioned"), tags(local.soft_missing, "soft"));
    local.notes.forEach((n) => box.append(el("p", "muted small", n)));
    box.append(el("p", "muted small", "Quick keyword comparison. It checks skill names only."));
  }
  const ai = el("div", "ai-match"); box.append(ai);
  const show = (m) => {
    ai.replaceChildren();
    const head = el("div", "row match-head");
    const sc = scoreChip(m.fit_score); if (sc) head.append(sc);
    head.append(el("span", "", m.verdict || "AI analysis")); ai.append(el("div", "lbl", "AI analysis"), head);
    [["Strengths", m.strengths, "ok"], ["Gaps", m.gaps, "gap"], ["Emphasise", m.emphasise, "info"], ["Ask them", m.questions, "soft"]].forEach(([t, list, cls]) => {
      if (list && list.length) { ai.append(el("div", "lbl", t)); const ul = el("ul", "plain"); list.forEach((x) => ul.append(el("li", "", x))); ai.append(ul); }
    });
    if (m.next_step) ai.append(el("p", "next", "Next: " + m.next_step));
    const redo = el("button", "link small", "Re-run"); redo.addEventListener("click", () => run(true)); ai.append(redo);
  };
  const run = async (refresh) => {
    ai.replaceChildren(el("p", "muted small", "Comparing with your resume…"));
    try { show(await api("POST", `/api/emails/${e.id}/match`, { refresh: !!refresh })); }
    catch (err) { ai.replaceChildren(el("p", "error small", (err.data && (err.data.help || (err.data.error === "no_resume" ? "Upload a resume or fill in your profile first." : ""))) || "AI analysis failed. Try again.")); button(); }
  };
  const button = () => {
    if (!S.aiEnabled) return;
    const b = el("button", "btn small"); b.append(icon("sparkle"), "Analyse with AI");
    b.addEventListener("click", () => run(false)); ai.append(b);
  };
  if (d.ai_match) show(d.ai_match); else button();
  return box;
}

// ---------- reply bar ----------
function replyBar(e, d, refresh) {
  const box = xpanel("Reply");
  if (d.replied_at) box.append(el("p", "muted small", `Draft created ${ago(d.replied_at)}. Open Gmail drafts to send it.`));
  const info = d.info, canApply = info.apply_to.length > 0;
  const row = el("div", "row wrap");
  if (canApply) {
    const b = el("button", "btn primary"); b.append(icon("mail"), "Apply by email"); b.addEventListener("click", () => openCompose(e, "apply")); row.append(b);
  }
  if (S.aiEnabled) {
    const b = el("button", "btn" + (canApply ? "" : " primary")); b.append(icon("sparkle"), "Reply with AI"); b.addEventListener("click", () => openCompose(e, "ai")); row.append(b);
  }
  box.append(row);
  const quick = d.templates.filter((t) => t.suggested && t.id !== "apply").slice(0, 4);
  if (quick.length) {
    const q = el("div", "tags");
    quick.forEach((t) => { const b = el("button", "chipbtn", t.label); b.addEventListener("click", () => openCompose(e, t.id)); q.append(b); });
    box.append(el("div", "lbl", "Ready-made replies"), q);
  }
  const more = el("select", "tpl-more"); more.setAttribute("aria-label", "More templates");
  more.append(new Option("More templates…", ""));
  d.templates.forEach((t) => more.append(new Option(t.label, t.id)));
  more.addEventListener("change", () => { if (more.value) openCompose(e, more.value); more.value = ""; });
  box.append(more);
  const foot = el("div", "row wrap");
  const done = el("button", "btn small", d.done ? "Put back on my list" : "Mark as done");
  done.addEventListener("click", async () => {
    await api("POST", `/api/emails/${e.id}/done`, { done: !d.done }); toast(d.done ? "Back on your list" : "Marked as done", "ok");
    loadStats(); if (S.view === "actions") loadActions(); refresh();
  });
  foot.append(done); box.append(foot);
  return box;
}

// ---------- thread ----------
function threadPanel(d) {
  if (!d.thread.length) return null;
  const box = xpanel(`Conversation (${d.thread.length} other message${d.thread.length === 1 ? "" : "s"})`);
  d.thread.forEach((m) => {
    const r = el("button", "trow"); r.append(chip(m.category), el("span", "grow", `${senderName(m.sender)} · ${m.subject || "(no subject)"}`), el("span", "muted small", fmtShort(m.received_at)));
    r.addEventListener("click", () => openEmail(m.id)); box.append(r);
  });
  return box;
}

// ---------- reading pane extras ----------
async function renderMailExtras(e, top, rest) {
  let d;
  try { d = await api("GET", `/api/emails/${e.id}/details`); } catch (_) { return; }
  if (S.selectedId !== e.id) return; // the user moved on to another email
  const draw = async () => { try { d = await api("GET", `/api/emails/${e.id}/details`); } catch (_) { return; } paint(); };
  const paint = () => {
    top.replaceChildren(); rest.replaceChildren();
    const det = detailsPanel(e, d.info);
    top.append(replyBar(e, d, draw)); if (det) top.append(det);
    const mp = matchPanel(e, d); if (mp) rest.append(mp); const th = threadPanel(d); if (th) rest.append(th);
  };
  paint();
}

// ---------- Needs action ----------
async function loadActions() {
  const box = $("actionsList"); skeleton(box, 3);
  let data; try { data = await api("GET", "/api/actions"); } catch (_) { box.replaceChildren(); return; }
  box.replaceChildren();
  $("actionsCount").textContent = data.total ? `${data.total} waiting` : "";
  if (!data.items.length) { box.append(emptyState("check", "Nothing needs a reply", "New interviews, offers and recruiter messages will show up here after the next sync.", "Sync now", () => sync({}))); return; }
  data.items.forEach((m) => box.append(actionCard(m)));
}
function actionCard(m) {
  const card = el("div", "match action" + (m.is_unread ? " unread" : ""));
  const body = el("div", "grow");
  const head = el("div", "row"); head.append(chip(m.category)); head.append(el("b", "", m.role ? m.role + (m.company ? " at " + m.company : "") : (m.company || m.subject || "(no subject)")));
  body.append(head, el("div", "why", m.reason));
  body.append(el("div", "muted", m.ai_summary || m.snippet || ""));
  body.append(el("div", "muted small", `${senderName(m.sender)} · ${ago(m.received_at)}`));
  const actions = el("div", "row wrap");
  const open = el("button", "btn primary", "Open and reply"); open.addEventListener("click", () => openEmail(m.id));
  const done = el("button", "btn", "Done");
  done.addEventListener("click", async () => { await api("POST", `/api/emails/${m.id}/done`, { done: true }); card.remove(); loadStats(); toast("Marked as done", "ok"); });
  actions.append(open, done); body.append(actions); card.append(body);
  return card;
}

// ---------- the email itself, as Gmail shows it ----------
// HTML entities left in older plain-text rows (&#x27; &nbsp;) are decoded with an inert parser, never innerHTML.
function decodeEntities(t) {
  if (!/&[#\w]+;/.test(t)) return t;
  return (new DOMParser().parseFromString(t, "text/html").documentElement.textContent || "").replace(/\u00a0/g, " ");
}
function buildMailViewer(e) {
  const wrap = el("div", "mail-viewer");
  const bar = el("div", "viewer-bar");
  const seg = el("div", "seg"); seg.setAttribute("role", "tablist");
  const bOrig = el("button", "", "Original"), bText = el("button", "", "Text");
  [bOrig, bText].forEach((b) => { b.type = "button"; b.setAttribute("role", "tab"); });
  seg.append(bOrig, bText);
  const imgs = el("button", "link small"); imgs.type = "button";
  const gm = el("a", "link small ext", "Open in Gmail"); gm.href = `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(e.gmail_id || "")}`;
  gm.target = "_blank"; gm.rel = "noopener noreferrer";
  const note = el("span", "muted small");
  bar.append(seg, imgs, note); if (e.gmail_id) bar.append(gm);
  const stage = el("div", "viewer-stage");
  wrap.append(bar, stage);

  const state = { mode: store("jm-view") === "text" ? "text" : "original", images: store("jm-images") !== "0", ro: null };
  const showText = (why) => {
    state.mode = "text"; seg.classList.toggle("text", true); bOrig.classList.remove("on"); bText.classList.add("on");
    imgs.classList.add("hidden"); note.textContent = why || "";
    stage.replaceChildren(); const mb = el("div", "mail-body"); linkify(mb, decodeEntities(e.body_text || e.snippet || "(no text)")); stage.append(mb);
  };
  const showOriginal = () => {
    state.mode = "original"; bText.classList.remove("on"); bOrig.classList.add("on");
    imgs.classList.remove("hidden"); imgs.textContent = state.images ? "Hide images" : "Show images"; note.textContent = "";
    const frame = el("iframe", "mail-frame");
    frame.title = "Email: " + (e.subject || "");
    // no allow-scripts: nothing inside the email can run code. allow-same-origin only lets this page size the frame.
    frame.setAttribute("sandbox", "allow-same-origin allow-popups allow-popups-to-escape-sandbox");
    frame.setAttribute("referrerpolicy", "no-referrer");
    frame.src = `/api/emails/${e.id}/view?images=${state.images ? 1 : 0}`;
    frame.style.height = "240px";
    let fitting = false;
    const fit = () => {
      if (fitting) return; fitting = true;
      try {
        const d = frame.contentDocument; if (!d || !d.body || !d.documentElement) return;
        // like Gmail on a phone: a fixed-width newsletter is scaled down to fit instead of scrolling sideways
        d.body.style.zoom = "";
        const natural = d.documentElement.scrollWidth, avail = frame.clientWidth;
        if (natural > avail + 1 && avail > 0) d.body.style.zoom = String(Math.max(0.3, avail / natural));
        frame.style.height = Math.max(120, d.documentElement.scrollHeight + 2) + "px";
      } catch (_) { /* cross-origin: keep fixed height */ } finally { fitting = false; }
    };
    window.addEventListener("resize", fit);
    frame.addEventListener("load", () => {
      let d = null; try { d = frame.contentDocument; } catch (_) { /* ignore */ }
      if (!d) return;
      if (d.querySelector('meta[name="jm-error"]')) { showText("The original could not be loaded, so this is the text version."); return; }
      fit();
      const held = Number((d.querySelector('meta[name="jm-remote"]') || {}).content || 0);
      note.textContent = held && !state.images ? `${held} image${held === 1 ? "" : "s"} hidden` : "";
      if (window.ResizeObserver && d.body) { if (state.ro) state.ro.disconnect(); state.ro = new ResizeObserver(fit); state.ro.observe(d.body); }
      d.querySelectorAll("img").forEach((i) => i.addEventListener("load", fit));
    });
    stage.replaceChildren(frame);
  };
  bOrig.addEventListener("click", () => { store("jm-view", "original"); showOriginal(); });
  bText.addEventListener("click", () => { store("jm-view", "text"); showText(); });
  imgs.addEventListener("click", () => { state.images = !state.images; store("jm-images", state.images ? "1" : "0"); showOriginal(); });
  if (state.mode === "text") showText(); else showOriginal();
  return wrap;
}
