"use strict";
/* Clippy web UI — vanilla JS, no build step. */

// ───────────────────────── helpers ─────────────────────────
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("clippy-" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("clippy-" + k, JSON.stringify(v)); } catch {} },
};
const finePointer = matchMedia("(pointer: fine)").matches;

const ICONS = {
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/>',
  trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
  checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  pencil: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  youtube: '<path d="M2.5 17a24.12 24.12 0 0 1 0-10 2 2 0 0 1 1.4-1.4 49.56 49.56 0 0 1 16.2 0A2 2 0 0 1 21.5 7a24.12 24.12 0 0 1 0 10 2 2 0 0 1-1.4 1.4 49.55 49.55 0 0 1-16.2 0A2 2 0 0 1 2.5 17"/><path d="m10 15 5-3-5-3z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  chevR: '<path d="m9 18 6-6-6-6"/>',
  chevL: '<path d="m15 18-6-6 6-6"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  film: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
  calendar: '<rect width="18" height="18" x="3" y="4" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  sliders: '<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  phone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  type: '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
  smile: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/>',
  columns: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 12h18"/>',
  zoom: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6"/><path d="M8 11h6"/>',
  mute: '<path d="M11 5 6 9H2v6h4l5 4V5Z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
  progress: '<path d="M3 12h18"/><path d="M3 6h12"/><path d="M3 18h7"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
  chat: '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/>',
  tv: '<rect width="20" height="15" x="2" y="7" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/>',
  ball: '<circle cx="12" cy="12" r="10"/><path d="M4.93 4.93c4.08 2.38 8.22 8.24 9.39 14.85"/><path d="M19.07 4.93c-4.08 2.38-8.22 8.24-9.39 14.85"/><path d="M2 12h20"/>',
  briefcase: '<rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  laugh: '<circle cx="12" cy="12" r="10"/><path d="M18 13a6 6 0 0 1-6 5 6 6 0 0 1-6-5h12Z"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/>',
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  swords: '<polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" x2="19" y1="19" y2="13"/><line x1="16" x2="20" y1="16" y2="20"/><line x1="19" x2="21" y1="21" y2="19"/><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/><line x1="5" x2="9" y1="14" y2="18"/><line x1="7" x2="4" y1="17" y2="20"/><line x1="3" x2="5" y1="19" y2="21"/>',
  cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
  gamepad: '<line x1="6" x2="10" y1="11" y2="11"/><line x1="8" x2="8" y1="9" y2="13"/><line x1="15" x2="15.01" y1="12" y2="12"/><line x1="18" x2="18.01" y1="10" y2="10"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/>',
  power: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
  stop: '<rect width="14" height="14" x="5" y="5" rx="2"/>',
  puzzle: '<path d="M15.39 4.39a1 1 0 0 0 1.68-.474 2.5 2.5 0 1 1 3.014 3.015 1 1 0 0 0-.474 1.68l1.683 1.682a2.414 2.414 0 0 1 0 3.414L19.61 15.39a1 1 0 0 1-1.68-.474 2.5 2.5 0 1 0-3.014 3.015 1 1 0 0 1 .474 1.68l-1.683 1.682a2.414 2.414 0 0 1-3.414 0L8.61 19.61a1 1 0 0 0-1.68.474 2.5 2.5 0 1 1-3.014-3.015 1 1 0 0 0 .474-1.68l-1.683-1.682a2.414 2.414 0 0 1 0-3.414L4.39 8.61a1 1 0 0 1 1.68.474 2.5 2.5 0 1 0 3.014-3.015 1 1 0 0 1-.474-1.68l1.683-1.682a2.414 2.414 0 0 1 3.414 0z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
};
const icon = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;
function hydrateIcons(root = document) { $$("[data-icon]", root).forEach((el) => { el.innerHTML = icon(el.dataset.icon); el.removeAttribute("data-icon"); }); }

async function apiErr(r) { try { const j = await r.json(); return new Error(j.detail || r.statusText); } catch { return new Error(r.statusText || "Request failed"); } }
const api = {
  async get(u) { const r = await fetch(u); if (!r.ok) throw await apiErr(r); return r.json(); },
  async post(u, body) { const r = await fetch(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body ?? {})}); if (!r.ok) throw await apiErr(r); return r.json(); },
  async del(u) { const r = await fetch(u, {method: "DELETE"}); if (!r.ok) throw await apiErr(r); return r.json(); },
};
function toast(msg, kind = "ok", action = null, ms = 4500) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = icon(kind === "ok" ? "checkCircle" : kind === "bad" ? "alert" : "info") + `<span>${esc(msg)}</span>` +
    (action ? `<button type="button" class="btn sm">${esc(action.label)}</button>` : "");
  if (action) $("button", t).onclick = () => { action.run(); t.remove(); };
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.transition = "opacity .3s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, ms);
}
const fail = (e) => toast(e.message || String(e), "bad");

// formatting: the interface is English, so numbers and relative times are English too
const NUM = new Intl.NumberFormat("en", {notation: "compact", maximumFractionDigits: 1});
const fmt = (n) => NUM.format(+n || 0);
const DATE = new Intl.DateTimeFormat("en", {dateStyle: "medium", timeStyle: "short"});
const fmtDate = (ts) => ts ? DATE.format(new Date(ts * 1000)) : "–";
const REL = new Intl.RelativeTimeFormat("en", {numeric: "auto"});
function rel(ts) {
  if (!ts) return "never";
  const s = ts - Date.now() / 1000, a = Math.abs(s);
  if (a < 60) return s < 0 ? "just now" : "any moment";
  for (const [u, sec] of [["day", 86400], ["hour", 3600], ["minute", 60]]) if (a >= sec) return REL.format(Math.round(s / sec), u);
  return "just now";
}
const fmtDur = (s) => { s = +s || 0; const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${m}m` : `${m}m`; };
const fmtAge = (d) => d == null ? "–" : d < 1 ? `${Math.max(1, Math.round(d * 24))}h` : `${Math.round(d)}d`;
const fmtBytes = (b) => { b = +b || 0; for (const [u, d] of [["GB", 1e9], ["MB", 1e6], ["KB", 1e3]]) if (b >= d) return (b / d).toFixed(b >= 10 * d ? 0 : 1) + " " + u; return b + " B"; };
const scoreCls = (s) => s >= 85 ? "hi" : "";
const everyLabel = (h) => !h ? "Only when you press Run" : h < 24 ? `Every ${h} hours` : h === 24 ? "Every day" : h === 168 ? "Every week" : `Every ${h / 24} days`;
const initials = (s) => (s || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

const NICHES = {
  "podcasts": ["mic", "Long talks, big opinions"], "interviews": ["chat", "Celebrities, experts, stories"],
  "challenges": ["trophy", "MrBeast-style money and stunts"], "streamers": ["tv", "Kick and Twitch highlights"],
  "sports": ["ball", "Athletes and sports talk"], "business": ["briefcase", "Money, hustle, founders"],
  "comedy": ["laugh", "Stand-up and funny shows"], "motivation": ["flame", "Speeches and life advice"],
  "debate": ["swords", "Heated arguments"], "true crime": ["search", "Cases and mysteries"],
  "tech & ai": ["cpu", "AI, gadgets, tech talk"], "gaming": ["gamepad", "Gaming talk and videos"],
};
const nicheLabel = (n) => ({"tech & ai": "Tech & AI"}[n] || n[0].toUpperCase() + n.slice(1));
const nicheIcon = (n) => icon((NICHES[n] || ["film"])[0]);
// caption styles and countdown themes: the built-in ones, then what extensions add (loadLooks)
let STYLES = [["beast", "Beast", "Comic, bouncy, tilted", "/static/styles/beast.jpg"], ["hormozi", "Hormozi", "Bold, colored keywords", "/static/styles/hormozi.jpg"],
  ["box", "Box", "Highlight box", "/static/styles/box.jpg"], ["clean", "Clean", "Calm and minimal", "/static/styles/clean.jpg"]];
let THEMES = [{id: "funny", name: "Funniest", emoji: "😂"}, {id: "crazy", name: "Craziest", emoji: "🤯"}, {id: "shocking", name: "Most shocking", emoji: "😱"}, {id: "wholesome", name: "Most wholesome", emoji: "🥹"}];
let PRESETS = [];                                   // saved styles (clippy/presets.py)
async function loadPresets() { try { PRESETS = (await api.get("/api/presets")).presets; } catch {} return PRESETS; }
const presetOptions = (sel, none = "None") => `<option value="">${esc(none)}</option>${PRESETS.map((p) => `<option value="${esc(p.id)}" ${p.id === sel ? "selected" : ""}>${esc(p.name)}</option>`).join("")}`;
async function loadLooks() {
  try { STYLES = (await api.get("/api/styles")).map((x) => [x.id, x.name, x.about, x.preview || ""]); } catch {}
  try { THEMES = await api.get("/api/top-themes"); } catch {}
  await loadPresets();
}
// name and save a style; saving under a name that exists updates that style
function savePresetDialog(settings, name = "") {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg"; bg.dataset.confirm = "1";
    bg.innerHTML = `<div class="modal small" role="dialog" aria-modal="true" aria-labelledby="psT">
      <div class="mh"><h2 id="psT">Save as a style</h2></div>
      <div class="mb"><p class="muted small" style="margin:6px 0 12px">Use it again in Make Clips, Find a Quote and Autopilot channels. A name you've used before updates that style.</p>
        <div class="lbl"><label for="psName">Name</label></div><input class="input" id="psName" type="text" maxlength="40" autocomplete="off" placeholder="Podcast, Gaming…" value="${esc(name)}">
        <p class="err-text small hidden" id="psErr" style="margin:8px 0 0"></p></div>
      <div class="mf"><span class="grow"></span><button type="button" class="btn quiet" data-no>Cancel</button><button type="button" class="btn primary" data-yes>Save Style</button></div></div>`;
    const done = (v) => { bg.remove(); document.removeEventListener("keydown", key, true); resolve(v); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); done(null); } else if (e.key === "Enter" && e.target.id === "psName") { e.preventDefault(); go(); } };
    const go = async () => {
      try { const pr = await api.post("/api/presets", {name: $("#psName", bg).value, settings}); await loadPresets(); toast(`Saved the style “${pr.name}”`); done(pr); }
      catch (e) { $("#psErr", bg).textContent = e.message; $("#psErr", bg).classList.remove("hidden"); }
    };
    document.addEventListener("keydown", key, true);
    $("[data-no]", bg).onclick = () => done(null);
    $("[data-yes]", bg).onclick = go;
    document.body.appendChild(bg);
    $("#psName", bg).focus(); $("#psName", bg).select();
  });
}
const stylePic = (pv, name) => pv ? `<img src="${esc(pv)}" alt="" width="360" height="640" loading="lazy">` : `<div class="nopic"><b>${esc(name)}</b></div>`;
const COLORS = ["#ffe135", "#3dff7a", "#ff4fd8", "#3ad8ff", "#ff8a1f", "#ffffff"];
const LANGS = [["en", "English"], ["no", "Norwegian"], ["es", "Spanish"], ["de", "German"], ["fr", "French"], ["pt", "Portuguese"], ["any", "Any language"]];

const state = {niches: null, overview: null, status: null, makeJob: null, lastResult: null, finder: null};

// ───────────────────────── dialogs ─────────────────────────
function openModal(html, {small = false, onClose = null, label = "Dialog"} = {}) {
  closeModal(true);
  const bg = document.createElement("div");
  bg.className = "modal-bg"; bg.id = "modal";
  bg.innerHTML = `<div class="modal ${small ? "small" : ""}" role="dialog" aria-modal="true" aria-label="${esc(label)}">${html}</div>`;
  bg.addEventListener("mousedown", (e) => { if (e.target === bg) closeModal(); });
  bg._onClose = onClose; bg._opener = document.activeElement;
  document.body.appendChild(bg);
  hydrateIcons(bg);
  return bg;
}
async function closeModal(force = false) {
  const m = $("#modal"); if (!m) return;
  if (!force && m._onClose && (await m._onClose()) === false) return;   // e.g. "discard changes?" answered no
  m.remove();
  m._opener?.focus?.();
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#modal") && !$(".modal-bg[data-confirm]")) closeModal(); });

function confirmDialog({title, body = "", confirm = "Confirm", danger = false}) {
  return new Promise((resolve) => {
    const prev = $("#modal");
    if (prev) prev.style.visibility = "hidden";            // shown over an open dialog (e.g. the wizard)
    const bg = document.createElement("div");
    bg.className = "modal-bg"; bg.dataset.confirm = "1";
    bg.innerHTML = `<div class="modal small" role="alertdialog" aria-modal="true" aria-labelledby="cfT">
      <div class="mh"><h2 id="cfT">${esc(title)}</h2></div><div class="mb"><p class="muted" style="margin:6px 0 0">${body}</p></div>
      <div class="mf"><span class="grow"></span><button type="button" class="btn quiet" data-no>Cancel</button>
      <button type="button" class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(confirm)}</button></div></div>`;
    const done = (v) => { bg.remove(); if (prev) prev.style.visibility = ""; document.removeEventListener("keydown", key, true); resolve(v); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); done(false); } };
    document.addEventListener("keydown", key, true);
    $("[data-no]", bg).onclick = () => done(false);
    $("[data-yes]", bg).onclick = () => done(true);
    bg.addEventListener("mousedown", (e) => { if (e.target === bg) done(false); });
    document.body.appendChild(bg);
    $("[data-yes]", bg).focus();
  });
}

// ───────────────────────── router ─────────────────────────
const pages = {};
let timers = [], leaveGuard = null, lastHash = location.hash;
const repeat = (ms, fn) => timers.push(setInterval(fn, ms));
const params = () => new URLSearchParams(location.hash.split("?")[1] || "");
function setParam(k, v) { const p = params(); p.set(k, v); history.replaceState(null, "", `${location.hash.split("?")[0]}?${p}`); lastHash = location.hash; }
const TITLES = {home: "Home", make: "Make Clips", find: "Find Videos", auto: "Autopilot", review: "Review", library: "Library", ai: "AI & Tools", ext: "Extensions", settings: "Settings"};
async function route() {
  let name = (location.hash.slice(1) || "home").split("?")[0];
  if (name === "autopilot") name = "auto";
  const page = pages[name] ? name : "home";
  timers.forEach(clearInterval); timers = [];
  leaveGuard = null;
  $$("#nav a").forEach((a) => { const on = a.dataset.page === page; a.classList.toggle("on", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const el = $("#page");
  el.innerHTML = "";
  el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter");   // the page settles in once
  clearTimeout(route.enterT); route.enterT = setTimeout(() => el.classList.remove("enter"), 900);
  document.title = `${TITLES[page]} · Clippy`;
  try { await pages[page](el); }
  catch (e) { el.innerHTML = `<div class="panel empty"><div class="ic">${icon("alert")}</div><h3>This page couldn't load</h3><p>${esc(e.message)}. Reload the page; if it keeps happening, ${state.status?.os === "windows" ? "close Clippy and open it again" : "check the terminal running Clippy"}.</p></div>`; }
  hydrateIcons(el);
}
window.addEventListener("hashchange", () => {
  if (leaveGuard && leaveGuard() && !confirm("You have unsaved changes. Leave without saving?")) { history.replaceState(null, "", lastHash); return; }
  lastHash = location.hash;
  closeModal(true);
  route(); window.scrollTo(0, 0);
});
window.addEventListener("beforeunload", (e) => { if (leaveGuard && leaveGuard()) { e.preventDefault(); e.returnValue = ""; } });

// ───────────────────────── live status (rail) ─────────────────────────
async function cancelJob(id) {
  try { await api.post(`/api/jobs/${id}/cancel`); toast("Cancelling — it stops at the next step", "info"); refreshGlobal(); } catch (e) { fail(e); }
}
async function refreshGlobal() {
  try {
    const [st, ov] = await Promise.all([api.get("/api/status"), api.get("/api/overview")]);
    state.status = st; state.overview = ov;
    const n = ov.review.pending;
    $("#navReview").textContent = n; $("#navReview").classList.toggle("hidden", !n);
    const run = st.running;
    $("#railStatus").innerHTML = `
      <div class="line" title="${esc(st.llm ? `${st.model} on ${st.ai}` : (st.ai_error || ""))}"><span class="dot ${st.llm ? "ok" : "bad"}"></span>Local AI ${st.llm ? "online" : "offline"}</div>
      ${st.vram_free != null ? `<div class="line"><span class="dot ok"></span>GPU: ${(st.vram_free / 1024).toFixed(1)}&nbsp;GB free</div>` : ""}
      ${run ? `<div class="onair"><div class="what"><span class="dot live"></span>${run.kind === "auto" ? "Autopilot on air" : run.kind === "fix" ? "Fixing a short" : "Making clips"}</div>
        <div class="bar"><i style="width:${(run.pct * 100).toFixed(1)}%"></i></div><div class="msg">${esc(run.msg || "")}</div>
        <button type="button" class="btn sm quiet" data-cancel="${run.id}">${icon("stop")} Cancel</button></div>`
        : st.queued ? `<div class="onair"><div class="msg">${st.queued} job${st.queued > 1 ? "s" : ""} waiting</div></div>` : ""}`;
    $$("[data-cancel]", $("#railStatus")).forEach((b) => b.onclick = () => cancelJob(b.dataset.cancel));
  } catch {}
}

// ───────────────────────── shared renderers ─────────────────────────
function clipCard(c) {
  const post = [c.caption, (c.hashtags || []).join(" ")].filter(Boolean).join("\n\n");
  return `<article class="clip">
    <video src="/media/${encodeURI(c.file)}" ${c.thumb ? `poster="/media/${encodeURI(c.thumb)}"` : ""} controls preload="none" playsinline width="232" height="412"></video>
    <div class="b">
      <div class="row small muted"><span class="score ${scoreCls(c.score)}" title="AI score">${c.score ?? "–"}</span><span class="num">${Math.round(c.duration || 0)}&nbsp;s</span>
        ${c.teaser ? `<span class="tag">${icon("zap")} Teaser</span>` : ""}</div>
      <h3>${esc(c.title)}</h3>
      ${post ? `<div class="cap">${esc(post)}</div>` : ""}
      <div class="acts"><a class="btn sm" href="/media/${encodeURI(c.file)}" download>${icon("download")} Download</a>
        <button type="button" class="btn sm" data-fix-file="${esc(c.file)}">${icon("pencil")} Quick Fix</button>
        ${post ? `<button type="button" class="btn sm" data-copy="${esc(post)}">${icon("copy")} Copy Caption</button>` : ""}</div>
    </div></article>`;
}
function bindCopy(root) {
  $$("[data-copy]", root).forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("Caption copied"); } catch { toast("Couldn't copy — select the text and copy it yourself", "bad"); }
  });
}
function stepper(steps, active, doneAll = false) {
  return `<div class="stepper">${steps.map((s, i) => {
    const cls = doneAll || i < active ? "done" : i === active ? "on" : "";
    return `${i ? `<div class="ln ${doneAll || i <= active ? "done" : ""}"></div>` : ""}<div class="st ${cls}" ${cls === "on" ? 'aria-current="step"' : ""}><span class="n">${cls === "done" ? icon("check") : i + 1}</span><span class="lbl">${esc(s)}</span></div>`;
  }).join("")}</div>`;
}
const emptyState = (ic, title, text, action = "") => `<div class="panel empty"><div class="ic">${icon(ic)}</div><h3>${esc(title)}</h3><p>${text}</p>${action}</div>`;

async function reviewAction(id, act, extra = {}, after = () => route()) {
  const res = await api.post("/api/review/" + id, {action: act, ...extra});
  const undo = {label: "Undo", run: async () => { try { await api.post("/api/review/" + id, {action: "restore"}); toast("Moved back to Waiting"); refreshGlobal(); after(); } catch (e) { fail(e); } }};
  if (act === "approve") toast("Approved — uploading in 10 seconds", "ok", undo, 9500);
  else if (act === "reject") toast("Rejected", "ok", undo, 9500);
  else if (act === "save") toast("Saved");
  else if (act === "restore") toast("Moved back to Waiting");
  refreshGlobal();
  return res;
}

// ═════════════════════════ HOME ═════════════════════════
async function setupBanner(box) {
  let s;
  try { s = await api.get("/api/setup"); } catch { return; }
  if (!box.isConnected || !s.missing.length) return;
  const names = s.missing.map((m) => m === "ai" ? "an AI model" : (s.components.find((c) => c.id === m)?.name || m).toLowerCase());
  box.innerHTML = `<section class="setup-banner"><div><b>Finish setting up Clippy</b><p>It still needs ${esc(names.join(" and "))}. Everything downloads into Clippy's own folder.</p></div><a class="btn primary" href="#ai">${icon("download")} Set Up</a></section>`;
  hydrateIcons(box);
}

pages.home = async (el) => {
  const h = new Date().getHours();
  const hello = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  el.innerHTML = `
    <div class="ph"><div><h1>${hello}</h1><p>What's waiting for you, and what Clippy is working on.</p></div></div>
    <div id="hSetup"></div>
    <nav class="mob-links" aria-label="More"><a class="btn sm" href="#library">${icon("grid")} Library</a><a class="btn sm" href="#ai">${icon("cpu")} AI &amp; Tools</a><a class="btn sm" href="#ext">${icon("puzzle")} Extensions</a><a class="btn sm" href="#settings">${icon("sliders")} Settings</a></nav>
    <form class="linkbar" id="hForm">
      <input class="input big" id="hUrl" name="url" type="text" inputmode="url" autocomplete="off" spellcheck="false" aria-label="YouTube link or video file" placeholder="https://www.youtube.com/watch?v=…">
      <button class="btn primary lg">${icon("scissors")} Make Clips</button></form>
    <div class="monitor">
      <section class="panel" aria-labelledby="upT"><div class="row between" style="margin-bottom:14px"><h2 id="upT" style="margin:0">Up next</h2><span id="upCount"></span></div><div id="upBody"></div></section>
      <div class="side-col"><section class="panel onair-panel" id="hAir" aria-live="polite"></section><div class="facts" id="hFacts" style="grid-template-columns:1fr"></div></div>
    </div>
    <div class="sec" id="hChannels"></div>
    <div class="grid g2 sec">
      <section class="panel"><h2>Recent activity</h2><p class="sub">Clip jobs and autopilot runs</p><div class="rows" id="hAct"></div></section>
      <section class="panel"><h2>Recently published</h2><p class="sub">Shorts that went out</p><div class="rows" id="hUp"></div></section>
    </div>`;
  let upSig = "";
  const loadUpNext = async () => {
    let items; try { items = await api.get("/api/review?status=pending"); } catch { return; }
    if (!$("#upBody")) return;
    const sig = items.map((i) => i.id).join();
    if (sig === upSig && $("#upBody").childElementCount) return;
    upSig = sig;
    $("#upCount").innerHTML = items.length ? `<span class="tag you">${items.length} waiting</span>` : "";
    if (!items.length) {
      $("#upBody").innerHTML = `<div class="empty" style="padding:26px 10px"><div class="ic">${icon("checkCircle")}</div><h3>Nothing waiting</h3>
        <p>Paste a link above, or let a channel on Autopilot find something.</p><a class="btn" href="#auto">${icon("bot")} Open Autopilot</a></div>`;
      return;
    }
    const i = items[0];
    $("#upBody").innerHTML = `<div class="upnext">
      <video src="/media/${encodeURI(i.file)}" ${i.thumb ? `poster="/media/${encodeURI(i.thumb)}"` : ""} controls preload="metadata" playsinline width="220" height="391"></video>
      <div class="meta"><h3 class="break">${esc(i.title)}</h3>
        <dl class="kv"><dt>Channel</dt><dd>${esc(i.profile_name)}</dd><dt>From</dt><dd><a href="${esc(i.source_url)}" target="_blank" rel="noopener">${esc(i.source_channel || "the source video")}</a></dd>
          <dt>Length</dt><dd class="num">${Math.round(i.duration || 0)}&nbsp;s</dd><dt>AI score</dt><dd class="num">${i.score ?? "–"}</dd></dl>
        <div class="row"><button type="button" class="btn primary" data-up="approve">${icon("check")} Approve &amp; Publish</button>
          <button type="button" class="btn quiet danger" data-up="reject">${icon("x")} Reject</button>
          ${items.length > 1 ? `<a class="btn quiet" href="#review">See All ${items.length}</a>` : ""}</div>
        <p class="small faint" style="margin:0">To change the title or description first, open it in <a href="#review">Review</a>.</p></div></div>`;
    $$("[data-up]", $("#upBody")).forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try { await reviewAction(i.id, b.dataset.up, {}, () => { upSig = ""; loadUpNext(); }); upSig = ""; loadUpNext(); } catch (e) { fail(e); b.disabled = false; }
    });
  };
  const load = async () => {
    await refreshGlobal();
    const o = state.overview, st = state.status; if (!o || !$("#hAir")) return;
    const run = st?.running;
    $("#hAir").innerHTML = run
      ? `<div class="what"><span class="dot live"></span>${run.kind === "auto" ? "Autopilot: " + esc(run.url) : "Making clips"}</div>
         <div class="bar" style="margin:12px 0 8px"><i style="width:${(run.pct * 100).toFixed(1)}%"></i></div>
         <div class="small muted">${esc(run.msg || "")}</div>
         <div class="row" style="margin-top:12px"><a class="btn sm" href="${run.kind === "auto" ? "#auto" : "#make"}">Open</a><button type="button" class="btn sm quiet" data-cancel="${run.id}">${icon("stop")} Cancel</button></div>`
      : `<div class="what"><span class="dot ${st?.llm ? "ok" : "bad"}"></span>Nothing on air</div><p class="small muted" style="margin:8px 0 0">${st?.llm ? "Ready for the next video." : "No AI server found. Start Ollama, LM Studio or llama.cpp, or check Settings."}</p>`;
    $$("[data-cancel]", $("#hAir")).forEach((b) => b.onclick = () => cancelJob(b.dataset.cancel));
    $("#hFacts").innerHTML = `
      <a class="fact ${o.review.pending ? "you" : ""}" href="#review"><div class="k">Waiting for you</div><div class="v">${o.review.pending}</div></a>
      <div class="fact"><div class="k">Published this week</div><div class="v">${o.published_week}</div></div>
      <div class="fact"><div class="k">Next automatic run</div><div class="v" style="font-size:24px">${o.next_run ? rel(o.next_run) : "None set"}</div></div>`;
    $("#hAct").innerHTML = o.jobs.length ? o.jobs.map((j) => {
      const [ic, cls, word] = {done: ["check", "ok", "Done"], error: ["alert", "err", "Failed"], running: ["refresh", "live", "Working"], cancelled: ["stop", "", "Cancelled"], interrupted: ["alert", "err", "Interrupted"]}[j.state] || ["clock", "", "Waiting"];
      const title = j.kind === "auto" ? `Autopilot: ${j.url}` : (j.title || j.url);
      const extra = j.state === "done" && j.clips != null ? `, ${j.clips} shorts` : j.state === "error" ? `: ${j.error || ""}` : "";
      return `<div class="rowi"><div class="ic ${cls}">${icon(ic)}</div><div class="t"><b class="break">${esc(title)}</b><small>${word}${esc(extra)}, ${rel(j.finished || j.created)}</small></div></div>`;
    }).join("") : `<p class="small muted">Nothing yet. Clip a video or run a channel.</p>`;
    $("#hUp").innerHTML = o.uploads.length ? o.uploads.map((u) => `<a class="rowi" href="${esc(u.youtube?.url || "#")}" target="_blank" rel="noopener">
        <div class="ic">${icon("youtube")}</div><div class="t"><b>${esc(u.title)}</b><small>${esc(u.profile_name)}, ${rel(u.uploaded)}</small></div>${icon("external", "faint")}</a>`).join("")
      : `<p class="small muted">Nothing published yet. Approve shorts in <a href="#review">Review</a> to publish them.</p>`;
  };
  const loadChannels = async () => {
    let ps; try { ps = await api.get("/api/auto/profiles"); } catch { return; }
    if (!$("#hChannels")) return;
    if (!ps.length) { $("#hChannels").innerHTML = ""; return; }
    $("#hChannels").innerHTML = `<div class="sec-head"><h2>Channels on Autopilot</h2><a class="btn sm quiet" href="#auto">Manage</a></div>
      <section class="panel" style="padding:6px 18px"><div class="rows">${ps.map((p) => `<div class="rowi">
        <div class="avatar" style="width:36px;height:36px;font-size:15px">${p.youtube_status?.channel?.thumb ? `<img src="${esc(p.youtube_status.channel.thumb)}" alt="" width="36" height="36">` : esc(initials(p.name))}</div>
        <div class="t"><b>${esc(p.name)}</b><small>${p.job ? "Running now" : p.auto_every_hours ? `${everyLabel(p.auto_every_hours)}${p.next_run ? `, next ${rel(p.next_run)}` : ""}` : "Runs when you press Run"}</small></div>
        ${p.pending ? `<a class="tag you" href="#review">${p.pending} waiting</a>` : ""}
        <button type="button" class="btn sm" data-run="${p.id}" ${p.job ? "disabled" : ""}>${icon("play")} Run Now</button></div>`).join("")}</div></section>`;
    $$("[data-run]", $("#hChannels")).forEach((b) => b.onclick = async () => { b.disabled = true; try { await api.post(`/api/auto/profiles/${b.dataset.run}/run`); toast("Started — this takes a few minutes"); load(); } catch (e) { fail(e); b.disabled = false; } });
  };
  setupBanner($("#hSetup"));
  $("#hForm").onsubmit = async (e) => {
    e.preventDefault();
    const url = $("#hUrl").value.trim(); if (!url) { $("#hUrl").focus(); return; }
    try { const r = await api.post("/api/jobs", {url, options: {...MAKE_DEFAULTS, ...store.get("make", {})}}); state.makeJob = r.id; $("#hUrl").value = ""; toast("Started — follow it under On air"); load(); }
    catch (err) { fail(err); }
  };
  await Promise.all([load(), loadUpNext(), loadChannels()]);
  repeat(4000, load); repeat(6000, loadUpNext); repeat(8000, loadChannels);
};

// ═════════════════════════ MAKE CLIPS ═════════════════════════
const MAKE_DEFAULTS = {clips: 5, min_seconds: 20, max_seconds: 60, caption_style: "beast", highlight_color: "#ffe135", title_seconds: 3.5,
  teaser: true, sfx: true, motion: true, emojis: true, progress_bar: true, remove_silences: true, split_screen: true, punch_in: true, reuse_picks: false,
  speech: "auto", format: "clips", top_theme: "funny", top_count: 3};
const SPEECH = [["auto", "Detect", "Clippy checks for talking itself"], ["on", "Has talking", "Podcasts, interviews, vlogs — picks by what's said"],
  ["off", "No talking", "Music, gameplay, sport, satisfying — picks by sound & action, skips transcription"]];
const EFFECTS = [
  ["title_seconds", "type", "Hook title", "Big title at the top for the first seconds"],
  ["teaser", "zap", "Teaser hook", "Opens with the best line, then whooshes into the clip"],
  ["sfx", "music", "Sound effects", "Whoosh, pop and impact sounds"],
  ["motion", "zoom", "Motion", "Intro slam, slow push-ins and zoom punches"],
  ["emojis", "smile", "Emojis", "Emojis the AI picks pop above the captions"],
  ["progress_bar", "progress", "Progress bar", "A thin bar at the top that fills up"],
  ["remove_silences", "mute", "Cut silences", "Removes dead air for faster pacing"],
  ["split_screen", "columns", "Split screen", "Stacks two people in podcast wide shots"],
  ["punch_in", "zoom", "Punch-in on cuts", "A subtle zoom change on every jump cut"],
];
const JOB_STEPS = ["Download", "Transcribe", "Find best moments", "Edit and render"];
const STAGE_IDX = {queued: 0, download: 0, transcribe: 1, pick: 2, render: 3, done: 4};

pages.make = async (el) => {
  const o = {...MAKE_DEFAULTS, ...store.get("make", {})};
  el.innerHTML = `
    <div class="ph"><div><h1>Make clips</h1><p>Paste a link or upload a video. Clippy finds the best moments, reframes them to 9:16 and adds captions, effects and sound.</p></div></div>
    <section class="panel stage dropzone" id="mDrop">
      <h2 id="mStageT">Drop a video here, or paste a link</h2><p class="sub">YouTube links and video files from your computer both work.</p>
      <form class="linkbar" id="mForm"><input class="input big" id="mUrl" name="url" type="text" inputmode="url" autocomplete="off" spellcheck="false" aria-label="YouTube link or video file" placeholder="https://www.youtube.com/watch?v=…">
        <button class="btn primary lg" id="mGo">${icon("sparkles")} Make Clips</button>
        <button type="button" class="btn lg" id="mUp">${icon("upload")} Upload Video</button>
        <input type="file" id="mFile" accept="video/*,.mkv,.mov,.avi,.m4v,.ts" hidden></form>
      <label class="focusbar"><span>Look for <small class="faint">(optional)</small></span><input class="input" id="mFocus" type="text" maxlength="200" autocomplete="off" placeholder="Like “practical advice about pricing”. Leave empty for the most watchable moments."></label>
      <p class="small faint" style="margin:12px 0 0">It takes a few minutes, and you can leave this page while it works.</p>
      <div class="drophint" aria-hidden="true">${icon("upload")}<b>Drop your video to make clips from it</b></div>
      <div id="mJob" style="margin-top:18px" class="hidden" aria-live="polite"></div>
    </section>
    <div class="sec"><div class="sec-head"><h2>What to make</h2><span>Separate shorts, or one countdown</span></div>
      <div class="choices wide" id="mFormat" role="radiogroup" aria-label="What to make">
        ${[["clips", "film", "Shorts", "Several separate shorts, each from its own best moment"], ["top", "trophy", "Top countdown", "One short that ranks the best moments: #3, #2 and then #1"]].map(([v, ic, t, d]) =>
          `<button type="button" role="radio" aria-checked="${o.format === v}" class="choice ${o.format === v ? "on" : ""}" data-v="${v}"><span class="tick">${icon("check")}</span><span class="ci">${icon(ic)}</span><b>${t}</b><small>${d}</small></button>`).join("")}</div>
      <section class="panel ${o.format === "top" ? "" : "hidden"}" id="mTop" style="margin-top:12px">
        <div class="field"><span id="mThemeLbl">Which moments</span><div class="chips" id="mThemes" role="radiogroup" aria-labelledby="mThemeLbl">${THEMES.map((t) =>
          `<button type="button" role="radio" aria-checked="${o.top_theme === t.id}" class="chip ${o.top_theme === t.id ? "on" : ""}" data-t="${esc(t.id)}">${esc(t.emoji || "")} ${esc(t.name)}</button>`).join("")}</div></div>
        <div class="field" style="margin-top:14px"><span id="mCountLbl">How many moments</span><div class="seg" id="mCount" role="radiogroup" aria-labelledby="mCountLbl">${[3, 4, 5].map((n) =>
          `<button type="button" role="radio" aria-checked="${o.top_count === n}" class="${o.top_count === n ? "on" : ""}" data-n="${n}">${n}</button>`).join("")}</div>
          <small class="hint" style="display:block;margin-top:8px">Each moment is 5–15 seconds, and the best one comes last. Extensions can add more kinds of countdown.</small></div>
      </section></div>
    <div class="sec"><div class="sec-head"><h2>Caption style</h2><span>How your captions look</span></div>
      <div class="presetbar"><label for="mPreset">Saved style</label><select class="input" id="mPreset">${presetOptions(o.preset, "None, just these choices")}</select>
        <button type="button" class="btn sm" id="mSavePreset">${icon("plus")} Save These as a Style</button>
        <span class="small faint" id="mPresetNote"></span></div>
      <div class="styles" id="mStyles" role="radiogroup" aria-label="Caption style">${STYLES.map(([k, n, d, pv]) => `<button type="button" role="radio" aria-checked="${o.caption_style === k}" class="style ${o.caption_style === k ? "on" : ""}" data-s="${esc(k)}">
        ${stylePic(pv, n)}<div><b>${esc(n)}</b><small>${esc(d)}</small></div></button>`).join("")}</div></div>
    <div class="sec grid g2">
      <section class="panel"><h2>Clips</h2><p class="sub">How many, and how long</p>
        <div id="mHowMany" class="${o.format === "top" ? "hidden" : ""}">
        <label class="field"><span>Number of clips: <b id="mNum" class="num" style="color:var(--ink)">${o.clips}</b></span><input type="range" id="mClips" min="1" max="12" value="${o.clips}"></label>
        <div class="grid g2" style="margin-top:14px">
          <label class="field"><span>Shortest (seconds)</span><input class="input num" type="number" inputmode="numeric" id="mMin" min="5" max="170" value="${o.min_seconds}"></label>
          <label class="field"><span>Longest (seconds)</span><input class="input num" type="number" inputmode="numeric" id="mMax" min="10" max="180" value="${o.max_seconds}"></label>
        </div></div>
        <div class="field" style="margin-top:16px"><span id="speechLbl">Talking in the video</span>
          <div class="seg" id="mSpeech" role="radiogroup" aria-labelledby="speechLbl">${SPEECH.map(([v, l, d]) => `<button type="button" role="radio" aria-checked="${o.speech === v}" data-v="${v}" title="${esc(d)}" class="${o.speech === v ? "on" : ""}">${l}</button>`).join("")}</div>
          <small class="hint" id="mSpeechHint" style="display:block;margin-top:8px">${esc((SPEECH.find((x) => x[0] === o.speech) || SPEECH[0])[2])}</small></div>
        <div class="field" style="margin-top:16px"><span id="colorLbl">Highlight color</span>
          <div class="swatches" id="mColors" role="radiogroup" aria-labelledby="colorLbl">${COLORS.map((c) => `<button type="button" role="radio" aria-checked="${o.highlight_color === c}" class="swatch ${o.highlight_color === c ? "on" : ""}" style="background:${c}" data-c="${c}" aria-label="${c}"></button>`).join("")}
          <label class="swatch custom ${COLORS.includes(o.highlight_color) ? "" : "on"}" id="mCustomL" title="Pick any color" style="--pick:${o.highlight_color}"><input type="color" id="mCustom" value="${o.highlight_color}" aria-label="Pick any color" style="position:absolute;opacity:0;width:0;height:0"></label></div></div>
        <label class="switch" style="margin-top:16px"><span class="ic">${icon("refresh")}</span><span class="txt"><b>Reuse previous AI picks</b><small>Same video, new look — skips the AI step</small></span><input type="checkbox" id="mReuse" ${o.reuse_picks ? "checked" : ""}></label>
      </section>
      <section class="panel"><h2>Effects</h2><p class="sub">What makes a short hard to swipe past</p>
        <div class="stack" id="mFx">${EFFECTS.map(([k, ic, t, d]) => `<label class="switch"><span class="ic">${icon(ic)}</span><span class="txt"><b>${t}</b><small>${d}</small></span>
          <input type="checkbox" data-fx="${k}" ${(k === "title_seconds" ? o.title_seconds !== 0 : o[k]) ? "checked" : ""}></label>`).join("")}</div>
      </section>
    </div>
    <div class="sec hidden" id="mResWrap"><div class="sec-head"><h2 id="mResTitle">Your clips</h2><span id="mResSub" class="break"></span><button type="button" class="btn sm" id="mQuote">${icon("search")} Find a Quote</button></div><div class="clips" id="mRes"></div></div>`;

  const LOOK = ["caption_style", "highlight_color", "title_seconds", "teaser", "sfx", "motion", "emojis", "progress_bar", "remove_silences", "split_screen", "punch_in"];
  const changedFromPreset = () => {
    const pr = PRESETS.find((x) => x.id === o.preset);
    return pr && LOOK.some((k) => k in pr.settings && String(pr.settings[k]).toLowerCase() !== String(o[k]).toLowerCase());
  };
  const focusText = () => ($("#mFocus")?.value || "").replace(/\s+/g, " ").trim();   // this job only, not remembered
  const save = () => {
    store.set("make", o);
    if ($("#mPresetNote")) $("#mPresetNote").textContent = changedFromPreset() ? "Changed from the saved style. Save to keep the changes." : "";
  };
  if (o.preset && !PRESETS.some((x) => x.id === o.preset)) o.preset = "";      // deleted since
  $("#mPreset").onchange = async (e) => {
    o.preset = e.target.value;
    const pr = PRESETS.find((x) => x.id === o.preset);
    if (pr) for (const k of LOOK) if (k in pr.settings) o[k] = pr.settings[k];
    store.set("make", o);
    const y = scrollY; await route(); scrollTo(0, y);                          // every control shows the style
    if (pr) toast(`Using the style “${pr.name}”`);
  };
  $("#mSavePreset").onclick = async () => {
    const pr = await savePresetDialog(Object.fromEntries(LOOK.map((k) => [k, o[k]])), PRESETS.find((x) => x.id === o.preset)?.name || "");
    if (pr) { o.preset = pr.id; store.set("make", o); const y = scrollY; await route(); scrollTo(0, y); }
  };
  save();
  if (!THEMES.some((t) => t.id === o.top_theme)) o.top_theme = "funny";        // its extension was removed
  $$("#mFormat .choice").forEach((b) => b.onclick = () => {
    o.format = b.dataset.v;
    $$("#mFormat .choice").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    $("#mTop").classList.toggle("hidden", o.format !== "top"); $("#mHowMany").classList.toggle("hidden", o.format === "top"); save();
  });
  $$("#mThemes .chip").forEach((b) => b.onclick = () => { o.top_theme = b.dataset.t; $$("#mThemes .chip").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); }); save(); });
  $$("#mCount button").forEach((b) => b.onclick = () => { o.top_count = +b.dataset.n; $$("#mCount button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); }); save(); });
  $$("#mStyles .style").forEach((b) => b.onclick = () => { o.caption_style = b.dataset.s; $$("#mStyles .style").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); }); save(); });
  $("#mClips").oninput = (e) => { o.clips = +e.target.value; $("#mNum").textContent = o.clips; save(); };
  $("#mMin").onchange = (e) => { o.min_seconds = +e.target.value; save(); };
  $("#mMax").onchange = (e) => { o.max_seconds = +e.target.value; save(); };
  const setColor = (c, custom) => {
    o.highlight_color = c;
    $$("#mColors .swatch").forEach((s) => { const on = custom ? s.id === "mCustomL" : s.dataset.c === c; s.classList.toggle("on", on); if (s.dataset.c) s.setAttribute("aria-checked", on); });
    $("#mCustomL").style.setProperty("--pick", c); save();
  };
  $$("#mColors [data-c]").forEach((b) => b.onclick = () => setColor(b.dataset.c, false));
  $("#mCustom").oninput = (e) => setColor(e.target.value, true);
  $("#mReuse").onchange = (e) => { o.reuse_picks = e.target.checked; save(); };
  $$("#mSpeech button").forEach((b) => b.onclick = () => {
    o.speech = b.dataset.v;
    $$("#mSpeech button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    $("#mSpeechHint").textContent = (SPEECH.find((x) => x[0] === o.speech) || SPEECH[0])[2]; save();
  });
  $$("[data-fx]").forEach((cb) => cb.onchange = () => { const k = cb.dataset.fx; o[k] = k === "title_seconds" ? (cb.checked ? 3.5 : 0) : cb.checked; save(); });

  const showResult = (res) => {
    state.lastResult = res;
    $("#mResWrap").classList.remove("hidden");
    $("#mResTitle").textContent = res.clips.length === 1 && res.clips[0].format === "top" ? "Your countdown is ready" : `${res.clips.length} clips ready`;
    $("#mResSub").textContent = res.title;
    $("#mQuote").classList.toggle("hidden", res.mode === "visual");
    $("#mQuote").onclick = () => openQuote(res.id, {after: () => {}});
    $("#mRes").innerHTML = res.clips.map(clipCard).join("");
    bindCopy($("#mRes"));
    bindFix($("#mRes"), (r, old) => {                 // swap in the fixed short
      const c = r && res.clips.find((x) => x.file.replace(/\\/g, "/") === old.replace(/\\/g, "/"));
      if (c) Object.assign(c, {file: r.file, thumb: r.thumb, duration: r.duration, title: r.title});
      if ($("#mRes")) showResult(res);
    });
  };
  if (state.lastResult) showResult(state.lastResult);

  const watch = (id) => {
    state.makeJob = id;
    const box = $("#mJob"); box.classList.remove("hidden");
    $("#mGo").disabled = true;
    const tick = async () => {
      let j; try { j = await api.get("/api/jobs/" + id); } catch { return; }
      if (!$("#mJob")) return;
      const live = j.state === "queued" || j.state === "running";
      const idx = j.state === "done" ? 4 : STAGE_IDX[j.stage] ?? 0;
      box.innerHTML = `${stepper(JOB_STEPS, idx, j.state === "done")}
        ${live ? `<div class="bar ${j.state === "queued" ? "wait" : ""}"><i style="width:${(j.pct * 100).toFixed(1)}%"></i></div>
        <div class="row between small" style="margin-top:8px"><span class="muted row" style="gap:8px">${j.state === "running" ? '<span class="dot live"></span>' : ""}${esc(j.state === "queued" ? "Waiting for the job before it to finish…" : j.msg)}</span>
          <span class="row"><span class="muted num">${Math.round(j.pct * 100)}%</span><button type="button" class="btn sm quiet" id="mCancel">${icon("stop")} Cancel</button></span></div>` : ""}
        ${j.state === "error" ? `<div class="note err"><div class="ic">${icon("alert")}</div><div><b>That didn't work</b><p>${esc(j.error)}</p></div></div>` : ""}
        ${j.state === "cancelled" ? `<div class="note"><div class="ic">${icon("stop")}</div><div><b>Cancelled</b><p>Nothing was saved. Paste the link again to start over.</p></div></div>` : ""}
        ${j.state === "interrupted" ? `<div class="note err"><div class="ic">${icon("alert")}</div><div><b>Interrupted</b><p>Clippy was closed while this ran. Paste the link again to restart it.</p></div></div>` : ""}`;
      $("#mCancel", box)?.addEventListener("click", () => cancelJob(id));
      if (!live) {
        clearInterval(t); $("#mGo").disabled = false; state.makeJob = null;
        if (j.state === "done") { showResult(j.result); toast(j.result.clips[0]?.format === "top" ? "Countdown ready" : `${j.result.clips.length} clips ready`); refreshGlobal(); }
      }
    };
    const t = setInterval(tick, 1000); timers.push(t); tick();
  };
  // ── upload a video from this computer: streamed into Clippy's folder, then made like a link
  let xhr = null;
  const upload = (file) => {
    if (!file || xhr) return;
    if (!/^video\//.test(file.type) && !/\.(mp4|mov|mkv|webm|avi|m4v|mpe?g|wmv|flv|ts|3gp)$/i.test(file.name)) { toast("That isn't a video file", "bad"); return; }
    const box = $("#mJob"); box.classList.remove("hidden");
    $("#mGo").disabled = $("#mUp").disabled = true;
    const done = () => { xhr = null; if ($("#mGo")) $("#mGo").disabled = $("#mUp").disabled = false; };
    const show = (pct, sent) => {
      if (!$("#mJob")) return;
      box.innerHTML = `<div class="bar"><i style="width:${(pct * 100).toFixed(1)}%"></i></div>
        <div class="row between small" style="margin-top:8px"><span class="muted row break" style="gap:8px"><span class="dot live"></span>Uploading ${esc(file.name)}… ${fmtBytes(sent)} of ${fmtBytes(file.size)}</span>
          <span class="row"><span class="muted num">${Math.round(pct * 100)}%</span><button type="button" class="btn sm quiet" id="mUpCancel">${icon("stop")} Cancel</button></span></div>`;
      $("#mUpCancel").onclick = () => xhr && xhr.abort();
    };
    show(0, 0);
    xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) show(e.loaded / e.total, e.loaded); };
    xhr.onabort = () => { done(); box.classList.add("hidden"); toast("Upload cancelled", "info"); };
    xhr.onerror = () => { done(); box.classList.add("hidden"); fail(new Error("The upload didn't get through. Is Clippy still running?")); };
    xhr.onload = async () => {
      const status = xhr.status;
      let r = {}; try { r = JSON.parse(xhr.responseText); } catch {}
      done();
      if (status !== 200) { box.classList.add("hidden"); fail(new Error(r.detail || "The upload failed")); return; }
      $("#mUrl").value = "";
      try { const j = await api.post("/api/jobs", {url: r.path, options: {...o, focus: focusText()}}); watch(j.id); toast(`Uploaded “${r.title}”: making clips`); } catch (err) { fail(err); }
    };
    xhr.send(file);
  };
  $("#mUp").onclick = () => $("#mFile").click();
  $("#mFile").onchange = (e) => { upload(e.target.files[0]); e.target.value = ""; };
  const drop = $("#mDrop");
  let depth = 0;
  const hasFile = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  drop.addEventListener("dragenter", (e) => { if (!hasFile(e)) return; e.preventDefault(); depth++; drop.classList.add("over"); });
  drop.addEventListener("dragover", (e) => { if (hasFile(e)) e.preventDefault(); });
  drop.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; drop.classList.remove("over"); } });
  drop.addEventListener("drop", (e) => { if (!hasFile(e)) return; e.preventDefault(); depth = 0; drop.classList.remove("over"); upload(e.dataTransfer.files[0]); });

  $("#mForm").onsubmit = async (e) => {
    e.preventDefault();
    const url = $("#mUrl").value.trim();
    if (!url) { $("#mUrl").focus(); return; }
    $("#mGo").disabled = true;
    try { const r = await api.post("/api/jobs", {url, options: {...o, focus: focusText()}}); watch(r.id); } catch (err) { $("#mGo").disabled = false; fail(err); }
  };
  const pre = store.get("prefill", null);
  if (pre) { store.set("prefill", null); $("#mUrl").value = pre; $("#mForm").requestSubmit(); return; }
  if (state.makeJob) { watch(state.makeJob); return; }
  try { const jobs = await api.get("/api/jobs"); const a = jobs.find((j) => (j.state === "running" || j.state === "queued") && j.kind === "clip"); if (a) watch(a.id); } catch {}
};

// ═════════════════════════ FIND VIDEOS ═════════════════════════
pages.find = async (el) => {
  if (!state.niches) state.niches = await api.get("/api/finder/niches");
  const f = {niches: ["podcasts", "interviews", "challenges"], keywords: "", window: "week", duration: "long", lang: "en", cc_only: false, ...store.get("find", {})};
  const wl = await api.get("/api/finder/watchlist").catch(() => []);
  const seg = (id, val, opts) => `<div class="seg" id="${id}" role="radiogroup">${opts.map(([v, l]) => `<button type="button" role="radio" aria-checked="${val === v}" data-v="${v}" class="${val === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  el.innerHTML = `
    <div class="ph"><div><h1>Find videos worth clipping</h1><p>Scans YouTube now and ranks videos by how fast they're growing, how far they beat their channel's size, engagement and length. No API key, nothing to pay.</p></div></div>
    <section class="panel">
      <div class="field"><span id="gLbl">Genres</span>
        <div class="chips" id="fNiches" role="group" aria-labelledby="gLbl">${state.niches.map((n) => `<button type="button" class="chip ${f.niches.includes(n) ? "on" : ""}" aria-pressed="${f.niches.includes(n)}" data-n="${esc(n)}">${nicheIcon(n)}${esc(nicheLabel(n))}</button>`).join("")}</div></div>
      <div class="grid" style="margin-top:18px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
        <label class="field"><span>Extra keywords</span><input class="input" id="fKw" name="keywords" autocomplete="off" value="${esc(f.keywords)}" placeholder="joe rogan, kai cenat…"></label>
        <div class="field"><span>Uploaded</span>${seg("fWin", f.window, [["today", "Today"], ["week", "Week"], ["month", "Month"], ["year", "Year"]])}</div>
        <div class="field"><span>Length</span>${seg("fDur", f.duration, [["any", "Any"], ["medium", "4–20 min"], ["long", "20+ min"]])}</div>
        <label class="field"><span>Language</span><select class="input" id="fLang">${LANGS.map(([v, l]) => `<option value="${v}" ${f.lang === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      </div>
      <div class="grid g2" style="margin-top:14px">
        <label class="switch"><span class="ic">${icon("shield")}</span><span class="txt"><b>Creative Commons only</b><small>Only videos whose creator allows reuse</small></span><input type="checkbox" id="fCc" ${f.cc_only ? "checked" : ""}></label>
        <details class="more"><summary>${icon("chevR")} Watchlist: channels to always check (${wl.length})</summary><div>
          <textarea class="input" id="fWatch" rows="3" aria-label="Watchlist channels, one per line" placeholder="@MrBeast…">${esc(wl.map((x) => x.replace("https://www.youtube.com/", "")).join("\n"))}</textarea>
          <div class="row" style="margin-top:8px"><button type="button" class="btn sm" id="fSaveWatch">Save Watchlist</button><label class="row small muted" style="gap:6px"><input type="checkbox" id="fUseWatch" checked style="accent-color:var(--yellow)"> Include in scan</label></div></div></details>
      </div>
      <div class="row" style="margin-top:18px"><button type="button" class="btn primary lg" id="fScan">${icon("search")} Scan YouTube</button><span class="small faint" id="fWhen"></span></div>
      <div id="fJob" class="hidden" style="margin-top:14px" aria-live="polite"><div class="bar"><i id="fBar"></i></div><div class="row between small" style="margin-top:8px"><span class="muted" id="fMsg">Starting…</span><span class="muted num" id="fPct"></span></div></div>
    </section>
    <div id="fOut"></div>`;
  const save = () => store.set("find", f);
  $$("#fNiches .chip").forEach((c) => c.onclick = () => { c.classList.toggle("on"); c.setAttribute("aria-pressed", c.classList.contains("on")); f.niches = $$("#fNiches .chip.on").map((x) => x.dataset.n); save(); });
  for (const [id, key] of [["fWin", "window"], ["fDur", "duration"]]) $$(`#${id} button`).forEach((b) => b.onclick = () => { $$(`#${id} button`).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); }); f[key] = b.dataset.v; save(); });
  $("#fKw").onchange = (e) => { f.keywords = e.target.value; save(); };
  $("#fLang").onchange = (e) => { f.lang = e.target.value; save(); };
  $("#fCc").onchange = (e) => { f.cc_only = e.target.checked; save(); };
  $("#fSaveWatch").onclick = async () => {
    try { const r = await api.post("/api/finder/watchlist", {channels: $("#fWatch").value.split(/\n|,/).map((x) => x.trim()).filter(Boolean)}); toast(`Watchlist saved (${r.length} channels)`); } catch (e) { fail(e); }
  };
  let sortKey = "score", sortDir = -1;
  const NUMCOLS = ["rank", "score", "views", "vpd", "breakout", "engagement", "duration", "days"];
  const COLS = [["rank", "#"], [null, "Video"], ["score", "Score"], ["views", "Views"], ["vpd", "Views/day"], ["breakout", "Breakout"], ["engagement", "Engage"], ["duration", "Length"], ["days", "Age"], [null, ""]];
  const table = () => {
    const vids = [...(state.finder?.videos || [])].sort((a, b) => ((a[sortKey] ?? -1) - (b[sortKey] ?? -1)) * sortDir);
    $$("#fOut th[data-k]").forEach((th) => { const on = th.dataset.k === sortKey; th.classList.toggle("sorted", on); if (on) th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending"); else th.removeAttribute("aria-sort"); });
    $("#fBody").innerHTML = vids.map((v) => `<tr>
      <td class="num faint">${v.rank}</td>
      <td><div class="vid"><img src="https://i.ytimg.com/vi/${esc(v.id)}/mqdefault.jpg" alt="" width="112" height="63" loading="lazy"><div>
        <a class="tt" href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener">${esc(v.title)}</a>
        <div class="cc">${esc(v.channel || "")}${v.subs ? `, ${fmt(v.subs)} subscribers` : ""}${v.clipped ? ' <span class="tag ok" style="margin-left:4px">Clipped</span>' : ""}</div>
        <div class="whys">${(v.why || []).slice(0, 3).map((w) => `<span>${esc(w)}</span>`).join("")}</div></div></div></td>
      <td class="num"><div class="meter" title="Clip score ${v.score} of 100"><div class="track"><div class="fill" style="width:${v.score}%"></div></div><b>${v.score}</b></div></td>
      <td class="num">${fmt(v.views)}</td><td class="num">${fmt(v.vpd)}</td><td class="num">${v.breakout != null ? v.breakout.toFixed(1) + "×" : "–"}</td>
      <td class="num">${(v.engagement * 100).toFixed(1)}%</td><td class="num">${fmtDur(v.duration)}</td><td class="num">${fmtAge(v.days)}</td>
      <td><button type="button" class="btn primary sm" data-clip="${esc(v.id)}">${icon("scissors")} Clip It</button></td></tr>`).join("");
    $$("#fBody [data-clip]").forEach((b) => b.onclick = () => { store.set("prefill", "https://www.youtube.com/watch?v=" + b.dataset.clip); location.hash = "make"; });
  };
  const render = (data) => {
    state.finder = data;
    const st = data.stats || {}, vids = data.videos || [];
    $("#fWhen").textContent = data.created ? "Last scan " + rel(data.created) : "";
    if (!vids.length) { $("#fOut").innerHTML = ""; return; }
    const best = vids[0];
    $("#fOut").innerHTML = `
      <div class="facts sec">
        <div class="fact"><div class="k">Videos ranked</div><div class="v">${st.scanned ?? vids.length}</div></div>
        <div class="fact"><div class="k">Median views per day</div><div class="v">${fmt(st.median_vpd)}</div><div class="s">Fastest: ${fmt(st.top_vpd)}</div></div>
        <div class="fact"><div class="k">Breakouts</div><div class="v">${st.breakouts ?? 0}</div><div class="s">3× or more their channel size</div></div>
        <div class="fact"><div class="k">Reuse allowed</div><div class="v">${st.cc_count ?? 0}</div><div class="s">Creative Commons</div></div>
        <div class="fact you"><div class="k">Top score</div><div class="v">${best.score}</div><div class="s break">${esc(best.channel || "")}</div></div>
      </div>
      <div class="grid g2 sec">
        <section class="panel"><h2>Average score by genre</h2><p class="sub">Which genre is hottest right now</p>${(st.niches || []).map((n) => `<div class="hbar" title="${esc(nicheLabel(n.niche))}: average ${n.avg} over ${n.count} videos (best ${n.best})"><span>${esc(nicheLabel(n.niche))}</span><div class="track"><div class="fill" style="width:${n.avg}%"></div></div><span class="val num">${n.avg}</span></div>`).join("")}</section>
        <section class="panel"><h2>Top channels</h2><p class="sub">Best performers in this scan</p><div class="rows">${(st.channels || []).slice(0, 7).map((c) => `<div class="rowi" style="padding:9px 2px"><div class="t"><b><a href="${esc(c.url || "#")}" target="_blank" rel="noopener" style="text-decoration:none">${esc(c.channel)}</a></b><small>${c.videos} video${c.videos > 1 ? "s" : ""}, ${fmt(c.views)} views</small></div><span class="score ${scoreCls(c.best)}">${c.best}</span></div>`).join("")}</div></section>
      </div>
      <div class="sec"><div class="sec-head"><h2>Leaderboard</h2><span>Sort by any column. Clip It sends the video to Make Clips.</span></div>
        <div class="panel tablewrap"><table class="lb"><thead><tr>${COLS.map(([k, l]) => `<th scope="col" class="${NUMCOLS.includes(k) ? "num" : ""}" ${k ? `data-k="${k}"` : ""}>${k ? `<button type="button">${l}</button>` : l}</th>`).join("")}</tr></thead><tbody id="fBody"></tbody></table></div></div>`;
    $$("#fOut th[data-k] button").forEach((b) => b.onclick = () => { const k = b.parentElement.dataset.k; if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = ["rank", "days", "duration"].includes(k) ? 1 : -1; } table(); });
    table();
  };
  $("#fScan").onclick = async () => {
    const body = {niches: f.niches, keywords: f.keywords, window: f.window, duration: f.duration, cc_only: f.cc_only, lang: f.lang, use_watchlist: $("#fUseWatch").checked};
    $("#fScan").disabled = true; $("#fJob").classList.remove("hidden");
    try {
      const {id} = await api.post("/api/finder/scan", body);
      const t = setInterval(async () => {
        let s; try { s = await api.get("/api/finder/scan/" + id); } catch { return; }
        if (!$("#fBar")) { clearInterval(t); return; }
        $("#fBar").style.width = (s.pct * 100).toFixed(1) + "%"; $("#fPct").textContent = Math.round(s.pct * 100) + "%"; $("#fMsg").textContent = s.msg;
        if (s.state !== "running") {
          clearInterval(t); $("#fScan").disabled = false; $("#fJob").classList.add("hidden");
          if (s.state === "done") { render(s.result); toast(`Ranked ${s.result.videos.length} videos`); } else fail(new Error(s.error));
        }
      }, 800);
      timers.push(t);
    } catch (e) { $("#fScan").disabled = false; $("#fJob").classList.add("hidden"); fail(e); }
  };
  const last = state.finder || await api.get("/api/finder/latest").catch(() => null);
  if (last && last.videos) render(last);
};

// ═════════════════════════ AUTOPILOT ═════════════════════════
const PROFILE_DEFAULTS = {name: "", language: "en", niches: [], keywords: "", window: "week", duration: "long", sources: [], source_mode: "safe",
  caption_style: "beast", highlight_color: "#ffe135", preset: "", videos_per_run: 1, clips_per_video: 3, min_seconds: 20, max_seconds: 60,
  auto_every_hours: 24, youtube: true, tiktok: false, privacy: "public", spacing_hours: 4, category_id: "24",
  description_template: "{caption}\n\n{hashtags} #Shorts\n\n🎥 Credit: {source_channel} — {source_url}", extra_hashtags: ""};
const LENGTHS = [["short", "Short", "15–30 seconds", 15, 30], ["medium", "Medium", "20–60 seconds", 20, 60], ["long", "Long", "45–90 seconds", 45, 90]];
const SCHEDULES = [[0, "Manual", "Only when you press Run"], [12, "Twice a day", "Every 12 hours"], [24, "Every day", "Once a day"], [48, "Every 2 days", "Every other day"], [168, "Every week", "Once a week"]];
const SPACING = [[0, "Right away", "As soon as you approve"], [4, "Spread out", "One short every 4 hours"], [24, "One per day", "Steady daily posting"]];

pages.auto = async (el) => {
  const qs = new URLSearchParams(location.search);
  let banner = "";
  if (qs.get("yt")) {
    const ok = qs.get("yt") === "connected";
    banner = `<div class="note ${ok ? "ok" : "err"}" style="margin-bottom:16px"><div class="ic">${icon(ok ? "check" : "alert")}</div><div><b>${ok ? "YouTube connected" : qs.get("yt") === "cancelled" ? "YouTube sign-in was cancelled" : "YouTube sign-in failed"}</b><p>${ok ? "Approved shorts for this channel now upload automatically." : esc(qs.get("msg") || "Press Connect YouTube to try again.")}</p></div></div>`;
    history.replaceState(null, "", "/#auto");
  }
  if (!state.niches) state.niches = await api.get("/api/finder/niches");
  el.innerHTML = `
    <div class="ph"><div><h1>Autopilot</h1><p>Put a channel on autopilot: Clippy finds great videos, makes shorts and lines them up. You approve, and it posts.</p></div>
      <button type="button" class="btn primary lg" id="aNew">${icon("plus")} New Channel</button></div>
    ${banner}<div id="aList"></div><div id="aSetup" class="sec"></div>`;
  $("#aNew").onclick = () => openWizard(null);
  const how = `<div class="steps5">
      <div class="s"><div class="ic">${icon("search")}</div><b>Find</b><small>Scans YouTube in your genres and source channels</small></div>
      <div class="s"><div class="ic">${icon("trophy")}</div><b>Pick the best</b><small>Ranks by views per day, breakout and engagement</small></div>
      <div class="s"><div class="ic">${icon("film")}</div><b>Make shorts</b><small>Captions, effects and sound, fully edited</small></div>
      <div class="s"><div class="ic">${icon("checkCircle")}</div><b>You approve</b><small>Watch, fix the title, approve or reject</small></div>
      <div class="s"><div class="ic">${icon("youtube")}</div><b>Publish</b><small>Uploads to YouTube and saves files for TikTok</small></div></div>`;
  let sig = "";
  const load = async () => {
    let ps, client;
    try { [ps, client] = await Promise.all([api.get("/api/auto/profiles"), api.get("/api/youtube/client")]); } catch { return; }
    if (!$("#aList")) return;
    const s = JSON.stringify(ps) + client.has_client;
    if (s !== sig) {
      sig = s;
      if (!ps.length) {
        $("#aList").innerHTML = `<section class="panel"><div class="empty" style="padding:22px 10px 8px"><div class="ic">${icon("bot")}</div><h3>Put your first channel on autopilot</h3>
          <p>Tell Clippy what your channel is about. Every day it finds a great video, makes shorts and waits for your OK.</p></div>${how}
          <div class="row" style="justify-content:center;margin-top:22px"><button type="button" class="btn primary lg" id="aFirst">${icon("plus")} Create Your First Channel</button></div></section>`;
        $("#aFirst").onclick = () => openWizard(null);
      } else {
        $("#aList").innerHTML = `<div class="stack" style="gap:16px">${ps.map(profileCard).join("")}</div>
          <details class="more sec"><summary>${icon("chevR")} How Autopilot works</summary><div>${how}</div></details>`;
        bindProfiles(ps);
      }
    }
    renderSetup(ps, client);
  };
  await load(); repeat(3000, load);
};

function profileCard(p) {
  const yt = p.youtube_status || {}, job = p.job;
  const phase = !job ? -1 : job.state === "queued" ? 0 : job.pct < 0.2 ? (job.pct < 0.15 ? 0 : 1) : 2;
  const done = (i) => p.last_run > 0 && (phase === -1 || i < phase);
  const ytNeeds = p.youtube && !yt.connected;
  const node = (ic, title, sub, cls) => `<div class="pn ${cls}"><div class="c">${icon(ic)}</div><b>${title}</b><small>${sub}</small></div>`;
  const pubSub = p.published ? `${p.published} published` : ytNeeds ? "Needs YouTube" : p.youtube ? "Ready" : p.tiktok ? "TikTok files" : "Off";
  const pipe = `<div class="pipe">
    ${node("search", "Find", phase === 0 ? (job.state === "queued" ? "Waiting…" : "Scanning…") : p.last_run ? rel(p.last_run) : "Not run yet", phase === 0 ? "live" : done(0) ? "done" : "")}
    ${node("trophy", "Pick best", phase === 1 ? "Ranking…" : `${p.used_count} used`, phase === 1 ? "live" : done(1) ? "done" : "")}
    ${node("film", "Make shorts", phase === 2 ? Math.round(job.pct * 100) + "%" : `${p.videos_per_run}×${p.clips_per_video} per run`, phase === 2 ? "live" : done(2) ? "done" : "")}
    ${node("checkCircle", "You review", p.pending ? `${p.pending} waiting` : "All clear", p.pending ? "you" : p.last_run ? "done" : "")}
    ${node(p.youtube ? "youtube" : "phone", "Publish", pubSub, ytNeeds ? "you" : p.published ? "done" : "")}</div>`;
  const status = job ? `<span class="tag live"><span class="dot live" style="box-shadow:none"></span>${job.state === "queued" ? "Queued" : "Running"}</span>`
    : p.auto_every_hours ? `<span class="tag ok">${icon("clock")} ${everyLabel(p.auto_every_hours)}</span>` : `<span class="tag">${icon("play")} Manual</span>`;
  let mid = "";
  if (job) mid = `<div class="bar ${job.state === "queued" ? "wait" : ""}"><i style="width:${(job.pct * 100).toFixed(1)}%"></i></div><div class="row between small" style="margin-top:8px"><span class="muted">${esc(job.state === "queued" ? "Waiting for the GPU — another job is running…" : job.msg)}</span><button type="button" class="btn sm quiet" data-cancel="${job.id}">${icon("stop")} Cancel</button></div>`;
  else if (p.last_error) mid = `<div class="note err"><div class="ic">${icon("alert")}</div><div><b>The last run didn't finish</b><p>${esc(p.last_error)}</p></div></div>`;
  else if (ytNeeds) mid = `<div class="note you"><div class="ic">${icon("youtube")}</div><div style="flex:1"><b>Connect YouTube to publish automatically</b><p>Until then, approved shorts can't upload. The steps are under “Connect YouTube” below.</p></div></div>`;
  else if (p.pending) mid = `<div class="note you"><div class="ic">${icon("checkCircle")}</div><div style="flex:1"><b>${p.pending} new short${p.pending > 1 ? "s" : ""} waiting for you</b><p>Watch them and approve the good ones.</p></div><a class="btn sm primary" href="#review">Review Now</a></div>`;
  const av = yt.channel?.thumb ? `<img src="${esc(yt.channel.thumb)}" alt="" width="44" height="44">` : esc(initials(p.name));
  const genres = (p.niches || []).map(nicheLabel).join(", ") || "Source channels only";
  return `<article class="panel profile" aria-label="${esc(p.name)}">
    <div class="top"><div class="avatar">${av}</div>
      <div class="name"><b>${esc(p.name)}</b><small>${esc(genres)}${p.sources.length ? `; ${p.sources.length} source channel${p.sources.length > 1 ? "s" : ""}` : ""}</small></div>
      ${status}</div>
    ${pipe}${mid ? `<div class="mid">${mid}</div>` : ""}
    <div class="foot">
      <div class="info"><span>${icon(p.source_mode === "safe" ? "shield" : "alert")} ${p.source_mode === "safe" ? "Safe sources" : "Any video"}</span>
        <span>${icon("youtube")} ${p.youtube ? (yt.connected ? esc(yt.channel?.title || "Connected") : "Not connected") : "YouTube off"}</span>
        ${p.tiktok ? `<span>${icon("phone")} TikTok files</span>` : ""}${p.next_run ? `<span>${icon("calendar")} Next run ${rel(p.next_run)}</span>` : ""}</div>
      <button type="button" class="btn primary" data-run="${p.id}" ${job ? "disabled" : ""}>${icon("play")} Run Now</button>
      ${ytNeeds ? `<a class="btn" href="/api/youtube/connect/${p.id}" data-connect>${icon("youtube")} Connect YouTube</a>` : ""}
      <button type="button" class="btn" data-edit="${p.id}">${icon("pencil")} Edit</button>
      ${p.youtube && yt.connected ? `<button type="button" class="btn quiet icon" data-disc="${p.id}" aria-label="Disconnect YouTube from ${esc(p.name)}" title="Disconnect YouTube">${icon("link")}</button>` : ""}
      <button type="button" class="btn quiet icon danger" data-del="${p.id}" aria-label="Delete ${esc(p.name)}" title="Delete channel">${icon("trash")}</button>
    </div></article>`;
}

function bindProfiles(ps) {
  $$("#aList [data-run]").forEach((b) => b.onclick = async () => { b.disabled = true; try { await api.post(`/api/auto/profiles/${b.dataset.run}/run`); toast("Started — this takes a few minutes"); refreshGlobal(); } catch (e) { fail(e); b.disabled = false; } });
  $$("#aList [data-cancel]").forEach((b) => b.onclick = () => cancelJob(b.dataset.cancel));
  $$("#aList [data-edit]").forEach((b) => b.onclick = () => openWizard(ps.find((p) => p.id === b.dataset.edit)));
  $$("#aList [data-connect]").forEach((a) => a.onclick = async (e) => {
    const c = await api.get("/api/youtube/client").catch(() => ({}));
    if (!c.has_client) { e.preventDefault(); toast("First do steps 1 and 2 under “Connect YouTube”", "info"); $("#aSetup")?.scrollIntoView({behavior: "smooth"}); }
  });
  $$("#aList [data-disc]").forEach((b) => b.onclick = async () => {
    if (!await confirmDialog({title: "Disconnect YouTube?", body: "Approved shorts won't upload until you connect again.", confirm: "Disconnect", danger: true})) return;
    try { await api.post(`/api/youtube/disconnect/${b.dataset.disc}`); toast("YouTube disconnected"); } catch (e) { fail(e); }
  });
  $$("#aList [data-del]").forEach((b) => b.onclick = async () => {
    const p = ps.find((x) => x.id === b.dataset.del);
    if (!await confirmDialog({title: `Delete “${p.name}”?`, body: "The channel's settings are removed. Shorts it made stay in your output folder.", confirm: "Delete Channel", danger: true})) return;
    try { await api.del(`/api/auto/profiles/${p.id}`); toast("Channel deleted"); } catch (e) { fail(e); }
  });
}

function renderSetup(ps, client) {
  const yts = ps.filter((p) => p.youtube);
  const allConnected = yts.length > 0 && yts.every((p) => p.youtube_status?.connected);
  const doneCount = (client.has_client ? 2 : 0) + (allConnected ? 1 : 0);
  const box = $("#aSetup"); if (!box) return;
  const s = `${client.has_client}|${allConnected}|${yts.length}`;
  if (box.dataset.sig === s) return;
  box.dataset.sig = s;
  box.innerHTML = `<section class="panel">
    <div class="row between"><div><h2 style="margin:0">Connect YouTube</h2><p class="sub" style="margin:2px 0 0">One-time setup so Clippy can upload for you. Free, about 10 minutes.</p></div>
      <span class="tag ${doneCount === 3 ? "ok" : "you"}">${doneCount} of 3 done</span></div>
    <div style="margin-top:8px">
      <div class="check ${client.has_client ? "done" : ""}"><span class="n">${client.has_client ? icon("check") : 1}</span><div class="t"><b>Create a free Google Cloud project</b>
        <p>Open <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener">console.cloud.google.com</a> and create a project called “Clippy”. Enable the
        <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noopener">YouTube Data API v3</a>. On the
        <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener">OAuth consent screen</a>, choose <b>External</b> and add your channel's Google account as a <b>test user</b>.</p></div></div>
      <div class="check ${client.has_client ? "done" : ""}"><span class="n">${client.has_client ? icon("check") : 2}</span><div class="t"><b>Download your key file and add it here</b>
        <p>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Credentials</a>, then Create credentials → OAuth client ID → <b>Desktop app</b> → Download JSON.</p>
        <div class="row" style="margin-top:10px"><label class="btn sm">${icon("upload")} ${client.has_client ? "Replace Key File" : "Choose Key File"}<input type="file" id="aClient" accept=".json,application/json" hidden></label>
          ${client.has_client ? `<span class="tag ok">${icon("check")} Key file added</span>` : ""}</div></div></div>
      <div class="check ${allConnected ? "done" : ""}"><span class="n">${allConnected ? icon("check") : 3}</span><div class="t"><b>Connect each channel</b>
        <p>Press <b>Connect YouTube</b> on a channel above and sign in with that channel's Google account.${yts.length ? ` ${yts.filter((p) => p.youtube_status?.connected).length} of ${yts.length} connected.` : ""}</p></div></div>
    </div>
    <div class="note" style="margin-top:14px"><div class="ic">${icon("info")}</div><div><b>Good to know</b><p>Google's free quota allows about 6 uploads a day. Videos from a new, unverified Google project stay <b>private</b> until Google approves it in a free API audit — until then, press publish in YouTube Studio. For TikTok, Clippy saves the video and caption for you to post from your phone.</p></div></div>
  </section>`;
  $("#aClient").onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    let data; try { data = JSON.parse(await f.text()); } catch { fail(new Error("That file isn't JSON. Download the key file again")); return; }
    try { await api.post("/api/youtube/client", data); toast("Key file added — now press Connect YouTube on a channel"); box.dataset.sig = ""; } catch (err) { fail(err); }
  };
}

// ── the wizard ──
const WZ_STEPS = ["Channel", "Content", "Sources", "Style", "Publishing", "Summary"];
function openWizard(existing) {
  const p = {...PROFILE_DEFAULTS, ...(existing || {})};
  p.sources = [...(p.sources || [])].map((s) => s.replace("https://www.youtube.com/", ""));
  p.niches = [...(p.niches || [])];
  const initial = JSON.stringify(p);
  let step = 0;
  const lenKey = () => (LENGTHS.find((l) => l[3] === p.min_seconds && l[4] === p.max_seconds) || [null])[0];
  const m = openModal(`<div class="mh"><div class="row between"><h2>${existing ? "Edit " + esc(existing.name) : "New autopilot channel"}</h2>
      <button type="button" class="btn quiet icon" data-close aria-label="Close">${icon("x")}</button></div><div id="wzStep"></div></div>
    <div class="mb" id="wzBody"></div>
    <div class="mf"><button type="button" class="btn quiet" id="wzBack">${icon("chevL")} Back</button><span class="grow small faint" id="wzCount"></span><span class="err-text" id="wzErr" role="alert"></span>
      <button type="button" class="btn primary" id="wzNext"></button></div>`,
    {label: "Channel setup", onClose: async () => JSON.stringify(p) === initial || await confirmDialog({title: "Discard your changes?", body: "What you entered in this setup will be lost.", confirm: "Discard", danger: true})});
  $("[data-close]", m).onclick = () => closeModal();
  const choice = (on, ic, title, sub, attrs) => `<button type="button" class="choice ${on ? "on" : ""}" aria-pressed="${on}" ${attrs}><span class="tick">${icon("check")}</span>${ic ? `<span class="ci">${icon(ic)}</span>` : ""}<b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</button>`;
  const valid = () => {
    if (step === 0) return p.name.trim().length > 0 || "Give your channel a name.";
    if (step === 1) return p.niches.length > 0 || p.keywords.trim().length > 0 || p.sources.length > 0 || "Pick at least one genre, or type keywords.";
    if (step === 2) return p.source_mode === "any" || p.sources.length > 0 || p.niches.length > 0 || "Add a source channel.";
    if (step === 4) return p.youtube || p.tiktok || "Choose where shorts should go.";
    return true;
  };
  const body = () => {
    const b = $("#wzBody", m);
    $("#wzErr", m).textContent = "";
    if (step === 0) {
      b.innerHTML = `<label for="wzName" class="wz-q" style="display:block">What's your channel called?</label><p class="wz-help">Only you see this. It helps you tell your channels apart.</p>
        <input class="input big" id="wzName" name="channel-name" autocomplete="off" value="${esc(p.name)}" placeholder="Daily Podcast Clips…" maxlength="60">
        <p class="wz-q" style="margin-top:28px">What language are your shorts in?</p><p class="wz-help">Clippy only picks videos in this language.</p>
        <div class="choices">${LANGS.map(([v, l]) => choice(p.language === v, "", l, "", `data-lang="${v}"`)).join("")}</div>`;
      const inp = $("#wzName", b); inp.oninput = () => { p.name = inp.value; };
      if (finePointer) setTimeout(() => inp.focus(), 50);
      inp.onkeydown = (e) => { if (e.key === "Enter") $("#wzNext", m).click(); };
      $$("[data-lang]", b).forEach((c) => c.onclick = () => { p.language = c.dataset.lang; body(); });
    } else if (step === 1) {
      b.innerHTML = `<p class="wz-q">What should Clippy look for?</p><p class="wz-help">Pick one or more genres. Clippy searches YouTube for the hottest videos in them.</p>
        <div class="choices">${state.niches.map((n) => choice(p.niches.includes(n), (NICHES[n] || ["film"])[0], nicheLabel(n), (NICHES[n] || ["", ""])[1], `data-n="${esc(n)}"`)).join("")}</div>
        <label class="field" style="margin-top:22px"><span>Anything specific? (optional)</span><input class="input" id="wzKw" autocomplete="off" value="${esc(p.keywords)}" placeholder="joe rogan, nba, ai news…"></label>
        <details class="more" style="margin-top:14px"><summary>${icon("chevR")} More options</summary><div class="grid g2">
          <div class="field"><span>Only videos uploaded in the last</span><div class="seg" id="wzWin">${[["today", "Day"], ["week", "Week"], ["month", "Month"], ["year", "Year"]].map(([v, l]) => `<button type="button" data-v="${v}" class="${p.window === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
          <div class="field"><span>Video length</span><div class="seg" id="wzDur">${[["any", "Any"], ["medium", "4–20 min"], ["long", "20+ min"]].map(([v, l]) => `<button type="button" data-v="${v}" class="${p.duration === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
        </div></details>`;
      $$("[data-n]", b).forEach((c) => c.onclick = () => { const n = c.dataset.n; p.niches = p.niches.includes(n) ? p.niches.filter((x) => x !== n) : [...p.niches, n]; c.classList.toggle("on"); c.setAttribute("aria-pressed", c.classList.contains("on")); });
      $("#wzKw", b).oninput = (e) => { p.keywords = e.target.value; };
      for (const [id, key] of [["wzWin", "window"], ["wzDur", "duration"]]) $$(`#${id} button`, b).forEach((x) => x.onclick = () => { p[key] = x.dataset.v; $$(`#${id} button`, b).forEach((y) => y.classList.toggle("on", y === x)); });
    } else if (step === 2) {
      b.innerHTML = `<p class="wz-q">Where may Clippy take videos from?</p><p class="wz-help">Reposting other people's videos without permission gets channels struck. Safe mode keeps you out of trouble.</p>
        <div class="choices wide">
          ${choice(p.source_mode === "safe", "shield", "Safe (recommended)", "Only the source channels you list below, plus Creative Commons videos (reuse allowed) from your genres. A credit line is added automatically.", 'data-mode="safe"')}
          ${choice(p.source_mode === "any", "alert", "Any video", "Any video from your genres. Choose this only if you have the rights or permission — otherwise expect copyright claims.", 'data-mode="any"')}
        </div>
        <label for="wzSrc" class="wz-q" style="display:block;margin-top:26px;font-size:19px">Source channels${p.source_mode === "safe" ? "" : " (optional)"}</label>
        <p class="wz-help">Creators you're allowed to clip — many run clipping programs. Clippy always checks their newest uploads.</p>
        <form class="row" id="wzAdd"><input class="input" id="wzSrc" autocomplete="off" spellcheck="false" placeholder="@channelname…" style="flex:1"><button class="btn">${icon("plus")} Add Channel</button></form>
        <div class="stack" style="margin-top:12px;gap:8px">${p.sources.map((s, i) => `<div class="srcrow">${icon("youtube")}<span>${esc(s)}</span><button type="button" class="btn quiet icon sm" data-rm="${i}" aria-label="Remove ${esc(s)}">${icon("x")}</button></div>`).join("") || `<p class="small faint">No source channels yet.${p.source_mode === "safe" ? " Without any, Clippy only uses Creative Commons videos from your genres." : ""}</p>`}</div>`;
      $$("[data-mode]", b).forEach((c) => c.onclick = () => { p.source_mode = c.dataset.mode; body(); });
      $("#wzAdd", b).onsubmit = (e) => {
        e.preventDefault(); const v = $("#wzSrc", b).value.trim(); if (!v) return;
        const handle = v.replace(/^https?:\/\/(www\.)?youtube\.com\//, "").replace(/\/(videos|featured|shorts)\/?$/, "");
        const h2 = handle.startsWith("@") || handle.includes("/") ? handle : "@" + handle;
        if (!p.sources.includes(h2)) p.sources.push(h2);
        body(); $("#wzSrc", m)?.focus();
      };
      $$("[data-rm]", b).forEach((x) => x.onclick = () => { p.sources.splice(+x.dataset.rm, 1); body(); });
    } else if (step === 3) {
      b.innerHTML = `<p class="wz-q">How should the shorts look?</p><p class="wz-help">Pick a saved style, or a caption style and color. You can change it any time.</p>
        ${PRESETS.length ? `<div class="presetbar" style="margin-bottom:16px"><label for="wzPreset">Saved style</label><select class="input" id="wzPreset">${presetOptions(p.preset, "None, pick below")}</select>
          ${p.preset ? `<span class="small faint">The saved style decides the captions, color and effects.</span>` : ""}</div>` : ""}
        <div class="styles ${p.preset ? "dimmed" : ""}" role="radiogroup" aria-label="Caption style">${STYLES.map(([k, n, d, pv]) => `<button type="button" role="radio" aria-checked="${!p.preset && p.caption_style === k}" class="style ${!p.preset && p.caption_style === k ? "on" : ""}" data-s="${esc(k)}">${stylePic(pv, n)}<div><b>${esc(n)}</b><small>${esc(d)}</small></div></button>`).join("")}</div>
        <div class="grid g2" style="margin-top:22px">
          <div class="field ${p.preset ? "dimmed" : ""}"><span>Highlight color</span><div class="swatches">${COLORS.map((c) => `<button type="button" class="swatch ${!p.preset && p.highlight_color === c ? "on" : ""}" style="background:${c}" data-c="${c}" aria-label="${c}"></button>`).join("")}</div></div>
          <div class="field"><span>Shorts per run</span><div class="seg" id="wzClips">${[1, 2, 3, 5].map((n) => `<button type="button" data-v="${n}" class="${p.clips_per_video === n ? "on" : ""}">${n}</button>`).join("")}</div>
            <div class="hint">From the best new video each run</div></div>
        </div>
        <div class="field" style="margin-top:20px"><span>Short length</span><div class="choices">${LENGTHS.map(([k, n, d]) => choice(lenKey() === k, "", n, d, `data-len="${k}"`)).join("")}</div></div>`;
      $("#wzPreset", b)?.addEventListener("change", (e) => { p.preset = e.target.value; body(); });
      $$("[data-s]", b).forEach((c) => c.onclick = () => { p.preset = ""; p.caption_style = c.dataset.s; body(); });
      $$("[data-c]", b).forEach((c) => c.onclick = () => { p.preset = ""; p.highlight_color = c.dataset.c; body(); });
      $$("#wzClips button", b).forEach((x) => x.onclick = () => { p.clips_per_video = +x.dataset.v; $$("#wzClips button", b).forEach((y) => y.classList.toggle("on", y === x)); });
      $$("[data-len]", b).forEach((c) => c.onclick = () => { const l = LENGTHS.find((x) => x[0] === c.dataset.len); p.min_seconds = l[3]; p.max_seconds = l[4]; body(); });
    } else if (step === 4) {
      b.innerHTML = `<p class="wz-q">How often should it run?</p><p class="wz-help">Each run finds a new video and makes shorts for you to review. Runs happen while Clippy is running — turn on “Start at login” in Settings to keep it running.</p>
        <div class="choices">${SCHEDULES.map(([h, n, d]) => choice(p.auto_every_hours === h, "", n, d, `data-every="${h}"`)).join("")}</div>
        <p class="wz-q" style="margin-top:26px">Where should approved shorts go?</p><p class="wz-help">Nothing is posted until you approve it in Review.</p>
        <div class="grid g2">
          <label class="switch"><span class="ic">${icon("youtube")}</span><span class="txt"><b>YouTube Shorts</b><small>Uploads automatically after you approve</small></span><input type="checkbox" id="wzYt" ${p.youtube ? "checked" : ""}></label>
          <label class="switch"><span class="ic">${icon("phone")}</span><span class="txt"><b>TikTok</b><small>Saves the video and caption to post from your phone</small></span><input type="checkbox" id="wzTt" ${p.tiktok ? "checked" : ""}></label>
        </div>
        <div id="wzYtOpts" class="${p.youtube ? "" : "hidden"}">
          <p class="wz-q" style="margin-top:26px;font-size:19px">When should YouTube shorts go live?</p>
          <div class="choices">${SPACING.map(([h, n, d]) => choice(p.spacing_hours === h, "", n, d, `data-space="${h}"`)).join("")}</div>
          <details class="more" style="margin-top:16px"><summary>${icon("chevR")} Advanced YouTube options</summary><div class="stack">
            <div class="grid g2"><label class="field"><span>Visibility</span><select class="input" id="wzPriv">${[["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]].map(([v, l]) => `<option value="${v}" ${p.privacy === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
              <label class="field"><span>Category</span><select class="input" id="wzCat">${[["24", "Entertainment"], ["22", "People & Blogs"], ["17", "Sports"], ["23", "Comedy"], ["27", "Education"], ["28", "Science & Technology"], ["20", "Gaming"], ["25", "News & Politics"]].map(([v, l]) => `<option value="${v}" ${p.category_id === v ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
            <label class="field"><span>Description template</span><textarea class="input" id="wzDesc" rows="4">${esc(p.description_template)}</textarea><div class="hint">Placeholders: {caption} {hashtags} {title} {source_channel} {source_url}</div></label>
            <label class="field"><span>Extra hashtags</span><input class="input" id="wzTags" autocomplete="off" value="${esc(p.extra_hashtags)}" placeholder="#podcast #clips…"></label>
          </div></details></div>`;
      $$("[data-every]", b).forEach((c) => c.onclick = () => { p.auto_every_hours = +c.dataset.every; $$("[data-every]", b).forEach((x) => x.classList.toggle("on", x === c)); });
      $$("[data-space]", b).forEach((c) => c.onclick = () => { p.spacing_hours = +c.dataset.space; $$("[data-space]", b).forEach((x) => x.classList.toggle("on", x === c)); });
      $("#wzYt", b).onchange = (e) => { p.youtube = e.target.checked; $("#wzYtOpts", b).classList.toggle("hidden", !p.youtube); };
      $("#wzTt", b).onchange = (e) => { p.tiktok = e.target.checked; };
      $("#wzPriv", b).onchange = (e) => { p.privacy = e.target.value; };
      $("#wzCat", b).onchange = (e) => { p.category_id = e.target.value; };
      $("#wzDesc", b).oninput = (e) => { p.description_template = e.target.value; };
      $("#wzTags", b).oninput = (e) => { p.extra_hashtags = e.target.value; };
    } else {
      const where = [p.youtube && "YouTube Shorts", p.tiktok && "TikTok (saved for your phone)"].filter(Boolean).join(" and ");
      const len = LENGTHS.find((l) => l[0] === lenKey());
      const lines = [
        ["calendar", "When", `<b>${everyLabel(p.auto_every_hours)}</b>${p.auto_every_hours ? ", while Clippy is running," : ""} a new run starts.`],
        ["search", "Find", `It searches ${p.niches.length ? `<b>${esc(p.niches.map(nicheLabel).join(", "))}</b>` : "your source channels"}${p.keywords ? ` plus “${esc(p.keywords)}”` : ""} in <b>${esc((LANGS.find((l) => l[0] === p.language) || ["", "any language"])[1])}</b>${p.sources.length ? `, and always checks <b>${p.sources.length} source channel${p.sources.length > 1 ? "s" : ""}</b>` : ""}.`],
        ["shield", "Sources", p.source_mode === "safe" ? "<b>Safe mode:</b> only your source channels and Creative Commons videos. Credit goes in every description." : "<b>Any video.</b> Make sure you have the rights."],
        ["film", "Make", `It picks the best new video and makes <b>${p.clips_per_video} short${p.clips_per_video > 1 ? "s" : ""}</b> (${len ? len[2] : `${p.min_seconds}–${p.max_seconds} seconds`}) in the <b>${esc(PRESETS.find((x) => x.id === p.preset)?.name || STYLES.find((s) => s[0] === p.caption_style)?.[1] || p.caption_style)}</b> style.`],
        ["checkCircle", "You", "They wait in <b>Review</b> until you approve them. Nothing is posted without you."],
        ["upload", "Publish", `Approved shorts go to <b>${esc(where)}</b>${p.youtube ? (p.spacing_hours ? `, one every <b>${p.spacing_hours} hours</b>` : ", <b>right away</b>") : ""}.`],
      ];
      b.innerHTML = `<p class="wz-q">Here's what will happen</p><p class="wz-help">Check that it reads right, then save.</p>
        <div class="summary">${lines.map(([ic, t, txt]) => `<div class="sline"><div class="ic">${icon(ic)}</div><div><b>${t}</b><p>${txt}</p></div></div>`).join("")}</div>
        ${p.youtube ? `<div class="note you" style="margin-top:14px"><div class="ic">${icon("info")}</div><div><b>Next: connect YouTube</b><p>After saving, press <b>Connect YouTube</b> on the channel so approved shorts can upload.</p></div></div>` : ""}`;
    }
    $("#wzStep", m).innerHTML = stepper(WZ_STEPS, step);
    $("#wzBack", m).style.visibility = step ? "visible" : "hidden";
    $("#wzCount", m).textContent = `Step ${step + 1} of ${WZ_STEPS.length}`;
    $("#wzNext", m).innerHTML = step === WZ_STEPS.length - 1 ? `${icon("check")} ${existing ? "Save Changes" : "Save Channel"}` : `Next: ${WZ_STEPS[step + 1]} ${icon("chevR")}`;
    $("#wzBody", m).scrollTop = 0;
  };
  $("#wzBack", m).onclick = () => { if (step > 0) { step--; body(); } };
  $("#wzNext", m).onclick = async () => {
    const v = valid();
    if (v !== true) { $("#wzErr", m).textContent = v; (step === 0 ? $("#wzName", m) : step === 2 ? $("#wzSrc", m) : null)?.focus(); return; }
    if (step < WZ_STEPS.length - 1) { step++; body(); return; }
    const payload = {...p, id: existing?.id, name: p.name.trim(), sources: p.sources};
    for (const k of ["youtube_status", "job", "pending", "published", "failed", "used_count", "used", "next_run", "last_error", "last_run", "last_publish_at"]) delete payload[k];
    $("#wzNext", m).disabled = true;
    try {
      await api.post("/api/auto/profiles", payload);
      closeModal(true); toast(existing ? "Changes saved" : `“${payload.name}” is on autopilot`);
      if ($("#aList")) route();
    } catch (e) { $("#wzNext", m).disabled = false; fail(e); }
  };
  body();
}

// ═════════════════════════ REVIEW ═════════════════════════
const LIC = {cc: ["ok", "shield", "Creative Commons"], source: ["ok", "shield", "Your source channel"], unknown: ["err", "alert", "No reuse licence — check you have permission"]};
const RV_TABS = [["pending", "Waiting"], ["approved,uploading,failed", "Publishing"], ["uploaded", "Published"], ["rejected", "Rejected"]];
pages.review = async (el) => {
  let tab = params().get("tab") || "pending";
  if (!RV_TABS.some(([k]) => k === tab)) tab = "pending";
  el.innerHTML = `<div class="ph"><div><h1>Review</h1><p>Watch each short, fix the title or description if you want, then approve. Approved shorts publish automatically after 10 seconds.</p></div></div>
    <div class="row between" style="margin-bottom:18px"><div class="seg" id="rvTabs" role="tablist" aria-label="Filter shorts"></div>
      <div class="keys" aria-hidden="true"><span><kbd>J</kbd> <kbd>K</kbd> Next and previous</span><span><kbd>A</kbd> Approve</span><span><kbd>R</kbd> Reject</span></div></div>
    <div class="stack" id="rvList" style="gap:16px"></div>`;
  let cur = 0, sig = "";
  const tabs = () => {
    const c = state.overview?.review || {};
    const count = (k) => k.split(",").reduce((a, s) => a + (c[s] || 0), 0);
    $("#rvTabs").innerHTML = RV_TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${tab === k}" data-t="${k}" class="${tab === k ? "on" : ""}">${l}${count(k) ? `<span class="badge ${k === "pending" ? "" : "quiet"}">${count(k)}</span>` : ""}</button>`).join("");
    $$("#rvTabs button").forEach((b) => b.onclick = () => { tab = b.dataset.t; setParam("tab", tab); cur = 0; load(true); });
  };
  const cards = () => $$("#rvList .rv");
  const focusCard = (i, scroll = true) => {
    const cs = cards(); if (!cs.length) return;
    cur = Math.max(0, Math.min(cs.length - 1, i));
    cs.forEach((c, k) => c.classList.toggle("cur", k === cur));
    if (scroll) cs[cur].scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
  };
  const act = async (id, action, btn) => {
    const t = $(`[data-title="${id}"]`), d = $(`[data-desc="${id}"]`), extra = {};
    if (t && !t.disabled) extra.title = t.value;
    if (d && !d.disabled) extra.description = d.value;
    if (btn) btn.disabled = true;
    try { await reviewAction(id, action, extra, () => load(true)); if (action !== "save") load(true); else if (btn) btn.disabled = false; }
    catch (e) { fail(e); if (btn) btn.disabled = false; }
  };
  const load = async (force) => {
    await refreshGlobal(); if (!$("#rvTabs")) return; tabs();
    let items; try { items = await api.get("/api/review?status=" + encodeURIComponent(tab)); } catch { return; }
    const s = JSON.stringify(items.map((i) => [i.id, i.status, i.upload_pct, i.error]));
    if (!force && s === sig) return;
    if (!force && $("#rvList")?.contains(document.activeElement) && ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;  // never wipe what you're typing
    sig = s;
    if (!items.length) {
      $("#rvList").innerHTML = tab === "pending"
        ? emptyState("checkCircle", "All caught up", "No shorts waiting. Run a channel in <a href=\"#auto\">Autopilot</a> or clip a video, and new shorts show up here.")
        : emptyState("film", "Nothing here yet", "Shorts appear here as they move through publishing.");
      return;
    }
    $("#rvList").innerHTML = items.map(reviewCard).join("");
    $$("[data-title]").forEach((inp) => inp.oninput = () => { $(`[data-cnt="${inp.dataset.title}"]`).textContent = inp.value.length + "/100"; });
    $$("#rvList [data-act]").forEach((b) => b.onclick = () => act(b.dataset.id, b.dataset.act, b));
    bindFix($("#rvList"), () => load(true));
    cards().forEach((c, k) => c.addEventListener("focusin", () => focusCard(k, false)));
    focusCard(Math.min(cur, items.length - 1), false);
    if (items.some((i) => i.status === "approved" || i.status === "uploading")) setTimeout(() => { if ($("#rvList")) load(false); }, 2500);
  };
  const onKey = (e) => {
    if (!$("#rvList")) { document.removeEventListener("keydown", onKey); return; }
    if (e.metaKey || e.ctrlKey || e.altKey || $("#modal") || $(".modal-bg[data-confirm]") || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
    const k = e.key.toLowerCase(), c = cards()[cur];
    if (k === "j") { focusCard(cur + 1); e.preventDefault(); }
    else if (k === "k") { focusCard(cur - 1); e.preventDefault(); }
    else if ((k === "a" || k === "r") && c && tab === "pending") { act(c.dataset.id, k === "a" ? "approve" : "reject"); e.preventDefault(); }
  };
  document.addEventListener("keydown", onKey);
  await load(true); repeat(4000, () => load(false));
};

function reviewCard(i) {
  const [lc, lic, lt] = LIC[i.licence] || LIC.unknown;
  const yt = i.youtube;
  const editable = i.status === "pending" || i.status === "failed";
  let actions;
  if (i.status === "pending") actions = `<button type="button" class="btn primary" data-act="approve" data-id="${i.id}">${icon("check")} Approve &amp; Publish</button>
      <button type="button" class="btn" data-act="save" data-id="${i.id}">Save Edits</button><button type="button" class="btn" data-fix-file="${esc(i.file)}">${icon("pencil")} Quick Fix</button><button type="button" class="btn quiet danger" data-act="reject" data-id="${i.id}">${icon("x")} Reject</button>`;
  else if (i.status === "approved") actions = `<span class="tag you"><span class="spin" style="width:12px;height:12px"></span> Uploading in a few seconds</span><button type="button" class="btn sm quiet" data-act="restore" data-id="${i.id}">Undo</button>`;
  else if (i.status === "uploading") actions = `<div style="flex:1;max-width:320px"><div class="row small" style="gap:8px;margin-bottom:6px"><span class="dot live"></span>Uploading <span class="num">${Math.round((i.upload_pct || 0) * 100)}%</span></div><div class="bar"><i style="width:${Math.round((i.upload_pct || 0) * 100)}%"></i></div></div>`;
  else if (i.status === "failed") actions = `<button type="button" class="btn primary" data-act="retry" data-id="${i.id}">${icon("refresh")} Try Again</button><button type="button" class="btn" data-fix-file="${esc(i.file)}">${icon("pencil")} Quick Fix</button><button type="button" class="btn quiet danger" data-act="reject" data-id="${i.id}">Reject</button>`;
  else if (i.status === "uploaded") actions = `${yt ? `<a class="btn primary" href="${esc(yt.url)}" target="_blank" rel="noopener">${icon("youtube")} View on YouTube</a>
      <span class="tag ${yt.privacy === "public" ? "ok" : ""}">${esc(yt.privacy)}${yt.publish_at ? `, goes live ${fmtDate(yt.publish_at)}` : ""}</span>` : ""}
      ${i.tiktok ? `<a class="btn" href="/media/${encodeURI(i.tiktok.file)}" download>${icon("phone")} TikTok File</a>` : ""}`;
  else actions = `<button type="button" class="btn" data-act="restore" data-id="${i.id}">${icon("refresh")} Move Back to Waiting</button>`;
  return `<article class="panel rv" data-id="${i.id}" aria-label="${esc(i.title)}">
    <video src="/media/${encodeURI(i.file)}" ${i.thumb ? `poster="/media/${encodeURI(i.thumb)}"` : ""} controls preload="none" playsinline width="240" height="427"></video>
    <div class="f">
      <div class="row small muted"><span class="tag">${icon("bot")} ${esc(i.profile_name)}</span><span class="tag ${lc}">${icon(lic)} ${lt}</span>
        ${i.score ? `<span class="score ${scoreCls(i.score)}" title="AI score">${i.score}</span>` : ""}<span class="num">${Math.round(i.duration || 0)}&nbsp;s</span><span>made ${rel(i.created)}</span></div>
      <div class="small muted break">From <a href="${esc(i.source_url)}" target="_blank" rel="noopener">${esc(i.source_channel || "the source video")}</a>: ${esc(i.source_title || "")}</div>
      ${i.status === "failed" ? `<div class="note err"><div class="ic">${icon("alert")}</div><div><b>The upload failed</b><p>${esc(i.error || "")}</p></div></div>` : ""}
      <div><div class="lbl"><label for="t-${i.id}">Title</label><span data-cnt="${i.id}" class="num">${(i.title || "").length}/100</span></div>
        <input class="input" id="t-${i.id}" type="text" maxlength="100" autocomplete="off" data-title="${i.id}" value="${esc(i.title)}" ${editable ? "" : "disabled"}></div>
      <div><div class="lbl"><label for="d-${i.id}">Description</label></div><textarea class="input" id="d-${i.id}" rows="5" data-desc="${i.id}" ${editable ? "" : "disabled"}>${esc(i.description)}</textarea></div>
      <div class="row">${actions}<a class="btn quiet icon" href="/media/${encodeURI(i.file)}" download aria-label="Download this short" title="Download">${icon("download")}</a></div>
    </div></article>`;
}

// ───────────────────────── quick fix ─────────────────────────
// fix an almost-good short without another editor: where it starts and ends, misspelled caption words, its title
const fmtT = (s) => { s = Math.max(0, +s || 0); const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`; };
function bindFix(root, after) {
  $$("[data-fix-file]", root).forEach((b) => b.onclick = () => openQuickFix(b.dataset.fixFile, {after}));
}
async function openQuickFix(file, {after = () => {}} = {}) {
  let d;
  try { d = await api.get("/api/fix?file=" + encodeURIComponent(file)); } catch (e) { fail(e); return; }
  const st = {start: d.start, end: d.end, words: {}, title: d.title, sel: null, busy: false};
  const list = d.words, pos = new Map(list.map((w, k) => [w.i, k]));
  const bounds = d.kind !== "countdown", hasWords = list.length > 0;
  const r3 = (x) => Math.round(x * 1000) / 1000;
  const inShort = (w) => d.kind === "countdown" ? d.segments.some((g) => w.s >= g.start - 0.05 && w.e <= g.end + 0.05)
    : w.s >= st.start - 0.05 && w.e <= st.end + 0.05;
  const text = (w) => st.words[w.i] ?? w.w;
  const pending = () => {
    const out = [], ds = st.start - d.start, de = st.end - d.end;
    if (Math.abs(ds) > 0.01) out.push(`Starts ${Math.abs(ds).toFixed(1)} s ${ds < 0 ? "earlier" : "later"}`);
    if (Math.abs(de) > 0.01) out.push(`Ends ${Math.abs(de).toFixed(1)} s ${de < 0 ? "earlier" : "later"}`);
    for (const [i, v] of Object.entries(st.words)) { const w = list[pos.get(+i)]; out.push(v === w.orig && w.w !== w.orig ? `“${w.w}” back to “${v}”` : `“${w.w}” becomes “${v}”`); }
    if (st.title.trim() && st.title.trim() !== d.title) out.push("A new title");
    return out;
  };
  const nudges = (which) => [-1, -0.25, 0.25, 1].map((v) => `<button type="button" class="btn sm quiet" data-nudge="${which}:${v}" aria-label="${which === "start" ? "Start" : "End"} ${Math.abs(v)} seconds ${v < 0 ? "earlier" : "later"}">${v < 0 ? "−" : "+"}${Math.abs(v) === 0.25 ? "¼" : "1"}&thinsp;s</button>`).join("");
  const srcNote = d.source ? "" : d.redownload
    ? `<div class="note"><div class="ic">${icon("info")}</div><div><b>The downloaded video was deleted</b><p>Previews need it. Rendering downloads it again first, so that takes a little longer.</p></div></div>`
    : `<div class="note err"><div class="ic">${icon("alert")}</div><div><b>The original video isn't on this PC anymore</b><p>It was deleted, so this short can't be rendered again. Upload the video again and make new shorts from it.</p></div></div>`;
  const m = openModal(`<div class="mh"><div class="row between"><h2>Quick Fix</h2><button type="button" class="btn quiet icon" data-close aria-label="Close">${icon("x")}</button></div>
      <p class="muted small" style="margin:4px 0 0">Change where it starts and ends, or fix a misspelled word, then render just this short again.</p></div>
    <div class="mb" id="qf"><div class="qf">
      <div class="qf-side">
        <video class="qf-short" src="/media/${encodeURI(d.file)}" poster="/media/${encodeURI(d.file.replace(/\.mp4$/i, ".jpg"))}" controls playsinline preload="metadata" aria-label="The current short"></video>
        <p class="small faint" style="margin:6px 0 0">The current short${d.short_duration ? `, ${Math.round(d.short_duration)} s` : ""}. It stays until the new one is ready.</p>
        <div class="qf-changes" id="qfChanges" aria-live="polite"></div>
      </div>
      <div class="qf-main">
        ${d.source ? `<video id="qfSrc" class="qf-src" src="/media/${encodeURI(d.source)}#t=${d.start}" preload="metadata" playsinline controls aria-label="The original video"></video>` : srcNote}
        ${bounds ? `<div class="qf-bounds">
          <div class="qf-b"><div><span class="small muted">Starts at</span> <b class="num" id="qfS"></b></div>
            <div class="row" style="gap:4px">${nudges("start")}${d.source ? `<button type="button" class="btn sm" data-q="playStart">${icon("play")} Play the Start</button>` : ""}</div></div>
          <div class="qf-b"><div><span class="small muted">Ends at</span> <b class="num" id="qfE"></b></div>
            <div class="row" style="gap:4px">${nudges("end")}${d.source ? `<button type="button" class="btn sm" data-q="playEnd">${icon("play")} Play the End</button>` : ""}</div></div>
          <p class="small faint" id="qfLen" style="margin:0"></p></div>`
          : `<div class="note"><div class="ic">${icon("info")}</div><div><b>A countdown</b><p>Fix its words and title here. Its moments can't be moved yet.</p></div></div>`}
        ${hasWords ? `<div><div class="lbl"><span>What's said</span><span class="small faint">Tap a word to start or end the short there, or to fix it</span></div>
            <div class="qf-tool" id="qfTool"></div><div class="qf-words" id="qfWords" role="group" aria-label="Transcript"></div></div>`
          : d.kind === "visual" ? `<p class="small faint" style="margin:0">No talking in this short, so there are no captions to fix.</p>` : ""}
        <div><div class="lbl"><label for="qfTitle">Title on the short</label></div><input class="input" id="qfTitle" type="text" maxlength="100" autocomplete="off" value="${esc(d.title)}"></div>
      </div></div></div>
    <div class="mf"><div class="grow small" id="qfStatus" aria-live="polite"></div><button type="button" class="btn quiet" data-close>Close</button>
      <button type="button" class="btn primary" id="qfGo">${icon("refresh")} Render This Short</button></div>`,
    {label: "Quick Fix", onClose: async () => {
      if (st.busy) { toast("It keeps rendering. The new short shows up when it's done.", "info"); return true; }
      return !pending().length || await confirmDialog({title: "Discard your changes?", body: "They haven't been rendered yet.", confirm: "Discard", danger: true});
    }});
  $$("[data-close]", m).forEach((b) => b.onclick = () => closeModal());
  const v = $("#qfSrc", m);
  let stopAt = null;
  const play = (a, b) => { if (!v) return; v.currentTime = Math.max(0, a); stopAt = b; v.play().catch(() => {}); };
  if (v) v.addEventListener("timeupdate", () => {
    if (stopAt != null && v.currentTime >= stopAt) { v.pause(); stopAt = null; }
    const now = !v.paused && list.find((w) => v.currentTime >= w.s && v.currentTime <= w.e + 0.05);
    $$(".qw.now", m).forEach((b) => b.classList.remove("now"));
    if (now) $(`.qw[data-i="${now.i}"]`, m)?.classList.add("now");          // the word being said while it plays
  });
  if (v) v.addEventListener("pause", () => $$(".qw.now", m).forEach((b) => b.classList.remove("now")));
  const draw = () => {
    if (bounds) {
      $("#qfS", m).textContent = fmtT(st.start); $("#qfE", m).textContent = fmtT(st.end);
      const lost = d.teaser && (st.start > d.teaser.start + 0.01 || st.end < d.teaser.end - 0.01);
      const tz = d.teaser && !lost ? ` It opens with a ${(d.teaser.end - d.teaser.start).toFixed(1)} s flash-forward from ${fmtT(d.teaser.start)} (the teaser), then plays from the start.` : "";
      $("#qfLen", m).textContent = `${(st.end - st.start).toFixed(1)} s of the video. Pauses are cut when it renders, so the short ends up a little shorter.${tz}${lost ? " Its flash-forward teaser is left out: that moment isn't between the new start and end." : ""}`;
    }
    if (hasWords) {
      const ins = list.filter(inShort), first = ins[0]?.i, last = ins[ins.length - 1]?.i;
      $("#qfWords", m).innerHTML = list.map((w) => `<button type="button" class="qw${inShort(w) ? " in" : ""}${w.i === first ? " first" : ""}${w.i === last ? " last" : ""}${d.fixed[w.i] != null ? " fixed" : ""}${st.words[w.i] != null ? " pend" : ""}${st.sel === w.i ? " sel" : ""}" data-i="${w.i}" title="${fmtT(w.s)}${w.w !== w.orig ? `: was “${esc(w.orig)}”` : ""}">${esc(text(w))}</button>`).join(" ");
      $$(".qw", m).forEach((b) => b.onclick = () => { st.sel = +b.dataset.i; draw(); $("#qfWord", m)?.focus(); });
      const w = st.sel != null ? list[pos.get(st.sel)] : null;
      $("#qfTool", m).innerHTML = w ? `<span class="small muted">“${esc(text(w))}” at ${fmtT(w.s)}</span>
        ${bounds ? `<button type="button" class="btn sm" data-q="startHere">Start Here</button><button type="button" class="btn sm" data-q="endHere">End Here</button>` : ""}
        ${d.source ? `<button type="button" class="btn sm quiet" data-q="playWord">${icon("play")} Play</button>` : ""}
        <input class="input" id="qfWord" type="text" maxlength="60" autocomplete="off" spellcheck="true" value="${esc(text(w))}" aria-label="Correct this word">
        <button type="button" class="btn sm" data-q="setWord">${icon("pencil")} Fix Word</button>` : "";
      $("#qfWord", m)?.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); act("setWord"); } });
      $$("#qfTool [data-q]", m).forEach((b) => b.onclick = () => act(b.dataset.q));
    }
    const ch = pending();
    $("#qfChanges", m).innerHTML = ch.length ? `<b class="small">Changes to render</b><ul class="small">${ch.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : "";
    if (!st.busy) {
      $("#qfStatus", m).textContent = ch.length ? `${ch.length} change${ch.length > 1 ? "s" : ""} to render` : "No changes yet";
      $("#qfGo", m).disabled = !ch.length || (!d.source && !d.redownload);
    }
  };
  const act = (q) => {
    const w = st.sel != null ? list[pos.get(st.sel)] : null, k = w ? pos.get(w.i) : -1;
    if (q === "playStart") play(st.start, st.start + 4);
    else if (q === "playEnd") play(Math.max(st.start, st.end - 4), st.end);
    else if (q === "playWord" && w) play(w.s - 0.3, w.e + 0.5);
    else if (q === "startHere" && w) {
      let s = w.s - 0.12; if (k > 0) s = Math.max(s, list[k - 1].e + 0.02);     // like the AI's own picks
      if (st.end - s < 3) return toast("A short needs at least 3 seconds", "bad");
      st.start = r3(Math.max(0, s)); draw();
    } else if (q === "endHere" && w) {
      let e = w.e + 0.45; if (k < list.length - 1) e = Math.min(e, list[k + 1].s - 0.03); e = Math.max(e, w.e + 0.05);
      if (e - st.start < 3) return toast("A short needs at least 3 seconds", "bad");
      st.end = r3(Math.min(d.duration, e)); draw();
    } else if (q === "setWord" && w) {
      const nv = ($("#qfWord", m).value || "").replace(/\s+/g, " ").trim();
      if (!nv || nv === w.w) delete st.words[w.i]; else st.words[w.i] = nv;
      st.sel = null; draw();
      $(`.qw[data-i="${w.i}"]`, m)?.focus();
    }
  };
  $$("[data-q]", m).forEach((b) => b.onclick = () => act(b.dataset.q));
  $$("[data-nudge]", m).forEach((b) => b.onclick = () => {
    const [which, dv] = b.dataset.nudge.split(":"); const dlt = +dv;
    if (which === "start") st.start = r3(Math.max(0, Math.min(st.end - 3, st.start + dlt)));
    else st.end = r3(Math.min(d.duration, Math.max(st.start + 3, st.end + dlt)));
    draw();
  });
  $("#qfTitle", m).oninput = (e) => { st.title = e.target.value; draw(); };
  $("#qfGo", m).onclick = async () => {
    const body = {file: d.file};
    if (Math.abs(st.start - d.start) > 0.01) body.start = st.start;
    if (Math.abs(st.end - d.end) > 0.01) body.end = st.end;
    if (Object.keys(st.words).length) body.words = st.words;
    if (st.title.trim() && st.title.trim() !== d.title) body.title = st.title.trim();
    st.busy = true; $("#qfGo", m).disabled = true;
    $("#qfStatus", m).innerHTML = `<div class="bar wait"><i style="width:0%"></i></div><span class="faint">Waiting in line…</span>`;
    let job;
    try { job = await api.post("/api/fix", body); }
    catch (e) { st.busy = false; draw(); $("#qfStatus", m).innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
    const t = setInterval(async () => {
      let j; try { j = await api.get("/api/jobs/" + job.id); } catch { return; }
      const open = $("#qf") === $("#qf", m) && document.body.contains(m);
      if (j.state === "done") {
        clearInterval(t); st.busy = false; after(j.result, d.file); refreshGlobal();
        toast("Short updated: the new version is ready");
        if (open) openQuickFix(j.result.file, {after});          // the editor again, now on the new short
        return;
      }
      if (j.state === "error" || j.state === "cancelled") {
        clearInterval(t); st.busy = false;
        if (open) { draw(); $("#qfStatus", m).innerHTML = `<span class="err-text">${esc(j.error || "Cancelled")}</span>`; }
        else toast(j.error || "The fix was cancelled", "bad");
        return;
      }
      if (open) $("#qfStatus", m).innerHTML = `<div class="bar ${j.state === "queued" ? "wait" : ""}"><i style="width:${Math.round((j.pct || 0) * 100)}%"></i></div><span class="faint">${esc(j.msg || "Rendering…")}</span>`;
    }, 1000);
  };
  draw();
  const box = $("#qfWords", m), first = $(".qw.first", m) || $(".qw.in", m);
  if (box && first) box.scrollTop = Math.max(0, first.offsetTop - box.offsetTop - 34);   // open where the short starts
}

// ───────────────────────── find a quote ─────────────────────────
// the line the AI skipped: search what's said beside the video, pick the first and last line, make it a short
async function openQuote(video, {after = () => {}} = {}) {
  let d;
  try { d = await api.get(`/api/transcript/${encodeURIComponent(video)}`); } catch (e) { fail(e); return; }
  const st = {first: null, last: null, q: "", title: "", typed: false, busy: false, preset: store.get("make", {}).preset || ""};
  const canMake = !!d.source || d.redownload;
  const m = openModal(`<div class="mh"><div class="row between"><h2>Find a Quote</h2><button type="button" class="btn quiet icon" data-close aria-label="Close">${icon("x")}</button></div>
      <p class="muted small break" style="margin:4px 0 0">${esc(d.title)}. Search what's said, pick the first and last line, and Clippy makes it a short with the usual captions and framing.</p></div>
    <div class="mb"><div class="qq">
      <div class="qq-side">
        ${d.source ? `<video id="qqSrc" class="qf-src" src="/media/${encodeURI(d.source)}#t=${d.lines[0]?.s || 0}" preload="metadata" playsinline controls aria-label="The video"></video>`
          : `<div class="note ${canMake ? "" : "err"}"><div class="ic">${icon(canMake ? "info" : "alert")}</div><div><b>The downloaded video was deleted</b><p>${canMake ? "Making a clip downloads it again first." : "It was an uploaded file, so it can't come back. Upload the video again to make clips from it."}</p></div></div>`}
        <div id="qqPick" class="qq-pick" aria-live="polite"></div>
        <div id="qqDone"></div>
      </div>
      <div class="qq-main">
        <div class="qq-search">${icon("search")}<input class="input" id="qqFind" type="search" placeholder="Search what's said" autocomplete="off" aria-label="Search the transcript"></div>
        <p class="small faint" id="qqCount" style="margin:8px 0"></p>
        <div class="qq-lines" id="qqLines"></div>
      </div></div></div>
    <div class="mf"><div class="grow small" id="qqStatus" aria-live="polite"></div><button type="button" class="btn quiet" data-close>Close</button>
      <button type="button" class="btn primary" id="qqGo" disabled>${icon("scissors")} Make This Clip</button></div>`,
    {label: "Find a Quote", onClose: () => { if (st.busy) toast("It keeps going. The clip shows up in the Library when it's ready.", "info"); return true; }});
  $$("[data-close]", m).forEach((b) => b.onclick = () => closeModal());
  const v = $("#qqSrc", m);
  let stopAt = null;
  const play = (a, b) => { if (!v) return; v.currentTime = Math.max(0, a); stopAt = b; v.play().catch(() => {}); };
  if (v) v.addEventListener("timeupdate", () => { if (stopAt != null && v.currentTime >= stopAt) { v.pause(); stopAt = null; } });
  const range = () => st.first == null || st.last == null ? null : [Math.min(st.first, st.last), Math.max(st.first, st.last)];
  const defaultTitle = (l) => l.text.split(/\s+/).slice(0, 7).join(" ").replace(/[,.;:!?]+$/, "");
  const draw = () => {
    const q = st.q.trim(), ql = q.toLowerCase(), r = range();
    const shown = d.lines.filter((l) => !ql || l.text.toLowerCase().includes(ql));
    const rx = q ? new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi") : null;
    $("#qqCount", m).textContent = q ? `${shown.length} line${shown.length === 1 ? "" : "s"} with “${q}”` : `${d.lines.length} lines. Tap one to play it.`;
    $("#qqLines", m).innerHTML = shown.length ? shown.map((l) => {
      const cls = [r && l.n >= r[0] && l.n <= r[1] ? "in" : "", l.n === st.first ? "first" : "", l.n === st.last ? "last" : ""].join(" ");
      const txt = rx ? esc(l.text).replace(rx, (x) => `<mark>${x}</mark>`) : esc(l.text);
      return `<div class="ql ${cls}" data-n="${l.n}"><button type="button" class="ql-x" data-seek="${l.n}"><span class="num faint">${fmtT(l.s)}</span> ${txt}</button>
        <span class="ql-b"><button type="button" class="btn sm ${l.n === st.first ? "on" : ""}" data-first="${l.n}" aria-pressed="${l.n === st.first}">First</button><button type="button" class="btn sm ${l.n === st.last ? "on" : ""}" data-last="${l.n}" aria-pressed="${l.n === st.last}">Last</button></span></div>`;
    }).join("") : `<p class="small muted" style="margin:8px">Nothing like that is said in this video. Try another word.</p>`;
    $$("[data-seek]", m).forEach((b) => b.onclick = () => { const l = d.lines[+b.dataset.seek]; play(l.s, l.e + 0.3); });
    $$("[data-first]", m).forEach((b) => b.onclick = () => { st.first = +b.dataset.first; if (st.last == null) st.last = st.first; pick(st.first, "last"); });
    $$("[data-last]", m).forEach((b) => b.onclick = () => { st.last = +b.dataset.last; if (st.first == null) st.first = st.last; pick(st.last, "first"); });
    summary();
  };
  const summary = () => {
    const r = range();
    if (!r) { $("#qqPick", m).innerHTML = `<p class="small muted" style="margin:12px 0 0">Pick a first line and a last line (they can be the same).</p>`; $("#qqGo", m).disabled = true; $("#qqStatus", m).textContent = ""; return; }
    const a = d.lines[r[0]], b = d.lines[r[1]], len = b.e - a.s;
    const bad = len < 3 ? "A short needs at least 3 seconds: pick a later last line." : len > 180 ? "A short can be at most 3 minutes: pick an earlier last line." : "";
    if (!st.typed) st.title = defaultTitle(a);
    $("#qqPick", m).innerHTML = `<div class="qq-sel"><div class="row between"><b>${fmtT(a.s)} to ${fmtT(b.e)}</b><span class="num small muted">${len.toFixed(1)} s</span></div>
      <p class="small muted break" style="margin:6px 0 0">“${esc(a.text.length > 90 ? a.text.slice(0, 90) + "…" : a.text)}”${r[1] > r[0] ? ` … “${esc(b.text.length > 70 ? "…" + b.text.slice(-70) : b.text)}”` : ""}</p>
      ${d.source ? `<button type="button" class="btn sm" id="qqPlay" style="margin-top:10px">${icon("play")} Play It</button>` : ""}
      <div style="margin-top:12px"><div class="lbl"><label for="qqTitle">Title on the short</label></div><input class="input" id="qqTitle" type="text" maxlength="100" autocomplete="off" value="${esc(st.title)}"></div>
      ${PRESETS.length ? `<div style="margin-top:10px"><div class="lbl"><label for="qqPreset">Style</label></div><select class="input" id="qqPreset">${presetOptions(st.preset, "Your settings")}</select></div>` : ""}
      ${bad ? `<p class="err-text small" style="margin:8px 0 0">${bad}</p>` : ""}</div>`;
    $("#qqPlay", m)?.addEventListener("click", () => play(a.s, b.e + 0.3));
    $("#qqTitle", m).oninput = (e) => { st.title = e.target.value; st.typed = true; };
    $("#qqPreset", m)?.addEventListener("change", (e) => { st.preset = e.target.value; });
    if (!st.busy) { $("#qqGo", m).disabled = !!bad || !canMake; $("#qqStatus", m).textContent = bad ? "" : "Ready to make"; }
  };
  // a search finds one end; the other end rarely has the same word, so show every line again around the pick
  const pick = (n, other) => {
    const searching = !!st.q.trim();
    if (searching) { st.q = ""; $("#qqFind", m).value = ""; }
    draw();
    if (v && v.paused) v.currentTime = d.lines[n].s;                       // the preview shows that moment
    const row = $(`.ql[data-n="${n}"]`, m), box = $("#qqLines", m);
    if (searching && row && box) {
      box.scrollTop = Math.max(0, row.offsetTop - box.offsetTop - 60);
      $("#qqCount", m).textContent = `Showing every line again. Pick the ${other} line.`;
    }
  };
  $("#qqFind", m).oninput = (e) => { st.q = e.target.value; draw(); };
  $("#qqGo", m).onclick = async () => {
    const r = range(); if (!r) return;
    st.busy = true; $("#qqGo", m).disabled = true;
    $("#qqStatus", m).innerHTML = `<div class="bar wait"><i style="width:0%"></i></div><span class="faint">Waiting in line…</span>`;
    let job;
    try { job = await api.post(`/api/transcript/${encodeURIComponent(video)}/clip`, {i0: d.lines[r[0]].i0, i1: d.lines[r[1]].i1, title: st.title.trim(), preset: st.preset}); }
    catch (e) { st.busy = false; summary(); $("#qqStatus", m).innerHTML = `<span class="err-text">${esc(e.message)}</span>`; return; }
    const t = setInterval(async () => {
      let j; try { j = await api.get("/api/jobs/" + job.id); } catch { return; }
      const open = document.body.contains(m);
      if (j.state === "done") {
        clearInterval(t); st.busy = false; after(); refreshGlobal();
        toast("Clip ready. It's in the Library too.");
        if (!open) return;
        $("#qqDone", m).innerHTML = `<div class="clips" style="margin-top:14px">${j.result.clips.map(clipCard).join("")}</div>`;
        bindCopy($("#qqDone", m)); bindFix($("#qqDone", m), after);
        st.first = st.last = null; st.typed = false; draw();
        $("#qqStatus", m).textContent = "Made. Pick other lines for another clip.";
        return;
      }
      if (j.state === "error" || j.state === "cancelled") {
        clearInterval(t); st.busy = false;
        if (open) { summary(); $("#qqStatus", m).innerHTML = `<span class="err-text">${esc(j.error || "Cancelled")}</span>`; } else toast(j.error || "Cancelled", "bad");
        return;
      }
      if (open) $("#qqStatus", m).innerHTML = `<div class="bar ${j.state === "queued" ? "wait" : ""}"><i style="width:${Math.round((j.pct || 0) * 100)}%"></i></div><span class="faint">${esc(j.msg || "Rendering…")}</span>`;
    }, 1000);
  };
  draw();
  $("#qqFind", m).focus();
}

// ═════════════════════════ LIBRARY ═════════════════════════
pages.library = async (el) => {
  el.innerHTML = `<div class="ph"><div><h1>Library</h1><p>Every video you've clipped, and the space it takes. Open one to see its shorts.</p></div></div><div id="libStore"></div><div id="libOut" class="sec"></div>`;
  const load = async () => {
    const [items, st] = await Promise.all([api.get("/api/library"), api.get("/api/storage")]);
    if (!$("#libStore")) return;
    const byId = Object.fromEntries(st.projects.map((p) => [p.id, p]));
    const pct = (b) => st.total ? Math.max(b ? 0.5 : 0, (b / st.total) * 100) : 0;
    $("#libStore").innerHTML = `<section class="panel"><div class="store"><div>
        <div class="row between" style="margin-bottom:12px"><h2 style="margin:0">Storage</h2><span class="num">${fmtBytes(st.total)} used</span></div>
        <div class="stbar" role="img" aria-label="${fmtBytes(st.sources)} of downloads and ${fmtBytes(st.clips)} of shorts"><i class="src" style="width:${pct(st.sources)}%"></i><i class="clp" style="width:${pct(st.clips)}%"></i></div>
        <div class="legend"><span><i style="background:#9ea2ad"></i>Downloaded videos: ${fmtBytes(st.sources)}</span><span><i style="background:var(--yellow)"></i>Your shorts: ${fmtBytes(st.clips)}</span></div></div>
      <button type="button" class="btn" id="libClean" ${st.sources ? "" : "disabled"}>${icon("trash")} Delete All Downloads</button></div>
      <p class="small faint" style="margin:10px 0 0">Downloads are only needed to re-edit a video, and Clippy downloads them again if you do. Your shorts are kept.</p></section>`;
    $("#libClean").onclick = async () => {
      if (!await confirmDialog({title: `Delete all downloads (${fmtBytes(st.sources)})?`, body: "Your shorts, transcripts and AI picks are kept. Re-editing a video downloads it again.", confirm: "Delete Downloads", danger: true})) return;
      try { const r = await api.post("/api/storage/cleanup", {days: 0}); toast(`Freed ${fmtBytes(r.freed)}`); load(); } catch (e) { fail(e); }
    };
    const withClips = new Set(items.map((it) => it.id));
    const others = st.projects.filter((p) => !withClips.has(p.id));
    if (!items.length && !others.length) { $("#libOut").innerHTML = emptyState("grid", "No clips yet", "Videos you clip show up here.", `<a class="btn primary" href="#make">${icon("scissors")} Make Clips</a>`); return; }
    const card = (it) => {
      const sz = byId[it.id];
      return `<article class="panel libcard"><button type="button" class="libopen" data-open="${esc(it.id)}">
        <span class="thumbs">${it.clips.slice(0, 2).map((c) => `<img src="/media/${encodeURI(c.thumb)}" alt="" width="44" height="78" loading="lazy">`).join("")}</span>
        <div><b>${esc(it.title)}</b><small>${it.clips.length} shorts${it.uploader ? `, ${esc(it.uploader)}` : ""}<br>${fmtDate(it.created)}${sz ? `, ${fmtBytes(sz.total)}` : ""}</small></div></button>
        <div class="row">${sz?.has_source ? `<button type="button" class="btn sm" data-src="${esc(it.id)}">Delete Download (${fmtBytes(sz.source_bytes)})</button>` : ""}
          <button type="button" class="btn sm quiet danger" data-delp="${esc(it.id)}" data-name="${esc(it.title)}">${icon("trash")} Delete</button></div></article>`;
    };
    $("#libOut").innerHTML = `<div class="libgrid">${items.map(card).join("")}</div>
      ${others.length ? `<div class="sec"><div class="sec-head"><h2>Other downloads</h2><span>Videos without finished shorts, for example cancelled jobs</span></div>
        <section class="panel" style="padding:6px 18px"><div class="rows">${others.map((p) => `<div class="rowi"><div class="t"><b>${esc(p.title)}</b><small class="num">${fmtBytes(p.total)}, last used ${rel(p.modified)}</small></div>
          <button type="button" class="btn sm quiet danger" data-delp="${esc(p.id)}" data-name="${esc(p.title)}">${icon("trash")} Delete</button></div>`).join("")}</div></section></div>` : ""}`;
    $$("[data-open]").forEach((b) => b.onclick = () => {
      const it = items.find((x) => x.id === b.dataset.open);
      const m = openModal(`<div class="mh"><div class="row between"><h2 class="break">${esc(it.title)}</h2><button type="button" class="btn quiet icon" data-close aria-label="Close">${icon("x")}</button></div>
        <p class="muted small" style="margin:4px 0 12px">${it.clips.length} shorts. <a href="${esc(it.url)}" target="_blank" rel="noopener">Open the source video</a></p>
        ${it.mode !== "visual" ? `<button type="button" class="btn sm" data-quote="${esc(it.id)}" style="margin-bottom:12px">${icon("search")} Find a Quote</button>` : ""}</div>
        <div class="mb"><div class="clips">${it.clips.map(clipCard).join("")}</div></div>`, {label: it.title});
      $("[data-close]", m).onclick = () => closeModal(); bindCopy(m); bindFix(m, () => load());
      $("[data-quote]", m)?.addEventListener("click", () => openQuote(it.id, {after: () => load()}));
    });
    $$("[data-src]").forEach((b) => b.onclick = async () => {
      try { const r = await api.post(`/api/storage/${encodeURIComponent(b.dataset.src)}/source/delete`); toast(`Freed ${fmtBytes(r.freed)} — your shorts are kept`); load(); } catch (e) { fail(e); }
    });
    $$("[data-delp]").forEach((b) => b.onclick = async () => {
      if (!await confirmDialog({title: `Delete “${b.dataset.name}”?`, body: "This removes the download, transcript and every short made from it. It can't be undone.", confirm: "Delete Everything", danger: true})) return;
      try { const r = await api.del(`/api/storage/${encodeURIComponent(b.dataset.delp)}`); toast(`Deleted, freed ${fmtBytes(r.freed)}`); load(); refreshGlobal(); } catch (e) { fail(e); }
    });
    hydrateIcons(el);
  };
  await load();
};

// ═════════════════════════ AI & TOOLS ═════════════════════════
pages.ai = async (el) => {
  el.innerHTML = `<div class="ph"><div><h1>AI and tools</h1><p>Everything Clippy downloads stays in its own folder. Uninstall Clippy and all of it goes too.</p></div></div>
    <div id="aiBanner"></div>
    <section class="panel">
      <div class="row between aihead" style="gap:12px;flex-wrap:wrap"><div><h2>AI model</h2><p class="sub">Reads the transcript and picks the moments worth posting. Bigger models pick better.</p></div>
        <div class="seg" id="aiMode" role="radiogroup" aria-label="Which AI to use">
          <button type="button" role="radio" data-v="auto">Automatic</button><button type="button" role="radio" data-v="builtin">Built-in</button><button type="button" role="radio" data-v="external">Another App</button></div></div>
      <p class="small muted" id="aiModeNote" style="margin:10px 0 0"></p>
      <div class="rows models" id="aiList"></div>
      <form class="row" id="aiAdd" style="gap:8px;margin-top:14px"><input class="input" id="aiUrl" type="url" autocomplete="off" spellcheck="false" aria-label="Hugging Face link to a .gguf file" placeholder="Add any model: paste a Hugging Face link to a .gguf file…"><button class="btn">${icon("plus")} Add</button></form>
    </section>
    <section class="panel"><h2>Tools</h2><p class="sub">The parts that turn a video into shorts.</p><div class="rows" id="aiParts"></div></section>
    <section class="panel"><h2>Space used</h2><p class="sub" id="aiFolder"></p><div class="space" id="aiSpace"></div></section>`;
  hydrateIcons(el);
  let last = null;
  const pct = (t) => t && t.total ? Math.round(100 * t.done / t.total) : null;
  const progress = (t) => t && t.state === "running"
    ? `<div class="prog"><div class="bar ${pct(t) == null ? "wait" : ""}"><i style="width:${pct(t) ?? 0}%"></i></div><span class="small muted num">${t.step ? esc(t.step) : pct(t) != null ? `${fmtBytes(t.done)} of ${fmtBytes(t.total)}` : "Working…"}</span></div>` : "";
  const failed = (t) => t && t.state === "failed" ? `<span class="err-text">${esc(t.error)}</span>` : "";
  const draw = (s) => {
    last = s;
    $$("#aiMode button").forEach((b) => { const on = b.dataset.v === s.mode; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
    $("#aiModeNote").textContent = {auto: "Uses the built-in AI when a model is downloaded, otherwise an AI app that's running on this PC (Ollama, LM Studio…).",
      builtin: "Always uses the built-in AI and the model marked In Use.", external: "Uses an AI app running on this PC, like Ollama or LM Studio. See Settings for which one."}[s.mode];
    const ev = s.everything;
    $("#aiBanner").innerHTML = s.missing.length || (ev && ev.state === "running")
      ? `<section class="setup-banner"><div><b>${ev && ev.state === "running" ? `Setting up: ${esc(ev.label)}` : "Clippy needs a few things before it can make clips"}</b>
          <p>${ev && ev.state === "running" ? "You can keep using Clippy while this downloads." : `One button gets everything that fits this PC${s.missing.includes("ai") ? `, including the ${esc(s.models.find((m) => m.recommended)?.name || "")} AI model` : ""}.`}</p>
          ${progress(ev)}${failed(ev)}</div>
          ${ev && ev.state === "running" ? `<button type="button" class="btn quiet" data-cancel="everything">${icon("x")} Stop</button>` : `<button type="button" class="btn primary" id="aiAll">${icon("download")} Set Up Everything</button>`}</section>` : "";
    $("#aiList").innerHTML = s.models.map((m) => {
      const t = m.task, busy = t && t.state === "running";
      const tags = [m.active ? `<span class="tag ok">${icon("check")} In use</span>` : "", m.recommended && !m.installed ? `<span class="tag your">Best fit for this PC</span>` : "",
        !m.fits ? `<span class="tag">Too big for this PC</span>` : ""].join("");
      const act = busy ? `<button type="button" class="btn sm quiet" data-cancel="${esc(t.id)}">${icon("x")} Cancel</button>`
        : !m.installed ? `<button type="button" class="btn sm ${m.recommended ? "primary" : ""}" data-get="${esc(m.id)}">${icon("download")} Download</button>`
        : `${m.active ? "" : `<button type="button" class="btn sm" data-use="${esc(m.file)}">Use</button>`}<button type="button" class="btn sm quiet" data-del="${esc(m.file)}" aria-label="Delete ${esc(m.name)}">${icon("trash")}</button>`;
      return `<div class="rowi model ${m.active ? "on" : ""}"><div class="t"><b>${esc(m.name)} ${tags}</b><small>${esc(m.about)} <span class="num">${m.gb} GB</span>${m.page ? ` <a href="${esc(m.page)}" target="_blank" rel="noopener">Model page</a>` : ""}</small>${progress(t)}${failed(t)}</div><div class="acts">${act}</div></div>`;
    }).join("");
    $("#aiParts").innerHTML = s.components.map((c) => {
      const t = c.task, busy = t && t.state === "running";
      const right = busy ? `<button type="button" class="btn sm quiet" data-cancel="${esc(c.id)}">${icon("x")} Cancel</button>`
        : c.installed ? `<span class="tag ok">${icon("check")} Ready</span>${c.removable ? `<button type="button" class="btn sm quiet" data-rm="${esc(c.id)}" aria-label="Remove ${esc(c.name)}">${icon("trash")}</button>` : ""}`
        : `<button type="button" class="btn sm" data-part="${esc(c.id)}">${icon("download")} Download <span class="num faint">${fmtBytes(c.size)}</span></button>`;
      return `<div class="rowi"><div class="ic ${c.installed ? "ok" : ""}">${icon(c.installed ? "checkCircle" : "download")}</div><div class="t"><b>${esc(c.name)}</b><small>${esc(c.about)} ${esc(c.detail)}</small>${progress(t)}${failed(t)}</div><div class="acts">${right}</div></div>`;
    }).join("");
    $("#aiFolder").textContent = `All in ${s.folder}`;
    $("#aiSpace").innerHTML = [["AI and speech models", s.space.models], ["Tools and AI engine", s.space.tools], ["Your videos and shorts", s.space.clips]]
      .map(([n, b]) => `<div><span class="small muted">${n}</span><b class="num">${fmtBytes(b)}</b></div>`).join("");
    hydrateIcons(el);
  };
  const load = async () => { try { draw(await api.get("/api/setup")); } catch (e) { fail(e); } };
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); } catch (e) { fail(e); } await load(); };
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b || !el.contains(b)) return;
    if (b.id === "aiAll") return act(() => api.post("/api/setup/install", {id: "everything"}), "Setting up. You can keep using Clippy meanwhile.");
    if (b.dataset.v && b.closest("#aiMode")) return act(() => api.post("/api/setup/mode", {mode: b.dataset.v}));
    if (b.dataset.get) return act(() => api.post("/api/setup/install", {id: "model:" + b.dataset.get}));
    if (b.dataset.part) return act(() => api.post("/api/setup/install", {id: b.dataset.part}));
    if (b.dataset.cancel) return act(() => api.post("/api/setup/cancel", {id: b.dataset.cancel}), "Stopped. It continues where it left off next time.");
    if (b.dataset.use) return act(() => api.post("/api/setup/use", {file: b.dataset.use}), "Clippy will use this model from the next video on");
    if (b.dataset.del) {
      const m = last?.models.find((x) => x.file === b.dataset.del);
      if (await confirmDialog({title: `Delete ${m?.name || "this model"}?`, body: `This frees ${m?.gb ?? "?"} GB. You can download it again any time.`, confirm: "Delete Model", danger: true}))
        return act(() => api.post("/api/setup/remove", {file: b.dataset.del}), "Model deleted");
    }
    if (b.dataset.rm) {
      const c = last?.components.find((x) => x.id === b.dataset.rm);
      if (await confirmDialog({title: `Remove ${c?.name || "this part"}?`, body: "Clippy can download it again whenever it's needed.", confirm: "Remove", danger: true}))
        return act(() => api.post("/api/setup/remove", {id: b.dataset.rm}), "Removed");
    }
  });
  $("#aiAdd").onsubmit = (e) => { e.preventDefault(); const url = $("#aiUrl").value.trim(); if (!url) return;
    act(async () => { await api.post("/api/setup/install", {url}); $("#aiUrl").value = ""; }, "Downloading your model"); };
  await load();
  repeat(1500, () => { const busy = last && (last.everything?.state === "running" || last.models.some((m) => m.task?.state === "running") || last.components.some((c) => c.task?.state === "running")); if (busy) load(); });
  repeat(15000, load);
};

// ═════════════════════════ EXTENSIONS ═════════════════════════
const MAKE_YOUR_OWN = "https://github.com/StormAmdam/clippy/blob/main/docs/extensions.md";
pages.ext = async (el) => {
  el.innerHTML = `<div class="ph"><div><h1>Extensions</h1><p>Caption styles, countdown themes, sound effects and more that other people made. They live in Clippy's folder, so uninstalling Clippy removes them too.</p></div>
      <a class="btn quiet" href="${MAKE_YOUR_OWN}" target="_blank" rel="noopener">${icon("external")} Make Your Own</a></div>
    <section class="panel"><h2>Installed</h2><p class="sub" id="xFolder">What you have, and whether it's switched on</p><div class="rows" id="xMine"></div></section>
    <section class="panel"><h2>Community</h2><p class="sub">Made for Clippy and checked before they were listed</p>
      <p class="small muted hidden" id="xNote" style="margin:10px 0 0"></p><div class="rows" id="xCat"><p class="small muted">Loading the community list…</p></div></section>
    <section class="panel"><h2>Install from a link</h2><p class="sub">A GitHub repository or a link to a .zip file. Only install extensions from people you trust.</p>
      <form class="row" id="xAdd" style="gap:8px;margin-top:12px"><input class="input" id="xUrl" type="url" autocomplete="off" spellcheck="false" aria-label="Link to an extension" placeholder="https://github.com/someone/their-clippy-extension"><button class="btn">${icon("download")} Install</button></form></section>`;
  const adds = (a) => (a || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
  const meta = (x) => [x.version && "v" + x.version, x.author && "by " + x.author].filter(Boolean).join(", ");
  const codeTag = (on) => on ? `<span class="tag you">${icon("code")} Runs code</span>` : "";
  const after = async (msg) => { state.niches = null; await loadLooks(); toast(msg); await draw(); };   // new topics, looks, themes
  const draw = async () => {
    let mine; try { mine = await api.get("/api/extensions"); } catch (e) { $("#xMine").innerHTML = `<p class="small">${esc(e.message)}</p>`; return; }
    $("#xFolder").textContent = `In ${mine.folder}`;
    $("#xMine").innerHTML = mine.installed.length ? mine.installed.map((x) => `<div class="rowi model"><div class="ic ${x.enabled ? "ok" : ""}">${icon("puzzle")}</div>
      <div class="t"><b>${esc(x.name)} <span class="small muted" style="font-weight:400">${esc(meta(x))}</span></b>
        <small>${x.error ? `<span class="err-text">${esc(x.error)}</span>` : esc(x.description)}</small><div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px">${codeTag(x.code)}${adds(x.adds)}</div></div>
      <div class="acts row" style="gap:8px">${x.error ? "" : `<label class="switch" style="padding:6px 10px"><span class="txt"><small>${x.enabled ? "On" : "Off"}</small></span><input type="checkbox" data-on="${esc(x.id)}" ${x.enabled ? "checked" : ""} aria-label="Switch ${esc(x.name)} on or off"></label>`}
        <button type="button" class="btn sm quiet" data-rm="${esc(x.id)}" aria-label="Remove ${esc(x.name)}">${icon("trash")}</button></div></div>`).join("")
      : `<p class="small muted">None yet. Pick some from the community list below.</p>`;
    $$("[data-on]", el).forEach((cb) => cb.onchange = async () => {
      const x = mine.installed.find((r) => r.id === cb.dataset.on), on = cb.checked;
      let trust = false;
      if (on && x.code && !x.trusted) {
        trust = await confirmDialog({title: "This extension runs its own code", danger: true, confirm: "Trust and Switch On",
          body: `“${esc(x.name)}”${x.author ? ` by ${esc(x.author)}` : ""} can do anything on this computer, like any program you install. Only switch it on if you trust who made it.`});
        if (!trust) { cb.checked = false; return; }
      }
      try { await api.post(`/api/extensions/${encodeURIComponent(x.id)}/enable`, {on, trust}); await after(on ? `${x.name} is on` : `${x.name} is off`); }
      catch (e) { cb.checked = !on; fail(e); }
    });
    $$("[data-rm]", el).forEach((b) => b.onclick = async () => {
      const x = mine.installed.find((r) => r.id === b.dataset.rm);
      if (!await confirmDialog({title: `Remove ${esc(x.name)}?`, confirm: "Remove", danger: true, body: "You can install it again any time."})) return;
      try { await api.del(`/api/extensions/${encodeURIComponent(x.id)}`); await after(`${x.name} removed`); } catch (e) { fail(e); }
    });
    let cat; try { cat = await api.get("/api/extensions/catalog"); } catch (e) { $("#xCat").innerHTML = `<p class="small">${esc(e.message)}</p>`; return; }
    $("#xNote").textContent = cat.note || ""; $("#xNote").classList.toggle("hidden", !cat.note);
    $("#xCat").innerHTML = cat.items.length ? cat.items.map((x) => `<div class="rowi model"><div class="ic">${icon("puzzle")}</div>
      <div class="t"><b>${esc(x.name)} <span class="small muted" style="font-weight:400">${esc(meta(x))}</span></b>
        <small>${esc(x.description)}</small><div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px">${codeTag(x.code)}${adds(x.adds)}</div></div>
      <div class="acts">${x.installed && !x.update ? `<span class="tag ok">${icon("check")} Installed</span>`
        : `<button type="button" class="btn sm ${x.update ? "" : "primary"}" data-get="${esc(x.id)}">${icon("download")} ${x.update ? "Update" : "Install"}</button>`}</div></div>`).join("")
      : `<p class="small muted">The community list is empty right now.</p>`;
    $$("[data-get]", el).forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try { const r = await api.post("/api/extensions/install", {id: b.dataset.get}); await after(r.code && !r.enabled ? `Installed ${r.name}. It runs code, so switch it on when you trust it.` : `Installed ${r.name}`); }
      catch (e) { b.disabled = false; fail(e); }
    });
  };
  $("#xAdd").onsubmit = async (e) => {
    e.preventDefault();
    const url = $("#xUrl").value.trim(); if (!url) return;
    const btn = $("#xAdd button"); btn.disabled = true;
    try { const r = await api.post("/api/extensions/install", {url}); $("#xUrl").value = ""; await after(r.code && !r.enabled ? `Installed ${r.name}. It runs code, so switch it on when you trust it.` : `Installed ${r.name}`); }
    catch (err) { fail(err); } finally { btn.disabled = false; }
  };
  await draw();
};

// ═════════════════════════ SETTINGS ═════════════════════════
// themes: the stylesheet and browser-bar colour of each (the server puts the saved one in the page from the start)
const UI_THEMES = [["caption", "Caption print", "Bold titles set like the captions in your shorts, sticker buttons, deep navy"],
  ["classic", "Classic", "The original look: calm grey panels and a yellow accent"]];
const THEME_FILES = {caption: ["/static/app.css", "#0f1320"], classic: ["/static/themes/classic.css", "#1b1c21"]};
function applyTheme(v) {
  const [css, colour] = THEME_FILES[v] || THEME_FILES.caption;
  const link = $("link[data-theme-css]");
  if (link && !link.href.endsWith(css)) link.href = css;
  $('meta[name="theme-color"]')?.setAttribute("content", colour);
}
// a small picture of each theme, drawn the same whichever one is on
const themeSample = (v) => v === "classic"
  ? `<span aria-hidden="true" style="display:block;position:relative;height:96px;margin-bottom:10px;border-radius:10px;overflow:hidden;background:#1b1c21;border:1px solid #34363e">
      <span style="position:absolute;left:14px;top:12px;font:600 26px/1 'Barlow Condensed',sans-serif;color:#ececef">Make clips</span>
      <span style="position:absolute;left:14px;bottom:14px;width:46%;height:24px;border-radius:8px;background:#2a2c32;border:1px solid #42454e"></span>
      <span style="position:absolute;right:14px;bottom:14px;padding:5px 11px;border-radius:8px;background:#ffe135;color:#1a1705;font:600 12.5px/1.2 Barlow,sans-serif">Make Clips</span></span>`
  : `<span aria-hidden="true" style="display:block;position:relative;height:96px;margin-bottom:10px;border-radius:12px;overflow:hidden;background:#0f1320;border:2px solid #232a3d;
      background-image:radial-gradient(circle,rgba(255,225,53,.18) 1px,transparent 1.5px);background-size:8px 8px">
      <span style="position:absolute;left:14px;top:12px;display:inline-block;transform:rotate(-2deg);font:400 25px/1 'Luckiest Guy',sans-serif;color:#f4f6fb;
        -webkit-text-stroke:6px #05070c;paint-order:stroke fill;text-shadow:2px 4px 0 #ffe135">MAKE CLIPS</span>
      <span style="position:absolute;left:14px;bottom:14px;width:46%;height:24px;border-radius:10px;background:#0b0e18;border:2px solid #2f3851"></span>
      <span style="position:absolute;right:14px;bottom:16px;padding:4px 10px;border-radius:9px;background:#ffe135;color:#1a1705;border:2px solid #05070c;
        box-shadow:0 3px 0 #05070c;font:700 12.5px/1.2 Barlow,sans-serif">Make Clips</span></span>`;

pages.settings = async (el) => {
  const [s, auto] = await Promise.all([api.get("/api/settings"), api.get("/api/autostart").catch(() => ({supported: false}))]);
  const orig = {...s}, cur = {...s};
  const win = auto.how === "windows" || auto.how === "windows-source" || state.status?.os === "windows";
  const autoOff = win ? "Off: Clippy runs while its window is open." : "Off: start it yourself with clippy web.";
  let keyTyped = "";
  const sel = (k, val, opts) => `<select class="input" id="s-${k}" data-k="${k}">${opts.map(([v, l]) => `<option value="${v}" ${String(val) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  el.innerHTML = `<div class="ph"><div><h1>Settings</h1><p>These apply to everything new you make. A single video's options still win.</p></div></div>
    <section class="panel" style="padding-top:4px;padding-bottom:16px">
      <div class="set"><div><b>Theme</b><p>How Clippy looks. It changes straight away, here and in every window.</p></div>
        <div class="choices wide" id="sTheme" role="radiogroup" aria-label="Theme">${UI_THEMES.map(([v, n, d]) => `<button type="button" role="radio" aria-checked="${(s.ui_theme || "caption") === v}"
          class="choice ${(s.ui_theme || "caption") === v ? "on" : ""}" data-theme="${v}"><span class="tick" style="z-index:1">${icon("check")}</span>${themeSample(v)}<b>${n}</b><small>${d}</small></button>`).join("")}</div></div>
      <div class="set"><div><b>Saved styles</b><p>Named looks for Make Clips, Find a Quote and Autopilot channels. Save one from Make Clips.</p></div>
        <div id="sPresets">${PRESETS.length ? `<div class="rows">${PRESETS.map((pr) => `<div class="rowi"><div class="t"><b>${esc(pr.name)}</b><small>${esc(STYLES.find((x) => x[0] === pr.settings.caption_style)?.[1] || pr.settings.caption_style)} captions, ${pr.settings.teaser ? "teaser" : "no teaser"}, ${pr.settings.sfx ? "sound effects" : "no sound effects"}</small></div>
          <button type="button" class="btn sm quiet danger" data-delpreset="${esc(pr.id)}" data-name="${esc(pr.name)}">${icon("trash")} Delete</button></div>`).join("")}</div>` : `<p class="muted">None yet.</p>`}</div></div>
      <div class="set"><div><b>Watch a recording folder</b><p>New recordings that land there become shorts by themselves, for example from OBS. Recordings already there are left alone. Clippy needs to be running.</p></div>
        <div class="stack"><label class="field"><span>Folder</span><input class="input" data-k="watch_folder" type="text" autocomplete="off" spellcheck="false" value="${esc(s.watch_folder || "")}" placeholder="${win ? "C:\\Users\\you\\Videos\\OBS" : "/home/you/Videos/OBS"} (empty: don't watch)"></label>
          <label class="field"><span>Make them with</span><select class="input" data-k="watch_preset">${presetOptions(s.watch_preset, "Your settings")}</select></label>
          <div class="small muted" id="sWatch" aria-live="polite"></div></div></div>
      <div class="set"><div><b>Updates</b><p id="sVersion">You have Clippy ${esc(state.version || "")}.</p></div>
        <div class="stack"><label class="switch"><span class="ic">${icon("refresh")}</span><span class="txt"><b>Check for updates when Clippy opens</b><small>It asks GitHub for a newer version and tells you. It never updates without you.</small></span><input type="checkbox" data-k="check_updates" ${s.check_updates ? "checked" : ""}></label>
          <div class="row"><button type="button" class="btn sm" id="sCheck">${icon("refresh")} Check Now</button><span class="small muted" id="sCheckNote"></span></div></div></div>
      <div class="set"><div><b>Start at login</b><p>${win ? "Keeps Clippy running in the background, also after you close its window, so scheduled Autopilot runs happen. Open Clippy as usual to see it." : "Keeps Clippy running in the background so scheduled Autopilot runs happen even when no terminal is open."}</p></div>
        <div>${auto.supported ? `<label class="switch"><span class="ic">${icon("power")}</span><span class="txt"><b>Start Clippy when you log in</b><small id="autoNote">${auto.enabled ? "On: Clippy starts automatically at login." : autoOff}</small></span><input type="checkbox" id="autoSw" ${auto.enabled ? "checked" : ""}></label>`
          : `<p class="muted">${auto.how === "windows-source" ? "Available in the Clippy app for Windows." : win ? "Not available here." : "Not available on this system. It needs systemd."}</p>`}
          ${auto.can_quit ? `<div class="row" style="gap:10px;margin-top:12px"><button type="button" class="btn sm quiet" id="quitApp">${icon("power")} Quit Clippy</button><span class="small muted">Stops Clippy until you open it again${auto.enabled ? " or log in" : ""}.</span></div>` : ""}</div></div>
      <div class="set"><div><b>AI that picks the clips</b><p>Clippy uses its built-in AI (AI &amp; Tools), or finds llama.cpp, Ollama, LM Studio, Jan, KoboldCpp or vLLM by itself${win ? "" : ", on this computer or on Windows when you use WSL"}. Choose a server or model here only if you want a specific one.</p></div>
        <div class="stack"><div class="aibox" id="aiBox" aria-live="polite"><span class="small muted">Looking for AI servers…</span></div>
          <label class="field"><span>Server address (auto finds one by itself)</span><input class="input" data-k="llm_url" autocomplete="off" spellcheck="false" value="${esc(s.llm_url)}" placeholder="auto"></label>
          <label class="field"><span>Model (empty: the one already loaded, or your newest download)</span><input class="input" data-k="llm_model" list="aiModels" autocomplete="off" spellcheck="false" value="${esc(s.llm_model)}" placeholder="qwen3.5:9b…"><datalist id="aiModels"></datalist></label>
          <label class="field"><span>API key (only for cloud services like Groq or Gemini)</span><input class="input" type="password" id="apiKey" autocomplete="off" placeholder="${s.has_llm_api_key ? "Saved. Type a new key to replace it…" : "gsk_…"}"></label>
          <label class="switch"><span class="ic">${icon("sparkles")}</span><span class="txt"><b>Let the AI think first</b><small>Slower, sometimes smarter picks</small></span><input type="checkbox" data-k="llm_thinking" ${s.llm_thinking ? "checked" : ""}></label></div></div>
      <div class="set"><div><b>Graphics card</b><p>Whisper needs about 2.6 GB of graphics memory. When the AI is holding it, Clippy pauses its built-in AI${win ? "" : " or the AI service named below"}, or asks Ollama to unload its model, and gives the memory back afterwards.</p></div>
        <div class="stack"><label class="switch"><span class="ic">${icon("zap")}</span><span class="txt"><b>Free the GPU for transcribing</b><small>About 10× faster transcription. Off means transcribing on the CPU when memory is short.</small></span><input type="checkbox" data-k="free_gpu_for_whisper" ${s.free_gpu_for_whisper ? "checked" : ""}></label>
          ${win ? "" : `<label class="field"><span>AI service name (systemd user service)</span><input class="input" data-k="llama_service" autocomplete="off" spellcheck="false" value="${esc(s.llama_service)}" placeholder="llama-coder…"></label>`}
          <label class="field"><span>Speech-to-text model</span>${sel("whisper_model", s.whisper_model, [["large-v3-turbo", "Large v3 Turbo (best)"], ["medium", "Medium (faster)"], ["small", "Small (fastest)"]])}</label></div></div>
      <div class="set"><div><b>New clips</b><p>The starting point on Make Clips and for new Autopilot channels.</p></div>
        <div class="stack"><div class="grid g3">
            <label class="field"><span>Clips per video</span><input class="input num" type="number" inputmode="numeric" min="1" max="12" data-k="clips" value="${s.clips}"></label>
            <label class="field"><span>Shortest (seconds)</span><input class="input num" type="number" inputmode="numeric" min="5" max="170" data-k="min_seconds" value="${s.min_seconds}"></label>
            <label class="field"><span>Longest (seconds)</span><input class="input num" type="number" inputmode="numeric" min="10" max="180" data-k="max_seconds" value="${s.max_seconds}"></label></div>
          <div class="grid g2"><label class="field"><span>Caption style</span>${sel("caption_style", s.caption_style, STYLES.map(([k, n]) => [k, esc(n)]))}</label>
            <label class="field"><span>Download quality</span>${sel("max_height", s.max_height, [[1080, "1080p (smaller files)"], [1440, "1440p (recommended)"], [2160, "4K (sharpest, big files)"]])}</label></div>
          <label class="switch"><span class="ic">${icon("music")}</span><span class="txt"><b>Voice polish</b><small>Trims low rumble and evens out loudness so voices sound clear on phones</small></span><input type="checkbox" data-k="voice_polish" ${s.voice_polish ? "checked" : ""}></label></div></div>
      <div class="set"><div><b>Storage</b><p>Downloaded videos take the most space and are only needed to re-edit.</p></div>
        <div><label class="field"><span>Delete downloaded videos automatically</span>${sel("auto_cleanup_days", s.auto_cleanup_days, [[0, "Never"], [3, "After 3 days without use"], [7, "After 7 days without use"], [14, "After 14 days without use"], [30, "After 30 days without use"]])}</label>
          <div class="hint">Your shorts are never deleted automatically.</div></div></div>
      <div class="row" style="justify-content:flex-end;padding-top:16px;border-top:1px solid var(--line)"><span class="small faint" id="setState" aria-live="polite"></span><button type="button" class="btn primary" id="setSave" disabled>Save Changes</button></div>
    </section>`;
  const dirty = () => Boolean(keyTyped) || Object.keys(cur).some((k) => String(cur[k]) !== String(orig[k]));
  const mark = () => { $("#setSave").disabled = !dirty(); $("#setState").textContent = dirty() ? "Unsaved changes" : ""; };
  leaveGuard = dirty;
  $$("[data-k]", el).forEach((inp) => {
    const k = inp.dataset.k;
    const read = () => inp.type === "checkbox" ? inp.checked : inp.type === "number" ? +inp.value : (inp.tagName === "SELECT" && typeof orig[k] === "number") ? +inp.value : inp.value;
    inp.addEventListener(inp.type === "checkbox" || inp.tagName === "SELECT" ? "change" : "input", () => { cur[k] = read(); mark(); });
  });
  $("#apiKey").oninput = (e) => { keyTyped = e.target.value; mark(); };
  const setField = (k, v) => { const inp = $(`[data-k="${k}"]`, el); inp.value = v; cur[k] = v; mark(); };
  const fillModels = (models) => { $("#aiModels").innerHTML = (models || []).map((m) => `<option value="${esc(m)}">`).join(""); };
  const showAI = async () => {
    const box = $("#aiBox");
    if (!box) return;
    box.innerHTML = `<span class="small muted">Looking for AI servers…</span>`;
    let r;
    try { r = await api.get("/api/ai"); } catch (e) { box.innerHTML = `<span class="small">${esc(e.message)}</span>`; return; }
    const u = r.using;
    const others = r.servers.filter((s) => !u || s.base !== u.base);
    box.innerHTML = (u
      ? `<div class="row" style="gap:10px"><span class="dot ok"></span><span>Using <b>${esc(u.model || "the loaded model")}</b> on ${esc(u.label)}${u.context ? `, ${u.context.toLocaleString()}-token context` : ""}</span></div>`
      : `<div class="row" style="gap:10px;align-items:flex-start"><span class="dot bad" style="margin-top:7px"></span><span class="small">${esc(r.error)}</span></div>`)
      + others.map((s, i) => `<div class="row between" style="gap:10px;margin-top:10px"><span class="small"><b>${esc(s.label)}</b><br><span class="muted">${esc(s.models.slice(0, 4).join(", ") || "No chat models")}</span></span><button type="button" class="btn sm" data-use="${i}">Use This</button></div>`).join("")
      + `<div class="row" style="gap:8px;margin-top:12px">${r.auto ? "" : `<button type="button" class="btn sm quiet" id="aiAuto">Find Automatically</button>`}<button type="button" class="btn sm quiet" id="aiAgain">Look Again</button></div>`;
    fillModels(u?.models);
    $$("[data-use]", box).forEach((b) => { b.onclick = () => { const s = others[+b.dataset.use]; setField("llm_url", s.base); setField("llm_model", ""); fillModels(s.models); toast(`Save to switch to ${s.label}`); }; });
    $("#aiAuto")?.addEventListener("click", () => { setField("llm_url", "auto"); toast("Save to let Clippy find the AI by itself"); });
    $("#aiAgain").onclick = showAI;
  };
  showAI();
  $("#setSave").onclick = async () => {
    const changes = {};
    for (const k of Object.keys(cur)) if (k !== "has_llm_api_key" && String(cur[k]) !== String(orig[k])) changes[k] = cur[k];
    if (keyTyped) changes.llm_api_key = keyTyped;
    $("#setSave").disabled = true;
    try { const saved = await api.post("/api/settings", changes); Object.assign(orig, saved); Object.assign(cur, saved); keyTyped = ""; $("#apiKey").value = ""; mark(); toast("Settings saved"); }
    catch (e) { fail(e); mark(); }
  };
  $$("#sTheme .choice").forEach((b) => b.onclick = async () => {
    const v = b.dataset.theme;
    if (v === (cur.ui_theme || "caption")) return;
    try { await api.post("/api/settings", {ui_theme: v}); } catch (err) { fail(err); return; }
    orig.ui_theme = cur.ui_theme = v;                 // saved already: not an unsaved change
    applyTheme(v);
    $$("#sTheme .choice").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    toast(`Theme: ${UI_THEMES.find((t) => t[0] === v)[1]}`);
  });
  api.get("/api/update").then((u) => { state.version = u.current; $("#sVersion") && ($("#sVersion").textContent = `You have Clippy ${u.current}.`); }).catch(() => {});
  api.get("/api/watch").then((w) => {
    const box = $("#sWatch"); if (!box) return;
    if (w.problem) { box.innerHTML = `<span class="err-text">${esc(w.problem)}</span>`; return; }
    if (!w.watching) { box.textContent = "Not watching a folder."; return; }
    box.innerHTML = `Watching this folder.${w.waiting.length ? ` Waiting for ${w.waiting.length} recording${w.waiting.length > 1 ? "s" : ""} to finish.` : ""}`
      + (w.recent.length ? `<br>Lately: ${w.recent.map((r) => `${esc(r.file)}${r.error ? ` (${esc(r.error)})` : ""}`).join(", ")}` : "");
  }).catch(() => {});
  $$("[data-delpreset]").forEach((b) => b.onclick = async () => {
    if (!await confirmDialog({title: `Delete the style “${b.dataset.name}”?`, body: "Shorts already made keep their look. Autopilot channels using it go back to their own caption style.", confirm: "Delete Style", danger: true})) return;
    try { await api.del(`/api/presets/${encodeURIComponent(b.dataset.delpreset)}`); await loadPresets(); toast("Style deleted"); route(); } catch (e) { fail(e); }
  });
  $("#sCheck").onclick = async () => {
    $("#sCheck").disabled = true; $("#sCheckNote").textContent = "Checking…";
    const u = await checkForUpdate(true);
    $("#sCheck").disabled = false;
    $("#sCheckNote").textContent = !u ? "Couldn't check right now." : u.error ? `Couldn't reach GitHub: ${u.error}` : u.newer ? `Clippy ${u.latest} is out.` : `You have the latest version (${u.current}).`;
  };
  $("#quitApp")?.addEventListener("click", async () => {
    const busy = state.status?.running || state.status?.queued;
    const yes = await confirmDialog({title: "Quit Clippy?", confirm: "Quit", danger: Boolean(busy),
      body: busy ? "A video is being made right now. Quitting stops it." : "Scheduled Autopilot runs wait until Clippy runs again."});
    if (!yes) return;
    try { await api.post("/api/quit"); } catch (err) { fail(err); return; }
    leaveGuard = null; timers.forEach(clearInterval); timers = []; clearInterval(globalTimer);
    document.body.innerHTML = `<div class="panel empty" style="margin:15vh auto;max-width:440px"><div class="ic">${icon("power")}</div><h3>Clippy has quit</h3><p>You can close this window. ${win ? "Open Clippy again from the Start menu." : "Start it again with clippy app."}</p></div>`;
    setTimeout(() => window.close(), 1500);
  });
  $("#autoSw")?.addEventListener("change", async (e) => {
    const on = e.target.checked;
    try { const r = await api.post("/api/autostart", {enabled: on}); $("#autoNote").textContent = r.enabled ? (win ? "On: Clippy starts at login, and keeps running after you close its window." : "On: Clippy starts automatically next time you log in.") : autoOff; toast(r.enabled ? "Clippy will start at login" : "Start at login turned off"); }
    catch (err) { e.target.checked = !on; fail(err); }
  });
};

// ───────────────────────── updates ─────────────────────────
// a light take on the release notes: headings and bold become bold, "- " lines become a list
function notesHtml(md) {
  const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  let out = "", list = false;
  for (const line of String(md || "").split(/\r?\n/)) {
    const li = line.match(/^\s*[-*] (.*)$/);
    if (li) { if (!list) { out += "<ul>"; list = true; } out += `<li>${inline(li[1])}</li>`; continue; }
    if (list) { out += "</ul>"; list = false; }
    const h = line.match(/^#+ (.*)$/);
    if (h) out += `<p style="margin:12px 0 4px"><b>${inline(h[1])}</b></p>`;
    else if (line.trim()) out += `<p style="margin:6px 0">${inline(line)}</p>`;
  }
  return out + (list ? "</ul>" : "");
}

function showUpdate(u) {
  if ($("#updModal")) return;
  const bg = document.createElement("div");
  bg.className = "modal-bg"; bg.id = "updModal";
  const action = u.can_install ? `<button type="button" class="btn primary" id="updGo">${icon("download")} Update Now</button>`
    : u.how === "install-line" ? `<button type="button" class="btn primary" id="updCopy">${icon("copy")} Copy the Install Line</button>`
    : `<a class="btn primary" href="${esc(u.url || u.releases)}" target="_blank" rel="noopener">${icon("external")} Open the Download Page</a>`;
  bg.innerHTML = `<div class="modal small" role="dialog" aria-modal="true" aria-labelledby="updT">
    <div class="mh"><h2 id="updT">Hey, there's a new update!</h2></div>
    <div class="mb"><p>Clippy <b>${esc(u.latest)}</b> is out, and you have ${esc(u.current)}. You don't have to update, but it's recommended.</p>
      ${u.how === "install-line" ? `<p class="small muted" style="margin:10px 0 6px">To update, run this in a terminal (it keeps your shorts and settings):</p><div class="aibox break" style="font:13px/1.5 ui-monospace,monospace">${esc(u.install_line)}</div>` : ""}
      ${u.can_install ? `<p class="small muted" style="margin:8px 0 0">It keeps your AI models, settings and shorts. Clippy closes while it updates and opens again by itself.</p>` : ""}
      ${u.notes ? `<div class="aibox small" style="margin-top:14px;max-height:240px;overflow:auto">${notesHtml(u.notes)}</div>` : ""}
      <div id="updProg" class="hidden" style="margin-top:14px"></div></div>
    <div class="mf"><span class="grow"></span><button type="button" class="btn quiet" id="updLater">Not Now</button>${action}</div></div>`;
  document.body.appendChild(bg);
  const close = () => { bg.remove(); document.removeEventListener("keydown", key, true); };
  const key = (e) => { if (e.key === "Escape") { e.preventDefault(); later(); } };
  const later = () => { try { sessionStorage.setItem("clippy-update-later", u.latest); } catch {} close(); };   // asked again next time Clippy opens
  document.addEventListener("keydown", key, true);
  $("#updLater", bg).onclick = later;
  $("#updCopy", bg)?.addEventListener("click", async () => { try { await navigator.clipboard.writeText(u.install_line); toast("Install line copied"); } catch { toast("Select the line and copy it yourself", "bad"); } });
  $("#updGo", bg)?.addEventListener("click", async () => {
    $("#updGo", bg).disabled = $("#updLater", bg).disabled = true;
    const prog = $("#updProg", bg); prog.classList.remove("hidden");
    try { await api.post("/api/update/install"); } catch (e) { fail(e); $("#updGo", bg).disabled = $("#updLater", bg).disabled = false; return; }
    let gone = false, doneAt = 0;
    const again = () => { $("#updGo", bg).disabled = $("#updLater", bg).disabled = false; };   // try again, or Not Now
    const t = setInterval(async () => {
      let s = null; try { s = await api.get("/api/update"); } catch {}
      if (!s) { gone = true; prog.innerHTML = `<p class="small">Installing the update. Clippy opens again by itself in a moment.</p>`; return; }
      if (gone) { clearInterval(t); location.reload(); return; }                 // back after updating
      const k = s.task || {};
      if (k.state === "failed") { clearInterval(t); prog.innerHTML = `<span class="err-text">${esc(k.error)}</span>`; again(); return; }
      if (k.state === "done" && !doneAt) doneAt = Date.now();
      if (doneAt && Date.now() - doneAt > 90000) {                              // the installer never closed Clippy
        clearInterval(t);
        prog.innerHTML = `<span class="err-text">The installer didn't finish. Close Clippy (Settings → Quit Clippy) and press Update Now again, or install it from the download page.</span>`;
        again(); return;
      }
      const pct = k.total ? Math.round(100 * k.done / k.total) : null;
      prog.innerHTML = `<div class="bar ${pct == null ? "wait" : ""}"><i style="width:${pct ?? 0}%"></i></div>
        <p class="small muted" style="margin:8px 0 0">${esc(k.step || (pct != null ? `Downloading ${fmtBytes(k.done)} of ${fmtBytes(k.total)}` : "Getting the update…"))}</p>`;
    }, 1000);
  });
  $(u.can_install ? "#updGo" : "#updLater", bg)?.focus();
}

function updateNotice(u) {
  const pill = $("#updatePill");
  if (!pill) return;
  const on = Boolean(u && u.newer && u.local);
  pill.classList.toggle("hidden", !on);
  if (on) { pill.innerHTML = `${icon("download")} Update to ${esc(u.latest)}`; pill.onclick = () => showUpdate(u); }
}

async function checkForUpdate(force = false) {
  let u; try { u = await api.get("/api/update" + (force ? "?force=true" : "")); } catch { return null; }
  updateNotice(u);
  let later = null; try { later = sessionStorage.getItem("clippy-update-later"); } catch {}
  if (u.newer && u.local && (force || later !== u.latest)) showUpdate(u);
  return u;
}

// ───────────────────────── boot ─────────────────────────
hydrateIcons();
refreshGlobal();
const globalTimer = setInterval(refreshGlobal, 5000);
loadLooks().finally(route);
setTimeout(() => checkForUpdate(), 2500);         // when Clippy opens: is there a newer version?
