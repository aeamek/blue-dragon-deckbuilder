// Shared filter pipeline for the card grid (used by cards.html and deck.html).
//
// A card has the shape: { id, set, name, element, type } where any of
// set/name/element/type may be null when the card is unlabeled.

function buildChipRows(vocab) {
  return {
    set: vocab.sets || [],
    element: vocab.elements || [],
    type: vocab.types || [],
  };
}

// state = { selectedSets, selectedElements, selectedTypes: Set<string lowercase>,
//           search: string, hideUnlabeled: bool }
function cardPasses(card, state) {
  const sets = card.set || [];
  if (state.hideUnlabeled && !card.name && sets.length === 0) return false;

  if (state.selectedSets.size) {
    const cardSets = sets.map(s => s.toLowerCase());
    let any = false;
    for (const sel of state.selectedSets) {
      if (cardSets.includes(sel)) { any = true; break; }
    }
    if (!any) return false;
  }

  if (state.selectedElements.size) {
    const els = (card.element || []).map(e => e.toLowerCase());
    let any = false;
    for (const sel of state.selectedElements) {
      if (els.includes(sel)) { any = true; break; }
    }
    if (!any) return false;
  }

  if (state.selectedTypes.size
      && !state.selectedTypes.has((card.type || "").toLowerCase())) return false;

  const q = (state.search || "").trim().toLowerCase();
  if (q) {
    const hay = `${card.id} ${card.name || ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderChipRow(container, label, values, selected, onToggle) {
  container.innerHTML = "";
  if (!values.length) {
    container.innerHTML = `<span class="chip-empty">${label}: —</span>`;
    return;
  }
  const lbl = document.createElement("span");
  lbl.className = "chip-label";
  lbl.textContent = label;
  container.appendChild(lbl);
  for (const v of values) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (selected.has(v.toLowerCase()) ? " on" : "");
    chip.textContent = v;
    chip.addEventListener("click", () => {
      const key = v.toLowerCase();
      if (selected.has(key)) selected.delete(key); else selected.add(key);
      chip.classList.toggle("on");
      onToggle();
    });
    container.appendChild(chip);
  }
}

function renderStandardChips(vocab, state, onChange) {
  const chips = buildChipRows(vocab);
  state.selectedSets = new Set();
  state.selectedElements = new Set();
  state.selectedTypes = new Set();
  renderChipRow(document.getElementById("chipSet"), "Set",
                chips.set, state.selectedSets, onChange);
  renderChipRow(document.getElementById("chipElement"), "Element",
                chips.element, state.selectedElements, onChange);
  renderChipRow(document.getElementById("chipType"), "Type",
                chips.type, state.selectedTypes, onChange);
}
