"use strict";

// All rendering uses createElement/textContent: model or user text is never parsed as HTML.

const MAX_PHOTOS = 3;
const MAX_TEXT = 4000;
const MAX_EDGE_PX = 1600;
const REQUEST_TIMEOUT_MS = 45000;

const SEVERITY = {
  critical: { icon: "!!", level: "CRITICAL", note: "Danger to life. Call 112 now." },
  high: { icon: "!", level: "HIGH", note: "Serious. Get help quickly." },
  moderate: { icon: "●", level: "MODERATE", note: "Needs care, but appears stable." },
  low: { icon: "✓", level: "LOW", note: "Appears minor." },
  unknown: { icon: "?", level: "UNKNOWN", note: "Not enough information. If in doubt, call 112." },
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
const locStatus = $("loc-status");
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
    locBtn.textContent = "Share my location";
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
      locBtn.textContent = "Location added ✓";
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

function renderCard(card) {
  const sev = SEVERITY[card.severity] || SEVERITY.unknown;
  const parts = [];

  parts.push(el("div", { class: `sev sev-${card.severity}` },
    el("span", { class: "sev-icon", "aria-hidden": "true", text: sev.icon }),
    el("div", {},
      el("h2", { id: "result-title", class: "visually-hidden", text: "Your action card" }),
      el("span", { class: "sev-level", text: `${sev.level} — ${incidentLabel(card.incident_type)}` }),
      el("span", { text: sev.note }))));

  parts.push(el("p", { class: "summary", text: card.summary }));

  if (card.red_flags.length) {
    parts.push(el("ul", { class: "chips", "aria-label": "Danger signs detected" },
      ...card.red_flags.map((f) => el("li", { text: f.label }))));
  }
  if (card.notices.length) {
    parts.push(el("ul", { class: "notices" }, ...card.notices.map((n) => el("li", { text: n }))));
  }

  if (card.protocols.length) {
    parts.push(section("Do this now",
      ...card.protocols.map((p) => el("div", { class: "protocol" },
        el("h3", { text: p.title }),
        el("ol", {}, ...p.steps.map((s) => el("li", { text: s })))))));
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

  parts.push(el("p", { class: "hint", text: card.disclaimer }));
  if (card.source === "fallback") {
    parts.push(el("p", { class: "hint", text: "This card was generated without AI analysis." }));
  }

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
