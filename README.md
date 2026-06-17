# 🐉 Blue Dragon Deck Builder

A small **local** web app for building decks for the Blue Dragon trading card
game and exporting a single shareable image of the deck (staggered card stacks
with copy counts), auto-sized to stay under Discord's 10 MB limit.

Everything runs on your own machine — nothing is uploaded anywhere, and your
card images never leave your disk.

---

## What you need

1. **Python 3.10+** — <https://www.python.org/downloads/> (tick *"Add Python to
   PATH"* during install).
2. **The card image pack.** Not in this repo (card images are gitignored). The
   maintainer publishes a curated pack of deduplicated scans separately — see
   the project's distribution link. Download it and unzip it into the `cards/`
   folder at the root of this repo. Each image's filename stem is its card ID
   (e.g. `BDS1-EN_0008.jpg` → card `BDS1-EN_0008`).

## Setup

1. Clone or download this repo.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Drop the card images into `<repo>/cards/`.

## Card labels

Metadata for the card scans lives in `labels.csv` at the repo root. Columns are
`id, set, name, element, type`. This file is committed; if your scans match the
maintainer's, you'll get name search and element/type filters for free. If
your scans differ, you can edit `labels.csv` directly — or label cards from
inside the app.

**Labeling from inside the app.** Click any card thumbnail (on Browse Cards or
Edit Deck) and the card opens at full size with an editor panel alongside.
Pick a Type, a Set, and the Element(s); changes autosave back to `labels.csv`.
Walk between cards in the current filtered view with ◀ / ▶ (or the arrow keys)
for batch labeling.

Vocabularies:

- **Type**: Shadow, Partner, Skill, Command.
- **Element / attribute**: light, dark, fire, water, earth, wind, none.
  Only Shadow and Partner cards carry an element; the editor hides the
  element block for Commands and Skills.
- **Set**: a card can belong to multiple sets (e.g. reprinted in both
  starter decks). Tick every set the card appears in. The six seeded sets
  show by default; click "+ new" above the set list to add a new one.

Cards with no `labels.csv` row still appear in the browse grid — they show
their ID instead of a printed name and don't match any chip filter. The
"Hide unlabeled" toggle removes them from the grid entirely.

## Card-folder location override (optional)

If you'd rather keep your scans somewhere outside the project (e.g. on an
external drive), point the app at them with **either**:

1. Environment variable **`BD_CARDS_DIR`**
2. A file named **`config.local.json`** next to `app.py`:
   ```json
   { "cards_dir": "/path/to/your/cards" }
   ```

The labels file location can be overridden with `BD_LABELS_PATH` or
`labels_path` in `config.local.json` (default: `<repo>/labels.csv`).

Optional keys in `config.local.json`:

| Key | Default | Meaning |
|-----|---------|---------|
| `cards_dir` | `./cards` | Path to the flat folder of card images |
| `labels_path` | `./labels.csv` | Path to the labels CSV |
| `max_copies_per_card` | `3` | Deck rule: max copies of one card |
| `deck_target_size` | `40` | Deck size the counter aims for |
| `export_max_bytes` | `10485760` | Image export size cap (10 MB) |
| `prewarm_thumbs` | `true` | Build the thumbnail cache in the background on startup so browsing is instant |
| `prewarm_views` | `false` | Also pre-build the larger zoom/export cache (~250 MB; only speeds up first zoom/export) |

---

## Run it

- **Windows:** double-click **`run.bat`** (installs dependencies on first run,
  then launches and opens your browser).
- **Any OS / manual:**
  ```bash
  pip install -r requirements.txt
  python app.py
  ```
  Then open <http://127.0.0.1:5000>.

---

## Using the app

- **Decks** (home) — create, open, or delete decklists. Each deck is saved as a
  JSON file in `decks/`.
- **Browse Cards** — scroll all cards, filter by set, type a code to filter,
  click any card to zoom in and read it.
- **Edit a deck** — left panel is the card browser with `− n +` controls to set
  how many copies to run; right panel shows your decklist with live counts, a
  `37 / 40` counter, per-card trim/remove, and **⬇ Download deck image**.

The exported image lays out every unique card in a grid, fans duplicate copies
behind the front card with an `×N` badge, and is automatically scaled/compressed
to fit under the size limit.

---

## What is and isn't in this repo

This is just the application code. The `.gitignore` keeps the following **out** of
the repository, so nothing personal or copyrighted is published:

- **Card images** (`*.jpg/*.jpeg/*.png`, the `English/` folder) — bring your own.
- **Your decklists** (`decks/*.json`) — they stay on your machine.
- **The thumbnail/view cache** (`cache/`) — rebuilt automatically.
- **Your local card path** (`config.local.json`) — each user sets their own.

To use it, clone the repo, point it at your own card images (see *Configure the
card folder* above), and run it. You need Python and your own copy of the scans.

## Roadmap

- Card naming/labelling + search by name (currently filter by set + code).
- Optional `.exe` bundle so friends don't need Python installed.

---

## Disclaimer

This is an **unofficial, non-commercial, fan-made** tool with no affiliation
with — and no endorsement by — the creators, publishers, or rights holders of
the Blue Dragon trading card game or franchise. **Blue Dragon**, its card
images, names, artwork, and all related assets are the property of their
respective owners. This repository contains **no** card images or game assets;
you must supply your own from cards you legally own.

## License

Application source code is released under the **MIT License** — see
[`LICENSE`](LICENSE). The license covers the code only, not any game assets.
