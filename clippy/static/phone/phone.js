// Review on a phone: watch the shorts waiting, approve, reject or undo, save one to the phone (clippy/phone.py)
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
const media = (f) => "/media/" + String(f).split(/[\\/]/).map(encodeURIComponent).join("/");
let sig = "";

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 3500);
}

async function call(path, opts) {
  const r = await fetch(path, {credentials: "same-origin", ...opts});
  if (r.status === 401) { location.reload(); throw new Error("Scan the code again"); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}

function card(i) {
  const len = i.duration ? `${Math.round(i.duration)} s` : "";
  let acts;
  if (i.status === "pending") acts = `<button class="btn primary" data-act="approve" data-id="${esc(i.id)}">Approve &amp; Publish</button>
      <a class="btn" href="${media(i.file)}?download=1" download>Save to Phone</a>
      <button class="btn danger" data-act="reject" data-id="${esc(i.id)}">Reject</button>`;
  else if (i.status === "approved") acts = `<div class="state"><span>Approved: uploading in a few seconds</span><button class="btn" data-act="restore" data-id="${esc(i.id)}">Undo</button></div>
      <a class="btn" href="${media(i.file)}?download=1" download style="grid-column:1/-1">Save to Phone</a>`;
  else if (i.status === "uploading") acts = `<div class="state"><span>Uploading ${Math.round((i.upload_pct || 0) * 100)}%</span></div>`;
  else acts = `<div class="state err"><span>The upload failed${i.error ? `: ${esc(i.error)}` : ""}. Try again on your PC.</span></div>`;
  return `<article class="card" data-id="${esc(i.id)}">
    <video src="${media(i.file)}" ${i.thumb ? `poster="${media(i.thumb)}"` : ""} controls playsinline preload="none"></video>
    <h2>${esc(i.title)}</h2>
    <p class="meta">${[esc(i.profile_name), len, i.source_channel ? `from ${esc(i.source_channel)}` : ""].filter(Boolean).join(", ")}</p>
    <div class="acts">${acts}</div></article>`;
}

async function load(force = false) {
  let items;
  try { items = await call("/api/review"); } catch (e) { $("#list").innerHTML = `<p class="quiet">${esc(e.message)}</p>`; return; }
  const s = JSON.stringify(items.map((i) => [i.id, i.status, i.upload_pct]));
  if (!force && s === sig) return;
  if (!force && [...document.querySelectorAll("video")].some((v) => !v.paused)) return;   // never interrupt a video
  sig = s;
  const waiting = items.filter((i) => i.status === "pending").length;
  $("#count").textContent = waiting ? `${waiting} waiting` : "";
  $("#list").innerHTML = items.length ? items.map(card).join("")
    : `<div class="empty"><h2>All caught up</h2><p class="quiet">No shorts waiting. New ones show up here.</p></div>`;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  b.disabled = true;
  try {
    await call(`/api/review/${encodeURIComponent(b.dataset.id)}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action: b.dataset.act})});
    toast(b.dataset.act === "approve" ? "Approved: it uploads in 10 seconds (Undo is there until then)" : b.dataset.act === "reject" ? "Rejected" : "Moved back to waiting");
    load(true);
  } catch (err) { toast(err.message); b.disabled = false; }
});

load(true);
setInterval(() => { if (!document.hidden) load(false); }, 8000);
