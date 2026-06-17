// Card editor modal. Replaces the old image-only zoom.
//
// openEditor(cards, index, { onSave, getVocab }):
//   cards         array of card records (id, set, name, element[], type)
//   index         starting index into `cards`
//   opts.onSave   called with the updated card record after each save
//   opts.getVocab returns a Promise that resolves to {types, elements, sets}

let _modal = null;
let _state = null;

function _build() {
  const modal = document.createElement("div");
  modal.className = "editor-modal";
  modal.innerHTML = `
    <div class="editor-stage">
      <button class="ed-nav prev" aria-label="previous">◀</button>
      <div class="editor-body">
        <div class="editor-image"><img alt=""></div>
        <div class="editor-form">
          <div class="ed-head">
            <span class="ed-id"></span>
            <span class="ed-pos"></span>
          </div>
          <label>Name <input type="text" class="ed-name" autocomplete="off"></label>
          <label>Set
            <select class="ed-set"></select>
          </label>
          <label>Type
            <select class="ed-type"></select>
          </label>
          <div class="ed-element-block">
            <div class="ed-element-label">Element</div>
            <div class="ed-element-chips"></div>
          </div>
          <div class="ed-status"></div>
        </div>
      </div>
      <button class="ed-nav next" aria-label="next">▶</button>
    </div>`;
  document.body.appendChild(modal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });
  modal.querySelector(".prev").addEventListener("click", () => move(-1));
  modal.querySelector(".next").addEventListener("click", () => move(+1));
  modal.querySelector(".ed-name").addEventListener("input", scheduleSave);
  modal.querySelector(".ed-set").addEventListener("change", onSetChange);
  modal.querySelector(".ed-type").addEventListener("change", onTypeChange);
  return modal;
}

function _ensure() {
  if (!_modal) _modal = _build();
  return _modal;
}

function close() {
  if (_modal) _modal.classList.remove("open");
  _state = null;
  document.removeEventListener("keydown", _onKey);
}

function _onKey(e) {
  if (!_state) return;
  if (e.key === "Escape") { close(); }
  else if (e.key === "ArrowLeft") { move(-1); }
  else if (e.key === "ArrowRight") { move(+1); }
}

function setStatus(text, kind) {
  const el = _modal.querySelector(".ed-status");
  el.textContent = text;
  el.dataset.kind = kind || "";
}

function move(delta) {
  flushSave();
  const next = _state.index + delta;
  if (next < 0 || next >= _state.cards.length) return;
  _state.index = next;
  loadCurrent();
}

function loadCurrent() {
  const card = _state.cards[_state.index];
  const m = _modal;
  m.querySelector(".ed-id").textContent = card.id;
  m.querySelector(".ed-pos").textContent = `${_state.index + 1} / ${_state.cards.length}`;
  m.querySelector(".editor-image img").src =
    `/api/card/${encodeURIComponent(card.id)}/view`;

  m.querySelector(".ed-name").value = card.name || "";

  populateSet(card.set || "");
  populateType(card.type || "");
  populateElement(card.element || []);
  toggleElementBlock(card.type);

  m.querySelector(".prev").disabled = _state.index === 0;
  m.querySelector(".next").disabled = _state.index === _state.cards.length - 1;
  setStatus("", "");
}

function populateSet(currentSet) {
  const sel = _modal.querySelector(".ed-set");
  sel.innerHTML = "";
  const blank = document.createElement("option");
  blank.value = ""; blank.textContent = "—";
  sel.appendChild(blank);
  for (const s of _state.vocab.sets) {
    const o = document.createElement("option"); o.value = s; o.textContent = s;
    sel.appendChild(o);
  }
  if (currentSet && !_state.vocab.sets.includes(currentSet)) {
    const o = document.createElement("option");
    o.value = currentSet; o.textContent = currentSet;
    sel.appendChild(o);
  }
  const add = document.createElement("option");
  add.value = "__add__"; add.textContent = "+ Add new set…";
  sel.appendChild(add);
  sel.value = currentSet || "";
}

function populateType(currentType) {
  const sel = _modal.querySelector(".ed-type");
  sel.innerHTML = "";
  const blank = document.createElement("option");
  blank.value = ""; blank.textContent = "—";
  sel.appendChild(blank);
  for (const t of _state.vocab.types) {
    const o = document.createElement("option"); o.value = t; o.textContent = t;
    sel.appendChild(o);
  }
  if (currentType && !_state.vocab.types.includes(currentType)) {
    const o = document.createElement("option");
    o.value = currentType; o.textContent = currentType + " (off-vocab)";
    sel.appendChild(o);
  }
  sel.value = currentType || "";
}

function populateElement(currentList) {
  const box = _modal.querySelector(".ed-element-chips");
  box.innerHTML = "";
  const set = new Set(currentList.map(e => e.toLowerCase()));
  for (const el of _state.vocab.elements) {
    const id = `el-${el}`;
    const wrap = document.createElement("label");
    wrap.className = "ed-element-chip";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.id = id; cb.value = el; cb.checked = set.has(el);
    cb.addEventListener("change", scheduleSave);
    const txt = document.createElement("span"); txt.textContent = el;
    wrap.appendChild(cb); wrap.appendChild(txt);
    box.appendChild(wrap);
  }
}

function toggleElementBlock(type) {
  const block = _modal.querySelector(".ed-element-block");
  const hide = type === "Command" || type === "Skill";
  block.style.display = hide ? "none" : "";
  if (hide) {
    for (const cb of _modal.querySelectorAll(".ed-element-chips input")) {
      cb.checked = false;
    }
  }
}

function onSetChange(e) {
  if (e.target.value === "__add__") {
    const name = (window.prompt("New set name:") || "").trim();
    if (!name) {
      e.target.value = _state.cards[_state.index].set || "";
      return;
    }
    if (!_state.vocab.sets.includes(name)) {
      _state.vocab.sets.push(name);
    }
    populateSet(name);
  }
  scheduleSave();
}

function onTypeChange(e) {
  toggleElementBlock(e.target.value);
  scheduleSave();
}

function readForm() {
  const m = _modal;
  const elements = Array.from(
    m.querySelectorAll(".ed-element-chips input:checked"),
    cb => cb.value
  );
  return {
    name: m.querySelector(".ed-name").value.trim(),
    set: m.querySelector(".ed-set").value === "__add__"
            ? "" : m.querySelector(".ed-set").value,
    type: m.querySelector(".ed-type").value,
    element: elements,
  };
}

let _saveTimer = null;
function scheduleSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(doSave, 250);
}
function flushSave() {
  if (_saveTimer) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
    doSave();
  }
}

async function doSave() {
  if (!_state) return;
  const card = _state.cards[_state.index];
  const payload = readForm();
  setStatus("Saving…", "saving");
  try {
    const res = await fetch(`/api/labels/${encodeURIComponent(card.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const updated = await res.json();
    _state.cards[_state.index] = updated;
    setStatus("Saved ✓", "saved");
    if (_state.onSave) _state.onSave(updated);
  } catch (err) {
    setStatus("Save failed: " + err.message, "error");
  }
}

async function openEditor(cards, index, opts) {
  opts = opts || {};
  const modal = _ensure();
  const vocab = await opts.getVocab();
  _state = {
    cards: cards.slice(),
    index,
    vocab,
    onSave: opts.onSave,
  };
  modal.classList.add("open");
  document.addEventListener("keydown", _onKey);
  loadCurrent();
  modal.querySelector(".ed-name").focus();
}

// Tiny memoized vocab fetcher; pages can pass this as opts.getVocab.
let _vocabPromise = null;
function fetchVocab() {
  if (!_vocabPromise) {
    _vocabPromise = fetch("/api/vocab").then(r => r.json());
  }
  return _vocabPromise;
}
