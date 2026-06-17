// Shared helpers used by all pages.

// Canonical card ordering: by type (Shadow, Partner, Command, Skill), then
// name, then id. Mirrors vocab.TYPE_ORDER on the server.
const TYPE_ORDER = ["Shadow", "Partner", "Command", "Skill"];
function typeRank(t) {
  const i = TYPE_ORDER.indexOf(t);
  return i < 0 ? TYPE_ORDER.length : i;
}
function compareCards(a, b) {
  const ra = typeRank(a.type), rb = typeRank(b.type);
  if (ra !== rb) return ra - rb;
  const na = (a.name || "").toLowerCase(), nb = (b.name || "").toLowerCase();
  if (na !== nb) return na < nb ? -1 : 1;
  return a.id < b.id ? -1 : 1;
}

async function api(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch (e) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}
async function apiJSON(url, method, body) {
  return api(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

let _toastTimer = null;
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

// Card-size slider whose value persists across pages + reloads (localStorage).
function setupSizeSlider(input, fallback = 150) {
  if (!input) return;
  const KEY = "bd_cardw";
  const min = parseInt(input.min || "0", 10);
  const max = parseInt(input.max || "9999", 10);
  const saved = parseInt(localStorage.getItem(KEY) || "", 10);
  let val = Number.isFinite(saved) ? saved : fallback;
  val = Math.max(min, Math.min(max, val));
  input.value = val;
  document.documentElement.style.setProperty("--cardw", val + "px");
  input.addEventListener("input", () => {
    document.documentElement.style.setProperty("--cardw", input.value + "px");
    localStorage.setItem(KEY, input.value);
  });
}

// Poll the background thumbnail warm-up and show progress in `el`.
function watchCacheWarm(el) {
  if (!el) return;
  let stop = false;
  async function tick() {
    if (stop) return;
    try {
      const s = await api("/api/cache/status");
      if (s.running && s.total) {
        el.style.display = "";
        const pct = Math.round((s.done / s.total) * 100);
        el.textContent = `⏳ Preparing images… ${s.done}/${s.total} (${pct}%)`;
        setTimeout(tick, 600);
      } else {
        el.textContent = "";
        el.style.display = "none";
        stop = true;
      }
    } catch (e) { stop = true; }
  }
  tick();
}
