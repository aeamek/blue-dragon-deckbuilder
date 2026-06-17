# In-UI card labeling editor

## Problem

`labels.csv` exists as a working file but has only the header row — every card in the catalog is currently unlabeled. The only way to populate it today is to hand-edit the CSV with full knowledge of the schema. That's brittle (typos in element / type values, no autocomplete for sets) and tedious for 272 rows. There's also no surface for inspecting a card and its label together, so verifying a label means cross-referencing the CSV against the image by hand.

## Goal

Let the user label cards from inside the app. Clicking a card opens an enlarged-image modal with a form alongside it; edits autosave back to `labels.csv`. Forward/back navigation moves between cards in the currently-filtered view so batch labeling is fast. Lock the element and type vocabularies so dropdowns prevent typos, and surface them via an API endpoint so the frontend doesn't hardcode them.

## Non-goals (explicit YAGNI)

- OCR / automatic name extraction. Handled by a separate offline script in a follow-up spec.
- Foil-card detection and confidence scoring — automation-script concern.
- Real-time multi-tab sync. Last-write-wins is fine for a local one-user app.
- Undo / redo within the editor. Re-editing a field is sufficient.
- Bulk-edit ("apply this element to every selected card"). Per-card editing only.
- Ability text, level / cost, rarity. Still out of scope.

## Design

### Vocabularies and schema

Three vocabularies drive the editor:

- **Card type** — `Shadows, Partners, Skills, Commands`. Closed set.
- **Element / attribute** — `light, dark, fire, water, earth, wind, none`. Closed set. `none` is a real value (the card has no element) and is distinct from an unlabeled empty.
- **Set** — starts with `Light Starter, Shadow Starter, Demo Deck, Set 1, Set 2, Parallel Shadows`. Extensible — the editor lets the user add new set names, and any set value that appears in `labels.csv` becomes legal automatically (union of seeded defaults and observed values).

**Type-element coupling:** only `Shadows` and `Partners` carry an element. `Commands` and `Skills` rows leave the `element` column blank. The editor hides the element field when the type is Commands or Skills; the API forces `element=[]` on save defensively.

**CSV schema** is unchanged from the existing `labels.csv` (`id, set, name, element, type`) with one rule for multi-element cards: `element` is **pipe-separated**, alphabetically sorted on write. Single-element cards have a plain value (`light`); multi-element cards use `dark|light`.

**JSON API** returns `element` as a list of strings (`[]` / `["light"]` / `["dark", "light"]`).

**Validation is lenient on load.** Unknown `element` or `type` values keep loading; they surface as warnings in the startup banner (and via the existing `warnings` field in `/api/status`). Same for Command/Skill rows that have a non-empty element — those load but emit a warning and the element list is ignored when the row is served over the API. The editor uses dropdowns and checkboxes so user-typed values can't be wrong on the way in; only hand-edited CSVs can produce off-vocab data.

### Editor UX: zoom modal becomes an editor

The existing click-to-zoom modal (`setupZoom` in `static/common.js`) is replaced by an editor that combines the enlarged image with an inline form. Same modal appears on Browse Cards **and** Deck Edit, so labeling while building a deck doesn't require leaving the page.

Layout (image dominant; form on the right):

```
┌──────────────────────── card editor (modal) ─────────────────────────────┐
│ ◀                                                                       ▶ │
│   ┌────────────────────────────────┐  ┌──────────────────────────────┐    │
│   │                                │  │ BDS1-EN_0001        12 / 272 │    │
│   │                                │  │                              │    │
│   │       large card image         │  │ Name   [ Phoenix___________ ]│    │
│   │       fills available space    │  │                              │    │
│   │       (flex: 1, contain)       │  │ Set    [ Light Starter   v ] │    │
│   │                                │  │         └ + Add new set...   │    │
│   │                                │  │                              │    │
│   │                                │  │ Type   [ Shadows         v ] │    │
│   │                                │  │                              │    │
│   │                                │  │ Element                      │    │
│   │                                │  │ [✓ light] [ ] dark [ ] fire  │    │
│   │                                │  │ [ ] water [ ] earth [ ] wind │    │
│   │                                │  │ [ ] none                     │    │
│   │                                │  │                              │    │
│   │                                │  │            Saved ✓           │    │
│   └────────────────────────────────┘  └──────────────────────────────┘    │
│                                                                           │
│            Esc / click bg = close   ◀ / ▶ = prev/next   Tab = next field  │
└───────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**

- **Autosave.** Every field change debounces ~200 ms then sends a `PUT /api/labels/<id>`. Status line cycles `Saving…` / `Saved ✓` / `Save failed: <reason>`. No explicit Save button.
- **Element block visibility gated by type.** Type Commands or Skills hides the element block and clears the local state (cleared values flush on the next autosave).
- **Set dropdown** is populated from `/api/vocab.sets`. A `+ Add new set…` entry at the bottom of the dropdown prompts for a new set name (HTML `prompt()` is fine — local app, no styling work). Empty/whitespace input cancels. New names appear in the dropdown immediately and persist when the next save lands.
- **Prev / Next navigation** moves between cards in the currently-filtered view. When the modal opens, the page passes the current filtered card list + the clicked index to the modal; the modal walks that **snapshot**. Edits don't reshuffle the cursor mid-flow. At the ends, the corresponding arrow button disables. Keyboard `←` / `→` mirror the on-screen buttons. Saves are fire-and-forget on navigation: if a save fails after the user moved on, the failure toasts globally.
- **Keyboard:** Tab cycles fields top-to-bottom; Esc closes; arrows navigate.
- **Narrow viewports:** the panels stack vertically (image on top, form below). CSS media query at ~720 px.

### API

Two new routes plus extended response shape:

- **`GET /api/vocab`** → vocabulary lists:
  ```json
  {
    "types": ["Shadows", "Partners", "Skills", "Commands"],
    "elements": ["light", "dark", "fire", "water", "earth", "wind", "none"],
    "sets": ["Light Starter", "Shadow Starter", "Demo Deck",
             "Set 1", "Set 2", "Parallel Shadows"]
  }
  ```
  `sets` is the sorted union of the seeded defaults and any set string seen in `labels.csv`. Custom set names added via the editor appear here on the next request.

- **`PUT /api/labels/<card_id>`** → save / update a card's label.
  Request body:
  ```json
  { "name": "Phoenix", "set": "Light Starter",
    "type": "Shadows", "element": ["light"] }
  ```
  - `200` with the updated catalog record (`{id, set, name, element, type}`) on success.
  - `400` on malformed body (missing required keys, wrong types).
  - `404` if `card_id` doesn't exist in the image scan.
  - Server-side coercion: if `type ∈ {Commands, Skills}`, `element` is forced to `[]` before write.
  - Whitespace-trimmed across all string fields. Empty `name` is allowed (row remains; card displays as unlabeled).

- **`/api/cards`** (existing) gains the `element` list shape — was `string | null`, becomes `string[]`. Unlabeled cards return `element: []`. The client-side chip filter (currently scalar-equality) updates to membership-in-array (`card.element.includes(chip)`).

### CSV persistence

Responsibilities split cleanly:

- `labels.py` owns parsing (existing `load()`) and serialization (new `dump(rows, path)`). Stateless helpers. No locks here.
- `catalog.py` owns the in-memory state and the write coordination via a new `save_label(card_id, payload)`. It also keeps the `rows` dict alive after `build()` (today it's discarded once the per-card references are stored) so saves don't need to re-read disk.

`catalog.save_label(card_id, payload)` steps, all inside a single module-level `threading.Lock`:

1. Validate `card_id` exists in the image scan; raise `KeyError` if not (route returns 404).
2. Coerce: trim string fields; if `type ∈ {Commands, Skills}`, force `element = []`. Sort `element` alphabetically.
3. Build a `LabelRow` and write it to `_label_rows[card_id]` (overwriting any prior).
4. Call `labels.dump(_label_rows, path)` — full CSV rewrite, sorted by `id` for stable diffs.
5. Update `_catalog[card_id]["label"]` to point at the new row.
6. Refresh `_sets` / `_elements` / `_types` if the save introduced a previously-unseen value (sets only; element / type chips are vocab-defined and don't depend on this).
7. Return the API-shape record for the card.

`labels.dump(rows, path)` writes to `path + ".tmp"` then `os.replace`s. CSV writer is `csv.writer(fh, lineterminator="\n")` for deterministic line endings. UTF-8 (no BOM) on write; reads continue to use `utf-8-sig` so a hand-edited file with a BOM still loads. Multi-element values serialize as `dark|light` (sorted); single-element as `light`; empty as `""`.

### Filter UI ripple change

The existing chip rows (Set / Element / Type) on Browse Cards and Deck Edit currently auto-populate from values seen in `labels.csv`. This spec switches their data source to `/api/vocab`:

- **Set chips:** unchanged behavior visually — the union list includes the same observed values plus the seeded defaults.
- **Element chips:** the seven canonical values always show, regardless of how many cards are labeled.
- **Type chips:** the four canonical values always show.
- **Sort order:** vocab-defined (the order the values appear in the vocab arrays). Sets are alphabetical with the seeded defaults at their original spec-defined order at the top.

Filter semantics for the now-list-valued `element` field: a card passes an element-chip filter if its `element` array contains the chip's lowercased value. Within-axis OR / across-axis AND from the existing design is preserved.

### Edge cases

- **First-time label** (card has no row in CSV yet): the editor opens with empty fields; the first autosave creates the row and flips the card from the unlabeled bucket to the labeled bucket.
- **User clears the name back to empty:** row persists with empty name. Set/type are independently useful, and the card display falls back to its ID (the existing unlabeled rendering).
- **Type switched Shadows → Commands while element=["light","dark"]:** the editor clears the element checkboxes immediately; the next autosave sends `element=[]`; the server would clear it anyway.
- **"+ Add new set" with empty / whitespace-only input:** the dropdown reverts to its previous value; no save fires.
- **Navigating (◀ / ▶) while a save is mid-flight:** the save is fire-and-forget; the modal advances to the next card. If the save fails, the page-level toast surfaces the error.
- **Concurrent saves on different cards from two tabs:** `threading.Lock` serialises them; both succeed.
- **Two tabs editing the same card:** last-write-wins. No live sync.
- **Card image is a foil (darker / harder to read):** out of scope for the editor itself — the user just sees the image as-is. The future automation script handles foil detection.
- **CSV file deleted between app startup and a save:** the save path treats it as "no rows yet" and writes the single edited row. No special-casing.
- **Lock-file races between rescan and save:** a single module-level lock in `catalog.py` serialises both rescans (`build()`) and saves (`save_label()`). No multi-lock ordering needed.

### File and code structure

**New files:**

- `static/editor.js` — modal layout, form behavior, prev/next navigation, autosave wiring. Replaces `setupZoom` from `static/common.js`.
- `tests/test_labels_save.py` — save-path tests.

**Modified files:**

- `labels.py` — add `dump(rows, path)` (stateless serializer), extend `load()` with multi-element pipe parsing and the new lenient-validation warnings (off-vocab, type-element mismatch). No lock here.
- `catalog.py` — add `save_label(card_id, payload)` plus the module-level `threading.Lock` that also covers `build()`. Keep the labels `rows` dict alive after build. `_record_to_api` returns `element` as a list (string → singleton list, empty → `[]`).
- `app.py` — add the two new routes (`GET /api/vocab`, `PUT /api/labels/<card_id>`).
- `static/common.js` — drop `setupZoom`; pages now load `editor.js` and call its `openEditor(card, cards, index)` API.
- `static/filters.js` — chip data source switches from data-derived to `/api/vocab`; `cardPasses` updates to treat `card.element` as an array (`.includes(chip)` instead of equality).
- `templates/cards.html` and `templates/deck.html` — load `editor.js`, pass the filtered card list to the editor on click, drop set/element/type chip auto-population (chips come from `/api/vocab` now).
- `tests/test_labels.py` — extend with lenient-validation cases (unknown element, type-element mismatch, multi-element parsing).
- `tests/test_catalog.py` — update fixtures for the list-valued element shape; assert the catalog's API response shape.
- `README.md` — short paragraph in the "Card labels" section noting that labeling now happens in-app; the CSV is just the persistence layer.

### Testing

- `tests/test_labels_save.py` (exercises `catalog.save_label`)
  - Creates a row when the card had no entry.
  - Updates an existing row in place.
  - Element list round-trips through pipe-separated form, alphabetical on write.
  - Type=Commands forces `element=[]` even if the payload includes elements.
  - Concurrent saves on different ids from two threads don't corrupt the file (use a `threading.Barrier` to synchronise).
  - Atomic write: monkey-patch `os.replace` to raise; assert the original file is untouched.
- `tests/test_labels.py` extended cases
  - Unknown element value loads with a warning.
  - Unknown type value loads with a warning.
  - Command row with non-empty element loads with a warning and the element list is dropped at the API layer.
  - Multi-element value parses into a list.
- `tests/test_catalog.py` updated
  - `element` returned as a list (singleton for single-element cards).
  - Unlabeled cards return `element: []`.

No end-to-end browser tests. Manual smoke test is sufficient: open the editor on a card, walk Prev/Next through five cards, verify the CSV updates on disk between each.

## Rollout / order of work

1. Extend `labels.py` with multi-element parse / serialize + lenient-validation warnings; update `tests/test_labels.py` to cover the new cases.
2. Add `labels.save()` + the labels-module lock; write `tests/test_labels_save.py`.
3. Update `catalog._record_to_api` to return `element` as a list; update `tests/test_catalog.py`. Add `catalog.update_record(card_id, label_row)`.
4. Add `GET /api/vocab` and `PUT /api/labels/<card_id>` routes; smoke via `curl`.
5. Build `static/editor.js` (layout, form, autosave, prev/next snapshot). Wire it into `cards.html`.
6. Mirror onto `deck.html`.
7. Switch `static/filters.js` chip data source from data-derived to `/api/vocab`; update `cardPasses` for list-valued element.
8. Manual end-to-end labeling smoke test on five cards; verify CSV updates between each.
9. README touch-up.
