"use strict";

// All rendering uses createElement/textContent: model or user text is never parsed as HTML.

const MAX_PHOTOS = 3;
const MAX_TEXT = 4000;
const MAX_EDGE_PX = 1600;
const REQUEST_TIMEOUT_MS = 45000;

const SEVERITY = {
  critical: { level: "CRITICAL", note: "Danger to life. Act now." },
  high: { level: "HIGH", note: "Serious. Get help quickly." },
  moderate: { level: "MODERATE", note: "Needs care, but appears stable." },
  low: { level: "LOW", note: "Appears minor." },
  unknown: { level: "UNKNOWN SEVERITY", note: "Not enough information. If in doubt, call." },
};
const STATUS_BADGE = {
  verified: { text: "Verified from your words", cls: "badge-verified" },
  visual: { text: "From photo - please confirm", cls: "badge-visual" },
  unverified: { text: "Not verified", cls: "badge-unverified" },
};

const $ = (id) => document.getElementById(id);
const form = $("intake-form");
const textInput = $("text");
const photoInput = $("photos");
const photoList = $("photo-list");
const locBtn = $("loc-btn");
const locLabel = $("loc-label");
const locStatus = $("loc-status");
const textCount = $("text-count");
const formError = $("form-error");
const submitBtn = $("submit-btn");
const statusEl = $("status");
const resultEl = $("result");

let photos = []; // File objects chosen by the user
let coords = null; // { lat, lng } only if the user opted in

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

function setStatus(message, busy = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("busy", busy);
}

// ---------- In-app sections (Home / Emergency / About / FAQ), switched by URL hash ----------

const VIEW_TITLES = { home: "LifeBridge - emergency help, step by step", emergency: "Emergency - LifeBridge", about: "About - LifeBridge", faq: "FAQs - LifeBridge" };

function showView(moveFocus) {
  const requested = location.hash.slice(1);
  const name = requested in VIEW_TITLES ? requested : "home"; // other hashes (e.g. the skip link) stay on Home
  for (const view of document.querySelectorAll("[data-view]")) view.hidden = view.dataset.view !== name;
  for (const link of document.querySelectorAll("[data-view-link]")) {
    if (link.dataset.viewLink === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = VIEW_TITLES[name];
  if (moveFocus && requested in VIEW_TITLES) {
    window.scrollTo(0, 0);
    document.querySelector(`[data-view="${name}"] h1`).focus();
  }
}
window.addEventListener("hashchange", () => showView(true));
showView(false);

// ---------- Emergency guidance: rendered from the vetted protocol cards (single source: app/protocols.py) ----------

const GUIDE_ICONS = { // presentation only: [path, filled?]
  unresponsive_person: [["M12 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Z"], ["M5 20.5a7 7 0 0 1 14 0"]],
  severe_bleeding: [["M12 3.5s-6 6.6-6 11a6 6 0 0 0 12 0c0-4.4-6-11-6-11Z"]],
  road_accident: [["M12 3.5 21.5 20h-19Z"], ["M12 10v4.5"], ["M12 16.2a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z", true]],
};

function guideIcon(id) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("focusable", "false");
  for (const [d, filled] of GUIDE_ICONS[id] || []) {
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", filled ? "currentColor" : "none");
    if (!filled) {
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.8");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
    }
    svg.append(path);
  }
  return el("span", { class: "option-icon", "aria-hidden": "true" }, svg);
}

async function loadEmergencyGuidance() {
  const grid = $("guide-grid");
  try {
    const response = await fetch(`/api/protocols?ids=${encodeURIComponent(grid.dataset.protocols)}`);
    const cards = response.ok ? await response.json() : [];
    if (!cards.length) throw new Error("no protocols");
    grid.replaceChildren(...cards.map((p) => el("article", { class: "guide-card" },
      guideIcon(p.id),
      el("h3", { text: p.title }),
      el("ol", { class: "steps", role: "list" }, ...p.steps.map((s) => el("li", { text: s }))))));
  } catch {
    $("guide-status").textContent = "Could not load the safety steps. If anyone may be in danger, call 112 now.";
  } finally {
    grid.removeAttribute("aria-busy");
  }
}
loadEmergencyGuidance();

// ---------- Character counter (limit enforced by maxlength and the server) ----------

function updateCount() { textCount.textContent = `${textInput.value.length}/${MAX_TEXT}`; }
textInput.addEventListener("input", updateCount);
updateCount();

// ---------- Photos ----------

function renderPhotoList() {
  photoList.replaceChildren(
    ...photos.map((file, i) =>
      el("li", {}, el("span", { text: file.name }),
        (() => {
          const btn = el("button", { type: "button", "aria-label": `Remove ${file.name}`, text: "✕" });
          btn.addEventListener("click", () => { photos.splice(i, 1); renderPhotoList(); photoInput.focus(); });
          return btn;
        })())
    )
  );
}

photoInput.addEventListener("change", () => {
  const combined = photos.concat(Array.from(photoInput.files || []));
  photos = combined.slice(0, MAX_PHOTOS);
  formError.textContent = combined.length > MAX_PHOTOS ? `Only the first ${MAX_PHOTOS} photos were kept.` : "";
  photoInput.value = "";
  renderPhotoList();
});

// Downscale in the browser: faster upload, less data sent to the model.
async function shrinkImage(file) {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob || file;
  } catch {
    return file; // e.g. HEIC on browsers that cannot decode it: send the original, the server validates it
  }
}

// ---------- Location (opt-in) ----------

locBtn.addEventListener("click", () => {
  if (coords) {
    coords = null;
    locBtn.setAttribute("aria-pressed", "false");
    locLabel.textContent = "Share my location";
    locStatus.textContent = "Location removed.";
    return;
  }
  if (!("geolocation" in navigator)) {
    locStatus.textContent = "This browser cannot share location. Type your location instead.";
    return;
  }
  locStatus.textContent = "Getting your location...";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      locBtn.setAttribute("aria-pressed", "true");
      locLabel.textContent = "Location added ✓";
      locStatus.textContent = "Your location will be added to the SOS message.";
    },
    () => { locStatus.textContent = "Could not get location. Type a landmark or address instead."; },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
});

// ---------- Submit ----------

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  const text = textInput.value.trim();
  if (!text && photos.length === 0) {
    formError.textContent = "Describe what is happening or add a photo.";
    textInput.focus();
    return;
  }
  if (text.length > MAX_TEXT) {
    formError.textContent = `Please keep the description under ${MAX_TEXT} characters.`;
    textInput.focus();
    return;
  }

  submitBtn.disabled = true;
  setStatus("Understanding your message... If anyone is in danger, call 112 now.", true);

  const body = new FormData();
  body.append("text", text);
  if (coords) { body.append("lat", String(coords.lat)); body.append("lng", String(coords.lng)); }
  for (const file of photos) {
    const shrunk = await shrinkImage(file);
    body.append("images", shrunk, file.name.replace(/\.\w+$/, "") + (shrunk.type === "image/jpeg" ? ".jpg" : ""));
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch("/api/analyze", { method: "POST", body, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data) {
      const message = (data && data.message) || "Something went wrong.";
      formError.textContent = `${message} If anyone is in danger, call 112.`;
      setStatus("");
      return;
    }
    setStatus("");
    renderCard(data);
  } catch {
    formError.textContent = "Could not reach LifeBridge. Check your connection. If anyone is in danger, call 112 now.";
    setStatus("");
  } finally {
    clearTimeout(timer);
    submitBtn.disabled = false;
  }
});

// ---------- Result card ----------

function section(title, ...children) {
  return el("section", { class: "panel" }, el("h2", { text: title }), ...children);
}

function sevIcon(severity) {
  // Decorative: the level is always spelled out in text next to it.
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "sev-icon");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS(NS, "path");
  path.setAttribute("fill", "currentColor");
  path.setAttribute("d", severity === "critical" || severity === "high"
    ? "M12 2 1 21h22L12 2Zm-1 7h2v6h-2V9Zm0 8h2v2h-2v-2Z"
    : "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-1 5h2v2h-2V7Zm0 4h2v6h-2v-6Z");
  svg.append(path);
  return svg;
}

function renderCard(card) {
  const sev = SEVERITY[card.severity] || SEVERITY.unknown;
  const outOfScope = card.scope === "out_of_scope";
  const showCallNow = !outOfScope && ["critical", "high", "unknown"].includes(card.severity) && card.contacts.length;
  const parts = [];

  // 1. Severity banner: level, incident, the one primary action, and the danger signs that drove it.
  parts.push(el("div", { class: `sev sev-${card.severity}` },
    el("h2", { id: "result-title", class: "visually-hidden", text: "Your action card" }),
    el("div", { class: "sev-head" },
      sevIcon(card.severity),
      el("div", {},
        el("p", { class: "sev-level", text: outOfScope ? "NOT AN EMERGENCY" : sev.level }),
        el("p", { class: "sev-incident", text: outOfScope ? "No safety situation detected" : incidentLabel(card.incident_type) }))),
    outOfScope ? null : el("p", { class: "sev-note", text: sev.note }),
    showCallNow ? el("a", { class: "btn btn-sev-call", href: card.contacts[0].tel, text: `Call ${card.contacts[0].number} now` }) : null,
    card.red_flags.length ? el("ul", { class: "sev-flags", "aria-label": "Danger signs detected" },
      ...card.red_flags.map((f) => el("li", { text: f.label }))) : null));

  // One concise indicator when the card was built without AI (the server's reason notice).
  if (card.source === "fallback") {
    parts.push(el("p", { class: "mode-note" },
      el("strong", { text: "Offline safety mode. " }),
      el("span", { text: card.notices[0] || "Showing safety guidance based on keywords in your message." })));
  }

  // 2. Immediate action steps.
  if (card.protocols.length) {
    parts.push(el("section", { class: "panel panel-now" }, el("h2", { text: "Do this now" }),
      ...card.protocols.map((p) => el("div", { class: "protocol" },
        el("h3", { text: p.title }),
        el("ol", { class: "steps", role: "list" }, ...p.steps.map((s) => el("li", { text: s })))))));
  }

  // 3. AI summary and transparency notices (AI cards only; the fallback card already said why above).
  if (card.source !== "fallback") {
    parts.push(el("p", { class: "summary", text: card.summary }));
    if (card.notices.length) {
      parts.push(el("ul", { class: "notices" }, ...card.notices.map((n) => el("li", { text: n }))));
    }
  }

  parts.push(section("Call for help",
    el("div", { class: "contacts" },
      ...card.contacts.map((c, i) => el("a", {
        class: i === 0 ? "btn btn-call" : "btn btn-call-secondary", href: c.tel, text: `${c.name}: ${c.number}`,
      })))));

  if (card.follow_up_questions.length) {
    parts.push(section("Responders will ask",
      el("p", { class: "hint", text: "Add the answers to your description and press Get help steps again." }),
      el("ol", { class: "questions" }, ...card.follow_up_questions.map((q) => el("li", { text: q })))));
  }

  parts.push(sosSection(card.sos_message));

  if (card.links.length) {
    parts.push(section("Maps",
      el("ul", { class: "links" }, ...card.links.map((l) =>
        el("li", {}, el("a", { href: l.url, target: "_blank", rel: "noopener noreferrer", text: l.label }))))));
  }

  if (card.facts.length) {
    parts.push(section("What LifeBridge understood",
      el("ul", { class: "facts" }, ...card.facts.map(factItem))));
  }

  // The disclaimer is shown once, in the page footer, directly below the card.
  resultEl.replaceChildren(...parts);
  resultEl.hidden = false;
  resultEl.focus();
  resultEl.scrollIntoView({ block: "start" });
}

function factItem(f) {
  const badge = STATUS_BADGE[f.status] || STATUS_BADGE.unverified;
  return el("li", {},
    el("span", { class: "fact-label", text: `${f.label}: ` }),
    el("span", { text: f.value }),
    el("span", { class: `badge ${badge.cls}`, text: badge.text }),
    f.source === "text" ? el("p", { class: "fact-quote", text: `Your words: “${f.quote}”` }) : null);
}

function sosSection(message) {
  const copyBtn = el("button", { type: "button", class: "btn btn-secondary", text: "Copy message" });
  copyBtn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(message); setStatus("SOS message copied."); }
    catch { setStatus("Copy failed. Select the message and copy it manually."); }
  });
  const row = el("div", { class: "row" }, copyBtn,
    el("a", { class: "btn btn-secondary", href: `sms:?&body=${encodeURIComponent(message)}`, text: "Send as SMS" }));
  if (navigator.share) {
    const shareBtn = el("button", { type: "button", class: "btn btn-secondary", text: "Share" });
    shareBtn.addEventListener("click", () => navigator.share({ text: message }).catch(() => {}));
    row.append(shareBtn);
  }
  return section("SOS message",
    el("p", { class: "hint", text: "Built only from verified details. Send it to family or responders." }),
    el("pre", { class: "sos-text", text: message }), row);
}

const INCIDENTS = {
  medical: "Medical emergency", injury_trauma: "Injury", road_accident: "Road accident", fire: "Fire",
  drowning: "Drowning", electrocution: "Electric shock", violence_assault: "Violence / assault",
  natural_disaster: "Natural disaster", hazardous_material: "Hazardous material",
  mental_health_crisis: "Mental health crisis", other: "Other situation", unknown: "Unclear situation",
};
function incidentLabel(type) { return INCIDENTS[type] || INCIDENTS.unknown; }
