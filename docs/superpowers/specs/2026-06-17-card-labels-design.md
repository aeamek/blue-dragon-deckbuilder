# Card labels and filterable catalog

## Problem

Today the catalog gets all its metadata from the filesystem: cards live in per-set subfolders under `cards_dir`, and the only "card information" available to the app is the filename stem (e.g. `BDS1-EN_0008`) and the parent folder name. There is no card name, no element, no card type. Users can filter by set or substring-match the ID, and that's it. Building a deck means recognising every card by its scan.

## Goal

Layer human-friendly metadata over the existing image collection so users can filter and search by **name, set, element, and card type** — without forcing the codebase to maintain a hardcoded list of every card, and without shipping any card images in the repo.

## Non-goals (explicit YAGNI)

The following are intentionally out of scope. Flagging so they're not forgotten, not so they're done:

- Ability / rules text and full-text search across it.
- Level / cost field, attack / defence stats.
- Rarity, foil / alt-art flags, collector metadata.
- Hard validation enums for element / type. Soft validation only.
- Automatic OCR of card art into labels.
- Deck statistics by element / type.
- Multi-language support.

## Design

### Data model

Three fields drive the feature: a per-card image file on disk, a row in a labels CSV, and the in-memory record that joins them.

**On disk** — `cards_dir/` is a single flat folder of card images, and by default it lives **inside the project** at `<repo>/cards/`. Setup story for a new user: clone the repo, download the card scans from wherever they get them, drop the files into `<repo>/cards/`. The folder is gitignored — see "What gets published in the repo" below. The path is still overridable via env var or `config.local.json` for users who want to keep the scans on an external disk.

The filename stem is the card ID (e.g. `BDS1-EN_0008.jpg` → id `BDS1-EN_0008`). IDs are globally unique across sets — already true in the current scans — so no per-set prefixing is required. Decks save IDs, so existing decklists keep working through the migration.

**`labels.csv`** lives at the repo root, committed. UTF-8, with a header row:

```csv
id,set,name,element,type
BDS1-EN_0001,Light Starter,Phoenix,light,shadow
BDS1-EN_0008,Light Starter,Jiro,earth,partner
```

Columns:

| Column | Required | Notes |
|--------|----------|-------|
| `id` | yes | Filename stem. Must be unique across the file. |
| `set` | yes | Display string, e.g. `Light Starter`. |
| `name` | yes | Card's printed name. **Not unique** — two distinct cards may share a name. |
| `element` | yes | E.g. `light`, `shadow`. Case-insensitive comparison; preserved case for display. |
| `type` | yes | E.g. `partner`, `event`. Same case rules as element. |

Rows are trimmed on load. Empty `name`/`element`/`type` cells are tolerated (the row still counts as labeled for set membership, but won't appear under the corresponding chip filter).

**In-memory catalog record:**

```python
{
  "id": "BDS1-EN_0008",
  "path": "/abs/path/to/cards_dir/BDS1-EN_0008.jpg",
  "label": {                      # None when the card has no labels.csv row
    "set": "Light Starter",
    "name": "Jiro",
    "element": "earth",
    "type": "partner",
  },
}
```

### Three buckets, three behaviors

Joining the image scan with `labels.csv` produces three classes of record. Each is handled explicitly:

| Bucket | Image | Label row | Behavior |
|--------|-------|-----------|----------|
| **Labeled** | ✓ | ✓ | Fully searchable. Appears in browse, filter results, deck editor. Display shows `name` as primary, `id` as subtitle. |
| **Unlabeled image** | ✓ | ✗ | Visible in browse by default with `id` as the display label and no metadata chips. Selectable into a deck. Falls out of chip-filtered results automatically (no metadata to match). Search box can still find them by id substring. A "Hide unlabeled" toggle removes them from the grid entirely. |
| **Orphaned label** | ✗ | ✓ | Not rendered. Logged once at startup so the CSV's drift is visible. |

Name collisions are first-class: only `id` is unique. The `max_copies_per_card` deck rule keys off `id`, so two distinct cards that share a name each get their own three-copy budget. Browse order is `(set order, name, id)` so duplicates land next to each other in a stable order.

### Filter UI

Above the card grid:

```
Search: [ name or code ]

Set:      [ Light Starter ] [ Shadow Starter ] [ Demo Deck ] [ Set 1 ] [ Set 2 ] [ Parallel Shadows ]
Element:  [ light ] [ shadow ] [ fire ] [ earth ] [ water ] [ wind ]
Type:     [ partner ] [ shadow ] [ event ] ...

[ ] Hide unlabeled
```

Rules:

- Three chip rows: Set, Element, Type. Each chip toggleable, multi-select.
- **Within an axis**: selected chips are OR'd.
- **Across axes**: AND.
- Single search box matches substring against both `id` and `name`, case-insensitive.
- Chip values are auto-populated from values seen in `labels.csv` on startup. No hardcoded enum to maintain. Typos manifest as stray chips next to the correct value — a visible bug that's easy to spot and fix in the CSV.
- Unlabeled cards flow through the same filter pipeline. They have no metadata, so they fail any chip predicate automatically. The search box can still match them by `id` substring.
- "Hide unlabeled" toggle is off by default (unlabeled cards visible). When on, unlabeled cards are excluded from the grid regardless of other filters.
- The existing set dropdown on the browse and deck-edit pages is replaced by the set chip row.

### Soft validation

On load, the labels module:

- Trims whitespace from every cell.
- Lowercases `element` and `type` for comparison and chip grouping; preserves the original casing for display.
- Errors loudly only on **structural** problems: duplicate `id`, missing required column header, unparseable CSV.
- Logs a one-line warning (not an error) for orphaned label rows and for unlabeled image files. Both are normal during incremental labeling.

### Migration: physical flatten

Current layout: `<external>/English/<set>/<file>.jpg`. End state: `<repo>/cards/<file>.jpg`. Migration is a one-time disk operation handled by a new script.

`scripts/flatten_cards.py`:

- Required arg: `--source <path>` (the per-set root, e.g. `/Users/wadestern/stuff/English`).
- Optional: `--dest <path>` (defaults to `<repo>/cards/`, matching the new default `cards_dir`).
- Default behavior: dry-run. Prints the full copy plan as `src → dst` lines plus a summary count. No disk changes.
- `--apply`: copy files. Idempotent — silently skips destination files that already exist *and* are byte-identical; refuses (with an error message) if a destination exists with different bytes.
- `--move`: shorthand for "copy then delete source", opt-in.
- `--force`: overwrite destination on byte mismatch. Off by default.
- Refuses (errors out) on filename collisions across source subfolders. The current scan has zero collisions; this is defensive.

The script never touches `labels.csv` and never touches deck files — IDs are stable across the migration.

### Code changes

**New files**

- `labels.py` — pure-Python CSV loader. Exports `load(path) -> dict[id, LabelRow]`, raises on structural errors, returns a list of warnings (orphans, blank cells) as a second return value.
- `scripts/flatten_cards.py` — migration tool described above.
- `labels.csv` — committed at repo root. The canonical working file: it matches the card scans the maintainer uses, so anyone with the same scans (dropped into `cards/`) gets a fully labeled catalog with zero config. Also serves as the example for users with different scans.
- Test files (see Testing).

**Modified files**

- `catalog.py`: `build()` becomes flat (one-level `os.listdir` over `cards_dir`, no per-set walk). After the image scan it loads `labels.csv` and joins. Adds `labeled_count`, `unlabeled_count`, `orphaned_label_count` to its return dict. Adds `elements_seen()`, `types_seen()` accessors for the chip rows.
- `config.py`:
  - Default `cards_dir` changes from `<APP_DIR>/../English` to `<APP_DIR>/cards`. Env var `BD_CARDS_DIR` and `config.local.json:cards_dir` overrides are unchanged.
  - Adds `labels_path()` resolved from (env `BD_LABELS_PATH` || `config.local.json:labels_path` || `<APP_DIR>/labels.csv`).
  - `EXCLUDED_SETS` becomes unused and is removed (sets are now derived from `labels.csv`, not folder names).
- `app.py`:
  - `/api/status` returns the new counts and `elements`/`types` lists.
  - `/api/cards` returns the joined records grouped into the bucket structure the frontend needs.
  - No new routes.
- `templates/cards.html`, `templates/deck.html`: replace set dropdown markup with three chip rows (Set, Element, Type) and the "Show unlabeled" toggle. Search input gains placeholder copy reflecting name-or-code matching.
- `static/*.js` (whichever file holds the browse/filter logic): chip click toggles selection state; filter pipeline becomes AND-across-axes / OR-within. Card tiles render `name` as primary label and `id` as subtitle when labeled; render `id` as primary with no subtitle when unlabeled.
- `render.py`: deck-image export header and per-card caption use `name` when available, fall back to `id`. No other rendering changes.
- `README.md`: short section on `labels.csv` and the flatten script. Update the "what's in the repo" section so it's clear the labels CSV is committed and the card images are not.
- `.gitignore`:
  - Add `/cards/` (the new default cards directory inside the repo).
  - Remove `/English/` (no longer the default; the wildcards `*.jpg/*.jpeg/*.png` still cover anyone who keeps using that name).
  - `*.jpg/*.jpeg/*.png` stay as the belt-and-braces rule that prevents card images from being committed from anywhere in the tree.

### What gets published in the repo

- **Committed:** `labels.csv`, the migration script, code changes, README updates.
- **Not committed:** card images. The `cards/` folder lives inside the repo by default but is gitignored. Defence in depth: even if someone removes `/cards/` from `.gitignore`, the `*.jpg/*.jpeg/*.png` wildcards still block individual images from being staged. The migration script writes to `<repo>/cards/` by default, which is the gitignored path.

### Error handling and edge cases

- **Missing `labels.csv`**: app starts, every card falls into the unlabeled bucket, banner logs `Labels: labels.csv not found`. Chip rows render but contain no chips (no labeled values to populate them). Browse grid still works; users can still build decks by id.
- **Empty `cards_dir`**: existing behavior (banner says `Cards dir : <path>` and `Found: 0 cards`) is preserved.
- **Duplicate `id` rows in CSV**: load fails loudly at startup with the offending IDs printed. App refuses to start. This is a developer error, not a user error.
- **Missing required column header**: same — refuse to start, print which column is missing.
- **Unlabeled cards sort order**: they have no set, so they sort after every labeled card. Sort key within the unlabeled group is `id`.
- **Existing decks reference an unlabeled card**: works fine — decks reference `id`, which is bucket-agnostic.
- **Existing decks reference a missing card**: already handled today via `missing` in the deck payload; behavior unchanged.

### Testing

Unit tests, pytest-based (add `pytest` to `requirements.txt`).

- `tests/test_labels.py`: parses a tiny CSV fixture; verifies trimming, lowercasing for comparison, duplicate-id detection, missing-column detection, blank-cell tolerance, orphan-warning list.
- `tests/test_catalog.py`: builds a catalog against a `tmp_path` folder of fake image files plus a fixture CSV; covers the three buckets (labeled / unlabeled image / orphaned label) and the auto-derived `elements_seen` / `types_seen` lists.
- `tests/test_filter.py`: pure in-memory filter function with a tiny record set; asserts AND-across-axes, OR-within, search-substring against name and id, and the "show unlabeled" gate.

No end-to-end browser tests. The manual smoke path (load home, browse cards, build a deck, export image) was verified before this design and is sufficient for v1.

## Rollout / order of work

Implementation plan will sequence these. Listing here so the spec is self-contained:

1. Add `labels.py` + tests. No app wiring yet.
2. Build `labels.csv` for the current 272 cards (manual labeling pass; happens out-of-band by the user, not in code).
3. Wire `catalog.build()` to use `labels.py`; update `/api/status` and `/api/cards`. Keep the old set-dropdown UI working against the new payload.
4. Replace the browse-page filter UI with chip rows + new search behavior.
5. Mirror the same UI changes onto the deck-edit page.
6. Switch deck-image export to prefer `name`.
7. Write `scripts/flatten_cards.py`; run it against the user's `English/` folder, with `<repo>/cards/` as the destination.
8. README updates: new "Setup" flow (clone repo → drop scans into `cards/` → run), and brief notes on `labels.csv` and the flatten script.

Step 2 (manual labeling) and step 7 (flatten) are the only physical-world steps; the rest is code.
