# Card labels and filterable catalog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layer a CSV-driven metadata layer (name, set, element, type) over the existing card image collection, with chip-bar filtering on browse and deck-edit pages, soft validation, three-bucket handling for labeled/unlabeled/orphaned records, and a one-time disk flatten into a gitignored `<repo>/cards/` folder.

**Architecture:** New `labels.py` module loads `labels.csv` (committed at repo root) and joins it into the in-memory `catalog`. Frontend filter logic moves to a shared `static/filters.js` so cards.html and deck.html stop duplicating it. A one-time `scripts/flatten_cards.py` copies card images from the user's nested per-set folders into a flat `<repo>/cards/` folder, which becomes the new default `cards_dir`.

**Tech Stack:** Python 3.10+, Flask 3, Pillow, vanilla JS, CSV via the stdlib `csv` module, pytest for unit tests.

**Reference spec:** `docs/superpowers/specs/2026-06-17-card-labels-design.md`

**Two minor deviations from the spec, with rationale:**

1. The spec calls for `tests/test_filter.py` (Python unit tests for the filter pipeline). The filter pipeline lives in JS in the new architecture. Adding a JS test framework just for this is YAGNI. The filter functions get extracted into a clean `static/filters.js` module; manual browser smoke covers verification.
2. The spec mentions "per-card caption" in the deck-image export. The brainstorm session explicitly descoped this ("name is fine on the export, since duplicates of the same name are visually distinguishable by art"). The image export gets only the necessary sort-key fix to tolerate unlabeled cards; no new caption text is added.

---

## Task 1: Pytest infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add pytest to requirements.txt**

Edit `requirements.txt` so it reads:

```
Flask>=3.0
Pillow>=10.0
pytest>=8.0
```

- [ ] **Step 2: Install it into the existing venv**

Run: `.venv/bin/pip install -q -r requirements.txt`
Expected: pytest is installed; no errors.

- [ ] **Step 3: Create tests/__init__.py (empty file)**

Run: `mkdir -p tests && touch tests/__init__.py`

- [ ] **Step 4: Write a sanity test**

Create `tests/test_smoke.py`:

```python
def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 5: Run it and verify it passes**

Run: `.venv/bin/pytest -q`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/__init__.py tests/test_smoke.py
git -c commit.gpgsign=false commit -m "Add pytest dev dependency and tests/ skeleton"
```

---

## Task 2: labels.py — CSV loader

**Files:**
- Create: `labels.py`
- Create: `tests/test_labels.py`

Behavior: `load(path) -> tuple[dict[str, LabelRow], list[str]]`. Returns a dict keyed by id and a list of warning strings. Raises `LabelError` (subclass of `ValueError`) on structural problems: duplicate id, missing required column, malformed CSV.

`LabelRow` is a frozen dataclass with fields: `id, set, name, element, type` (all strings, stored as typed but whitespace-trimmed). Empty `name/element/type` cells are tolerated (count as labeled for set membership but don't appear under that chip filter).

If the file does not exist, `load()` returns `({}, ["labels.csv not found at <abs path>"])` — no exception.

- [ ] **Step 1: Write failing tests for the loader**

Create `tests/test_labels.py`:

```python
import textwrap

import pytest

import labels


def write_csv(tmp_path, content):
    p = tmp_path / "labels.csv"
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


def test_load_basic(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,shadow
        BDS1-EN_0008,Light Starter,Jiro,earth,partner
    """)
    rows, warnings = labels.load(str(p))
    assert set(rows.keys()) == {"BDS1-EN_0001", "BDS1-EN_0008"}
    jiro = rows["BDS1-EN_0008"]
    assert jiro.id == "BDS1-EN_0008"
    assert jiro.set == "Light Starter"
    assert jiro.name == "Jiro"
    assert jiro.element == "earth"
    assert jiro.type == "partner"
    assert warnings == []


def test_load_trims_whitespace(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
         BDS1-EN_0001 , Light Starter , Phoenix , light , shadow
    """)
    rows, _ = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == "Light Starter"
    assert row.name == "Phoenix"
    assert row.element == "light"


def test_blank_cells_allowed_and_warned(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,,,
    """)
    rows, warnings = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == "Light Starter"
    assert row.name == ""
    assert row.element == ""
    assert row.type == ""
    assert any("blank" in w.lower() for w in warnings)


def test_duplicate_id_raises(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,shadow
        BDS1-EN_0001,Light Starter,Phoenix2,light,event
    """)
    with pytest.raises(labels.LabelError) as exc:
        labels.load(str(p))
    assert "BDS1-EN_0001" in str(exc.value)


def test_missing_required_column_raises(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element
        BDS1-EN_0001,Light Starter,Phoenix,light
    """)
    with pytest.raises(labels.LabelError) as exc:
        labels.load(str(p))
    assert "type" in str(exc.value)


def test_missing_file_returns_empty_with_warning(tmp_path):
    rows, warnings = labels.load(str(tmp_path / "nope.csv"))
    assert rows == {}
    assert len(warnings) == 1
    assert "not found" in warnings[0].lower()
```

- [ ] **Step 2: Run the tests and verify they all fail**

Run: `.venv/bin/pytest tests/test_labels.py -v`
Expected: 6 failures (ImportError for `labels` module).

- [ ] **Step 3: Implement labels.py**

Create `labels.py`:

```python
"""Parse the labels.csv metadata file into in-memory rows.

Returned by load():
  rows:     dict[id, LabelRow]  -- whitespace-trimmed, raw-case fields
  warnings: list[str]           -- non-fatal issues (missing file, blank cells, ...)

Raises LabelError on structural problems (duplicate id, missing required column,
malformed CSV)."""
import csv
import os
from dataclasses import dataclass


REQUIRED_COLUMNS = ("id", "set", "name", "element", "type")


class LabelError(ValueError):
    """Structural problem with labels.csv that prevents the app from running."""


@dataclass(frozen=True)
class LabelRow:
    id: str
    set: str
    name: str
    element: str
    type: str


def load(path):
    if not os.path.isfile(path):
        return {}, [f"labels.csv not found at {os.path.abspath(path)}"]

    rows = {}
    warnings = []

    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise LabelError(f"{path}: file is empty (expected header row)")

        header = [h.strip() for h in header]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise LabelError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        idx = {c: header.index(c) for c in REQUIRED_COLUMNS}

        for line_no, raw in enumerate(reader, start=2):
            if not raw or all(not (c or "").strip() for c in raw):
                continue
            cells = [(raw[i].strip() if i < len(raw) else "") for i in range(len(header))]
            row = LabelRow(
                id=cells[idx["id"]],
                set=cells[idx["set"]],
                name=cells[idx["name"]],
                element=cells[idx["element"]],
                type=cells[idx["type"]],
            )
            if not row.id:
                warnings.append(f"{path}:{line_no} blank id, row skipped")
                continue
            if row.id in rows:
                raise LabelError(
                    f"{path}:{line_no} duplicate id {row.id!r} "
                    f"(also at line where it was first seen)"
                )
            blanks = [f for f in ("name", "element", "type")
                      if not getattr(row, f)]
            if blanks:
                warnings.append(
                    f"{path}:{line_no} {row.id} has blank {', '.join(blanks)}"
                )
            rows[row.id] = row

    return rows, warnings
```

- [ ] **Step 4: Run the tests and verify all 6 pass**

Run: `.venv/bin/pytest tests/test_labels.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add labels.py tests/test_labels.py
git -c commit.gpgsign=false commit -m "Add labels.py CSV loader with structural error checks"
```

---

## Task 3: scripts/flatten_cards.py — migration tool

**Files:**
- Create: `scripts/__init__.py` (empty; lets pytest import the script)
- Create: `scripts/flatten_cards.py`
- Create: `tests/test_flatten.py`

Behavior summary (from spec):

- Required arg: `--source <path>`.
- Optional: `--dest <path>` (defaults to `<repo>/cards/`).
- Default mode: dry-run. Prints `src → dst` lines plus a summary; no disk changes.
- `--apply`: copy files. Idempotent (skips byte-identical destinations); errors on byte mismatch.
- `--move`: copy + delete source on success.
- `--force`: overwrite mismatched destinations.
- Errors out on filename collisions across source subfolders.

- [ ] **Step 1: Write failing tests for the script's core function**

Create `tests/test_flatten.py`:

```python
import os
import shutil

import pytest

from scripts import flatten_cards


def make_source(tmp_path):
    """Build a nested per-set source folder and return (root, expected_files)."""
    root = tmp_path / "English"
    (root / "Light Starter").mkdir(parents=True)
    (root / "Shadow Starter").mkdir(parents=True)
    (root / "Light Starter" / "BDS1-EN_0001.jpg").write_bytes(b"a")
    (root / "Light Starter" / "BDS1-EN_0002.jpg").write_bytes(b"b")
    (root / "Shadow Starter" / "BDS2-EN_0001.jpg").write_bytes(b"c")
    (root / "Light Starter" / "notes.txt").write_text("non-image")
    return str(root), ["BDS1-EN_0001.jpg", "BDS1-EN_0002.jpg", "BDS2-EN_0001.jpg"]


def test_plan_lists_every_image(tmp_path):
    src, expected = make_source(tmp_path)
    dst = str(tmp_path / "cards")
    plan = flatten_cards.build_plan(src, dst)
    src_names = sorted(os.path.basename(p.src) for p in plan)
    assert src_names == sorted(expected)
    for entry in plan:
        assert entry.dst.startswith(dst)


def test_collision_across_sets_raises(tmp_path):
    src, _ = make_source(tmp_path)
    (tmp_path / "English" / "Shadow Starter" / "BDS1-EN_0001.jpg").write_bytes(b"dup")
    with pytest.raises(flatten_cards.CollisionError) as exc:
        flatten_cards.build_plan(src, str(tmp_path / "cards"))
    assert "BDS1-EN_0001.jpg" in str(exc.value)


def test_apply_copies_files(tmp_path):
    src, expected = make_source(tmp_path)
    dst = tmp_path / "cards"
    plan = flatten_cards.build_plan(src, str(dst))
    flatten_cards.apply(plan, move=False, force=False)
    assert sorted(p.name for p in dst.iterdir()) == sorted(expected)
    # source untouched
    assert (tmp_path / "English" / "Light Starter" / "BDS1-EN_0001.jpg").exists()


def test_apply_is_idempotent_on_identical_bytes(tmp_path):
    src, _ = make_source(tmp_path)
    dst = tmp_path / "cards"
    plan = flatten_cards.build_plan(src, str(dst))
    flatten_cards.apply(plan, move=False, force=False)
    # second run: identical destination contents, should be a no-op (no exception)
    flatten_cards.apply(plan, move=False, force=False)


def test_apply_errors_on_byte_mismatch_without_force(tmp_path):
    src, _ = make_source(tmp_path)
    dst = tmp_path / "cards"
    dst.mkdir()
    (dst / "BDS1-EN_0001.jpg").write_bytes(b"DIFFERENT")
    plan = flatten_cards.build_plan(src, str(dst))
    with pytest.raises(flatten_cards.DestinationConflict):
        flatten_cards.apply(plan, move=False, force=False)


def test_apply_force_overwrites_mismatch(tmp_path):
    src, _ = make_source(tmp_path)
    dst = tmp_path / "cards"
    dst.mkdir()
    (dst / "BDS1-EN_0001.jpg").write_bytes(b"DIFFERENT")
    plan = flatten_cards.build_plan(src, str(dst))
    flatten_cards.apply(plan, move=False, force=True)
    assert (dst / "BDS1-EN_0001.jpg").read_bytes() == b"a"


def test_move_deletes_source(tmp_path):
    src, _ = make_source(tmp_path)
    dst = tmp_path / "cards"
    plan = flatten_cards.build_plan(src, str(dst))
    flatten_cards.apply(plan, move=True, force=False)
    assert not (tmp_path / "English" / "Light Starter" / "BDS1-EN_0001.jpg").exists()
```

- [ ] **Step 2: Run the tests — they should fail with ImportError**

Run: `.venv/bin/pytest tests/test_flatten.py -v`
Expected: All fail (cannot import `scripts.flatten_cards`).

- [ ] **Step 3: Implement the script**

Create `scripts/__init__.py` (empty).

Create `scripts/flatten_cards.py`:

```python
"""One-time migration: copy card images from a nested per-set source folder
into a single flat destination folder.

Default behavior is dry-run (prints the plan, no disk changes). Use --apply
to copy, --move to copy-then-delete-source, --force to overwrite a destination
file that exists with different bytes.

Run via:  python -m scripts.flatten_cards --source <path> [options]
"""
import argparse
import filecmp
import os
import shutil
import sys
from dataclasses import dataclass


IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


class CollisionError(RuntimeError):
    """Two source files would land on the same destination filename."""


class DestinationConflict(RuntimeError):
    """Destination file exists with different bytes and --force was not passed."""


@dataclass(frozen=True)
class PlanEntry:
    src: str
    dst: str


def _is_image(name):
    _, ext = os.path.splitext(name)
    return ext.lower() in IMAGE_EXTS


def build_plan(source, dest):
    """Walk `source` (one level of subdirs) and produce the list of
    src→dst copies that would flatten it into `dest`.

    Raises CollisionError if any filename appears in more than one subdir.
    """
    if not os.path.isdir(source):
        raise FileNotFoundError(f"source not found: {source}")

    seen = {}                       # basename -> src abs path
    for entry in sorted(os.listdir(source)):
        sub = os.path.join(source, entry)
        if not os.path.isdir(sub):
            continue
        for fname in sorted(os.listdir(sub)):
            if not _is_image(fname):
                continue
            src = os.path.join(sub, fname)
            if fname in seen:
                raise CollisionError(
                    f"{fname} appears in both "
                    f"{os.path.dirname(seen[fname])} and {sub}"
                )
            seen[fname] = src

    return [PlanEntry(src=src, dst=os.path.join(dest, name))
            for name, src in sorted(seen.items())]


def _files_match(a, b):
    return os.path.isfile(b) and filecmp.cmp(a, b, shallow=False)


def apply(plan, move, force):
    """Execute the plan. Copies (or moves) each src→dst; idempotent when the
    destination matches; raises DestinationConflict on mismatch unless force."""
    if not plan:
        return
    os.makedirs(os.path.dirname(plan[0].dst), exist_ok=True)
    for entry in plan:
        os.makedirs(os.path.dirname(entry.dst), exist_ok=True)
        if os.path.isfile(entry.dst):
            if _files_match(entry.src, entry.dst):
                if move:
                    os.remove(entry.src)
                continue
            if not force:
                raise DestinationConflict(
                    f"{entry.dst} exists with different bytes; pass --force to overwrite"
                )
        if move:
            shutil.move(entry.src, entry.dst)
        else:
            shutil.copy2(entry.src, entry.dst)


def _print_plan(plan, dest):
    print(f"Source files: {len(plan)}")
    print(f"Destination : {os.path.abspath(dest)}")
    for entry in plan:
        print(f"  {entry.src}  ->  {entry.dst}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="Folder containing per-set subfolders of card images.")
    parser.add_argument("--dest", default=None,
                        help="Flat destination folder. Defaults to <repo>/cards/.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually copy files (default: dry-run).")
    parser.add_argument("--move", action="store_true",
                        help="Delete the source file after each successful copy.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite destination files with differing bytes.")
    args = parser.parse_args(argv)

    if args.dest is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        args.dest = os.path.join(repo_root, "cards")

    try:
        plan = build_plan(args.source, args.dest)
    except (FileNotFoundError, CollisionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not args.apply:
        _print_plan(plan, args.dest)
        print("\n(dry-run) pass --apply to copy these files.")
        return 0

    try:
        apply(plan, move=args.move, force=args.force)
    except DestinationConflict as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    print(f"Applied: {len(plan)} files → {os.path.abspath(args.dest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests and verify everything passes**

Run: `.venv/bin/pytest -v`
Expected: All tests pass (smoke + labels + flatten = 14 tests).

- [ ] **Step 5: Dry-run against the real card folder**

Run:
```bash
.venv/bin/python -m scripts.flatten_cards --source /Users/wadestern/stuff/English
```

Expected output: a list of 272 `src → dst` lines, summary `Source files: 272`, destination `/Users/wadestern/stuff/blue-dragon-deckbuilder/cards`, and a closing `(dry-run) pass --apply to copy these files.` line. No filesystem changes.

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/flatten_cards.py tests/test_flatten.py
git -c commit.gpgsign=false commit -m "Add scripts/flatten_cards.py migration tool"
```

---

## Task 4: Run the migration (no commit)

This is a one-time disk operation, not a code change. After it runs, `<repo>/cards/` contains all 272 card images at the top level. The app is still configured to read from `../English` at this point, so it keeps working.

- [ ] **Step 1: Stop the running dev server if it's still up**

If you have the Flask server running from earlier (PID was reported as 79399 in initial setup), kill it:
```bash
pkill -f "python app.py" || true
```

- [ ] **Step 2: Apply the migration**

Run:
```bash
.venv/bin/python -m scripts.flatten_cards \
  --source /Users/wadestern/stuff/English \
  --apply
```

Expected output: `Applied: 272 files → /Users/wadestern/stuff/blue-dragon-deckbuilder/cards`.

- [ ] **Step 3: Verify the flat folder is populated**

Run:
```bash
ls cards | wc -l
```

Expected: `272`.

- [ ] **Step 4: Confirm the source folder is untouched**

Run:
```bash
ls /Users/wadestern/stuff/English
```

Expected: the 7 original subdirectories are still present (we copied, didn't move).

No commit — `cards/` will be gitignored once we update `.gitignore` in Task 12.

---

## Task 5: config.py + catalog.py — flat scan with label join

**Files:**
- Modify: `config.py`
- Modify: `catalog.py`
- Create: `tests/test_catalog.py`

This task bundles the config default change and the catalog refactor into one commit. They have to land together because flipping the default cards_dir without updating the catalog (or vice versa) breaks the running app.

- [ ] **Step 1: Write failing tests for the new catalog shape**

Create `tests/test_catalog.py`:

```python
import os

import pytest


@pytest.fixture
def fake_cards(tmp_path, monkeypatch):
    """Set up a temp cards_dir + labels.csv and reload config + catalog."""
    cards = tmp_path / "cards"
    cards.mkdir()
    for fname in ("BDS1-EN_0001.jpg", "BDS1-EN_0002.jpg", "BDS1-EN_9999.jpg"):
        (cards / fname).write_bytes(b"x")
    (cards / "ignoreme.txt").write_text("not an image")

    labels_csv = tmp_path / "labels.csv"
    labels_csv.write_text(
        "id,set,name,element,type\n"
        "BDS1-EN_0001,Light Starter,Phoenix,Light,Shadow\n"
        "BDS1-EN_0002,Light Starter,Jiro,earth,partner\n"
        "BDS1-EN_8888,Light Starter,Ghost,light,event\n",   # orphan
        encoding="utf-8",
    )

    monkeypatch.setenv("BD_CARDS_DIR", str(cards))
    monkeypatch.setenv("BD_LABELS_PATH", str(labels_csv))

    import importlib
    import config
    import catalog
    importlib.reload(config)
    importlib.reload(catalog)
    return catalog


def test_buckets_labeled_unlabeled_orphan(fake_cards):
    catalog = fake_cards
    summary = catalog.build()
    assert summary["card_count"] == 3            # only image files
    assert summary["labeled_count"] == 2          # 0001 and 0002
    assert summary["unlabeled_count"] == 1        # 9999
    assert summary["orphaned_label_count"] == 1   # 8888

    rec = catalog.get("BDS1-EN_0001")
    assert rec["label"].name == "Phoenix"
    assert rec["label"].set == "Light Starter"

    rec = catalog.get("BDS1-EN_9999")
    assert rec["label"] is None

    assert catalog.get("BDS1-EN_8888") is None    # orphan not present


def test_seen_values_dedupe_case_insensitive(fake_cards):
    catalog = fake_cards
    catalog.build()
    # "Light"/"light" map to same chip — display picks first occurrence.
    elements = catalog.elements_seen()
    assert len(elements) == 1
    assert elements[0].lower() == "light"

    types = catalog.types_seen()
    assert sorted(t.lower() for t in types) == ["partner", "shadow"]


def test_sets_seen_from_labels(fake_cards):
    catalog = fake_cards
    catalog.build()
    assert catalog.sets_seen() == ["Light Starter"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.venv/bin/pytest tests/test_catalog.py -v`
Expected: failures (missing API: `labeled_count`, `elements_seen`, etc.).

- [ ] **Step 3: Update config.py**

Replace `config.py` entirely:

```python
"""Configuration for the Blue Dragon Deck Builder.

Resolution order for the card-image directory:
  1. Environment variable  BD_CARDS_DIR
  2. A local file          config.local.json   ->  {"cards_dir": "..."}
  3. Default               ./cards             (a flat folder inside the project)

Resolution order for the labels CSV:
  1. Environment variable  BD_LABELS_PATH
  2. config.local.json     ->  {"labels_path": "..."}
  3. Default               ./labels.csv        (committed at the repo root)
"""
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_local_config():
    path = os.path.join(APP_DIR, "config.local.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


_local = _load_local_config()


def cards_dir():
    """Absolute path to the flat folder of card images."""
    raw = (
        os.environ.get("BD_CARDS_DIR")
        or _local.get("cards_dir")
        or os.path.join(APP_DIR, "cards")
    )
    return os.path.abspath(raw)


def labels_path():
    """Absolute path to labels.csv."""
    raw = (
        os.environ.get("BD_LABELS_PATH")
        or _local.get("labels_path")
        or os.path.join(APP_DIR, "labels.csv")
    )
    return os.path.abspath(raw)


# Image file extensions treated as cards.
CARD_EXTS = {".jpg", ".jpeg", ".png"}

# Deck rules.
MAX_COPIES_PER_CARD = int(_local.get("max_copies_per_card", 3))
DECK_TARGET_SIZE = int(_local.get("deck_target_size", 40))

# Cache + storage locations.
DECKS_DIR = os.path.join(APP_DIR, "decks")
CACHE_DIR = os.path.join(APP_DIR, "cache")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
VIEW_DIR = os.path.join(CACHE_DIR, "view")

# Cached render sizes (width in px).
THUMB_WIDTH = 320
VIEW_WIDTH = 1400

# Deck image export.
EXPORT_MAX_BYTES = int(_local.get("export_max_bytes", 10 * 1024 * 1024))

# Pre-build the thumbnail cache in the background on startup (fast browsing).
PREWARM_THUMBS = bool(_local.get("prewarm_thumbs", True))
# Also pre-build the larger "view" cache (used by zoom + image export).
PREWARM_VIEWS = bool(_local.get("prewarm_views", False))

for _d in (DECKS_DIR, THUMB_DIR, VIEW_DIR):
    os.makedirs(_d, exist_ok=True)
```

(Changes vs. existing: new default for `cards_dir`, new `labels_path()`, removed `EXCLUDED_SETS`. Everything else preserved.)

- [ ] **Step 4: Rewrite catalog.py**

Replace `catalog.py` entirely:

```python
"""Scan the flat cards folder into an in-memory catalog joined with labels.csv,
and serve cached thumbnails / medium-size views."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import config
import labels

# id -> {"id", "filename", "path", "label": LabelRow | None}
_catalog = {}
_sets = []
_elements = []
_types = []
_lock = threading.Lock()

# Background thumbnail pre-warming progress.
_warm = {"running": False, "done": 0, "total": 0, "phase": "idle"}
_warm_lock = threading.Lock()


def _first_seen_display(values):
    """Dedupe `values` case-insensitively, preserving the first-seen casing.
    Returns the deduped list sorted by lowercase form."""
    by_lower = {}
    for v in values:
        if not v:
            continue
        key = v.lower()
        by_lower.setdefault(key, v)
    return [by_lower[k] for k in sorted(by_lower)]


def build():
    """(Re)scan cards_dir and labels.csv. Safe to call again to pick up changes."""
    root = config.cards_dir()
    rows, label_warnings = labels.load(config.labels_path())

    catalog = {}
    if os.path.isdir(root):
        for fname in sorted(os.listdir(root)):
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in config.CARD_EXTS:
                continue
            catalog[stem] = {
                "id": stem,
                "filename": fname,
                "path": os.path.join(root, fname),
                "label": rows.get(stem),
            }

    labeled = [rec for rec in catalog.values() if rec["label"] is not None]
    unlabeled = [rec for rec in catalog.values() if rec["label"] is None]
    orphaned = [row_id for row_id in rows if row_id not in catalog]

    sets_list = _first_seen_display(rec["label"].set for rec in labeled)
    elements_list = _first_seen_display(rec["label"].element for rec in labeled)
    types_list = _first_seen_display(rec["label"].type for rec in labeled)

    with _lock:
        _catalog.clear()
        _catalog.update(catalog)
        _sets[:] = sets_list
        _elements[:] = elements_list
        _types[:] = types_list

    return {
        "root": root,
        "labels_path": config.labels_path(),
        "exists": os.path.isdir(root),
        "card_count": len(catalog),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "orphaned_label_count": len(orphaned),
        "orphaned_label_ids": sorted(orphaned),
        "sets": sets_list,
        "elements": elements_list,
        "types": types_list,
        "warnings": label_warnings,
    }


def _record_to_api(rec):
    """Public record shape returned over the wire."""
    label = rec["label"]
    return {
        "id": rec["id"],
        "set": label.set if label else None,
        "name": label.name if label else None,
        "element": label.element if label else None,
        "type": label.type if label else None,
    }


def all_cards():
    """List of cards in display order: labeled first (by set, name, id),
    unlabeled last (by id)."""
    with _lock:
        cards = list(_catalog.values())
    set_index = {s: i for i, s in enumerate(_sets)}

    def key(rec):
        label = rec["label"]
        if label is None:
            return (1, "", "", rec["id"])
        return (0, set_index.get(label.set, len(_sets)), label.name.lower(), rec["id"])

    cards.sort(key=key)
    return [_record_to_api(c) for c in cards]


def sets_seen():
    with _lock:
        return list(_sets)


def elements_seen():
    with _lock:
        return list(_elements)


def types_seen():
    with _lock:
        return list(_types)


def get(card_id):
    """Internal accessor — returns the raw record (with `label` object) or None."""
    with _lock:
        return _catalog.get(card_id)


def get_api(card_id):
    """Public accessor — returns the API-shaped dict or None."""
    rec = get(card_id)
    return _record_to_api(rec) if rec else None


def exists(card_id):
    with _lock:
        return card_id in _catalog


# --------------------------------------------------------------------------- #
# Cached resized images (unchanged from previous catalog.py)
# --------------------------------------------------------------------------- #
def _cached_path(card_id, width, cache_dir):
    return os.path.join(cache_dir, f"{card_id}.jpg")


def cached_image(card_id, width, cache_dir):
    card = get(card_id)
    if card is None or not os.path.isfile(card["path"]):
        return None
    out = _cached_path(card_id, width, cache_dir)
    src_mtime = os.path.getmtime(card["path"])
    if os.path.isfile(out) and os.path.getmtime(out) >= src_mtime:
        return out
    with Image.open(card["path"]) as im:
        im = im.convert("RGB")
        if im.width > width:
            height = round(im.height * width / im.width)
            im = im.resize((width, height), Image.LANCZOS)
        im.save(out, "JPEG", quality=82, optimize=True)
    return out


def thumb_path(card_id):
    return cached_image(card_id, config.THUMB_WIDTH, config.THUMB_DIR)


def view_path(card_id):
    return cached_image(card_id, config.VIEW_WIDTH, config.VIEW_DIR)


def source_path(card_id):
    card = get(card_id)
    return card["path"] if card else None


# --------------------------------------------------------------------------- #
# Background cache pre-warming (unchanged)
# --------------------------------------------------------------------------- #
def warm_state():
    with _warm_lock:
        return dict(_warm)


def _warm_bump(phase=None):
    with _warm_lock:
        _warm["done"] += 1
        if phase:
            _warm["phase"] = phase


def warm_cache(warm_views=False, workers=None):
    workers = workers or min(8, (os.cpu_count() or 4))
    with _lock:
        ids = list(_catalog.keys())
    jobs = [("thumb", cid) for cid in ids]
    if warm_views:
        jobs += [("view", cid) for cid in ids]
    with _warm_lock:
        _warm.update(running=True, done=0, total=len(jobs), phase="thumbnails")

    def job(item):
        kind, cid = item
        try:
            thumb_path(cid) if kind == "thumb" else view_path(cid)
        except Exception:
            pass
        _warm_bump(phase="views" if kind == "view" else None)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, jobs))

    with _warm_lock:
        _warm.update(running=False, phase="done")


def warm_cache_async(warm_views=False):
    t = threading.Thread(target=warm_cache, kwargs={"warm_views": warm_views},
                         daemon=True)
    t.start()
    return t
```

Key changes from the old `catalog.py`:

- Flat `os.listdir` over `cards_dir` (no per-set subfolder walk).
- Joins each image with the matching `LabelRow` from `labels.load()`.
- New accessors: `sets_seen()`, `elements_seen()`, `types_seen()`, `get_api()`.
- Old `sets()` is renamed to `sets_seen()` — callers (`app.py`) need to be updated in Task 7.
- `all_cards()` returns the new API shape (id + label fields).
- Old shape returned `{id, set}`; new shape returns `{id, set, name, element, type}` with nulls when unlabeled.

- [ ] **Step 5: Run the catalog tests and verify they pass**

Run: `.venv/bin/pytest tests/test_catalog.py -v`
Expected: 3 passed.

- [ ] **Step 6: Smoke test against real data (the app boots and reports sane counts)**

The app's blueprint still imports `catalog.sets` and other old names — it will be broken right after this commit. That's fine, we'll fix it in Task 7. For now just verify the catalog module itself behaves:

Run:
```bash
.venv/bin/python -c "
import catalog
summary = catalog.build()
for k, v in summary.items():
    if not isinstance(v, list):
        print(f'{k}: {v}')
print('sample:', catalog.all_cards()[0])
"
```

Expected output includes `card_count: 272`, `labeled_count: 0`, `unlabeled_count: 272`, `orphaned_label_count: 0` (labels.csv doesn't exist yet so all images are unlabeled), and a sample like `{'id': 'BDS1-EN_0001', 'set': None, 'name': None, 'element': None, 'type': None}`.

- [ ] **Step 7: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: All previously-passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add config.py catalog.py tests/test_catalog.py
git -c commit.gpgsign=false commit -m "Flatten catalog scan and join with labels.csv"
```

---

## Task 6: labels.csv (header) + decks.py — surface name in deck payload

**Files:**
- Create: `labels.csv`
- Modify: `decks.py:get_resolved`

`labels.csv` ships with just the header — the user does the manual labeling pass out-of-band after the code lands. `decks.py:get_resolved` is currently the bridge from a saved deck (just `{id: count}`) to the side-panel payload. Today it returns `{id, set, count}` per card. After this task it returns `{id, set, name, count}`, with `set`/`name` as `None` when the card is unlabeled.

- [ ] **Step 1: Create the empty labels.csv**

Create `labels.csv` at the repo root:

```csv
id,set,name,element,type
```

(One line — the header. No card rows yet.)

- [ ] **Step 2: Patch decks.py:get_resolved**

In `decks.py`, replace the `get_resolved` function body. The current implementation looks at lines roughly 69–89; the replacement:

```python
def get_resolved(deck_id):
    """Deck plus per-card label info, dropping any cards no longer in the catalog."""
    deck = _read(deck_id)
    if deck is None:
        return None
    items = []
    missing = []
    for cid, cnt in deck["cards"].items():
        rec = catalog.get(cid)
        if rec is None:
            missing.append(cid)
            continue
        label = rec["label"]
        items.append({
            "id": cid,
            "set": label.set if label else None,
            "name": label.name if label else None,
            "count": cnt,
        })
    items.sort(key=lambda i: (i["set"] or "~", (i["name"] or "").lower(), i["id"]))
    return {
        "id": deck["id"],
        "name": deck["name"],
        "cards": items,
        "total": sum(i["count"] for i in items),
        "missing": missing,
    }
```

Sort key explanation: `set or "~"` — labeled cards (with real set names) sort before unlabeled ones (where `set` is `None` and we substitute `"~"`, which sorts after every printable letter). Within a set, we sort by lowercase name then id.

- [ ] **Step 3: Smoke test — create a deck via the API and check the payload**

The app still won't start cleanly (Task 7 fixes that); we drive `decks.py` directly:

```bash
.venv/bin/python -c "
import catalog, decks
catalog.build()
deck_id = decks.create('plan-smoke').get('id')
decks.set_card(deck_id, 'BDS1-EN_0001', 2)
print(decks.get_resolved(deck_id))
decks.delete(deck_id)
"
```

Expected output includes `'set': None`, `'name': None`, `'count': 2` (because no labels.csv rows yet) and `'missing': []`.

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add labels.csv decks.py
git -c commit.gpgsign=false commit -m "Surface name in resolved deck payload; ship empty labels.csv"
```

---

## Task 7: app.py — update /api/status and /api/cards

**Files:**
- Modify: `app.py`

The old `catalog.sets()` and old return shapes are gone. Update the Flask routes to use the new accessors and return the new payload shapes.

- [ ] **Step 1: Update app.py**

Edit `app.py` and change the relevant blocks. The full updated file:

```python
"""Blue Dragon Deck Builder — local Flask app.

Run:  python app.py     (or double-click run.bat)
Then open http://127.0.0.1:5000 in your browser.
"""
import io

from flask import (Flask, abort, jsonify, render_template, request,
                   send_file, send_from_directory)

import catalog
import config
import decks
import render

app = Flask(__name__)

_scan = catalog.build()


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    return render_template("index.html", scan=_scan)


@app.route("/cards")
def cards_page():
    return render_template("cards.html")


@app.route("/deck/<deck_id>")
def deck_page(deck_id):
    if decks.get(deck_id) is None:
        abort(404)
    return render_template("deck.html", deck_id=deck_id,
                           max_copies=config.MAX_COPIES_PER_CARD,
                           target=config.DECK_TARGET_SIZE)


# --------------------------------------------------------------------------- #
# Card catalog API
# --------------------------------------------------------------------------- #
@app.route("/api/status")
def api_status():
    return jsonify(_scan)


@app.route("/api/cards")
def api_cards():
    return jsonify({
        "cards": catalog.all_cards(),
        "sets": catalog.sets_seen(),
        "elements": catalog.elements_seen(),
        "types": catalog.types_seen(),
    })


@app.route("/api/cache/status")
def api_cache_status():
    return jsonify(catalog.warm_state())


@app.route("/api/card/<card_id>/thumb")
def api_thumb(card_id):
    path = catalog.thumb_path(card_id)
    if not path:
        abort(404)
    return send_file(path, mimetype="image/jpeg")


@app.route("/api/card/<card_id>/view")
def api_view(card_id):
    path = catalog.view_path(card_id)
    if not path:
        abort(404)
    return send_file(path, mimetype="image/jpeg")


# --------------------------------------------------------------------------- #
# Decks API (unchanged from previous app.py)
# --------------------------------------------------------------------------- #
@app.route("/api/decks", methods=["GET", "POST"])
def api_decks():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        deck = decks.create(body.get("name", "Untitled Deck"))
        return jsonify({"id": deck["id"], "name": deck["name"]}), 201
    return jsonify(decks.list_decks())


@app.route("/api/decks/<deck_id>", methods=["GET", "PUT", "DELETE"])
def api_deck(deck_id):
    if request.method == "DELETE":
        if not decks.delete(deck_id):
            abort(404)
        return ("", 204)
    if request.method == "PUT":
        body = request.get_json(silent=True) or {}
        if decks.update(deck_id, name=body.get("name"), cards=body.get("cards")) is None:
            abort(404)
    deck = decks.get_resolved(deck_id)
    if deck is None:
        abort(404)
    return jsonify(deck)


@app.route("/api/decks/<deck_id>/card", methods=["POST"])
def api_deck_card(deck_id):
    body = request.get_json(silent=True) or {}
    card_id = body.get("card_id")
    count = body.get("count")
    if not card_id or count is None:
        abort(400)
    if decks.set_card(deck_id, card_id, count) is None:
        abort(404)
    return jsonify(decks.get_resolved(deck_id))


@app.route("/api/decks/<deck_id>/image")
def api_deck_image(deck_id):
    deck = decks.get(deck_id)
    if deck is None:
        abort(404)
    try:
        data, info = render.render_deck(deck)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    resp = send_file(io.BytesIO(data), mimetype="image/jpeg",
                     as_attachment=True, download_name=f"{deck_id}.jpg")
    resp.headers["X-Under-Limit"] = "1" if info["under_limit"] else "0"
    return resp


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #
def _print_banner():
    print(f"Cards dir : {_scan['root']}")
    print(f"Found     : {_scan['card_count']} images "
          f"({_scan['labeled_count']} labeled, "
          f"{_scan['unlabeled_count']} unlabeled)")
    print(f"Labels    : {_scan['labels_path']} "
          f"({_scan['labeled_count']} rows used, "
          f"{_scan['orphaned_label_count']} orphaned)")
    for w in _scan.get("warnings", []):
        print(f"  warn: {w}")
    print()
    print("Open your browser to:  http://127.0.0.1:5000   (Ctrl+C to stop)")


if __name__ == "__main__":
    _print_banner()
    if config.PREWARM_THUMBS:
        catalog.warm_cache_async(warm_views=config.PREWARM_VIEWS)
    app.run(host="127.0.0.1", port=5000, debug=False)
```

Diff vs the previous `app.py`:

- `/cards` no longer receives `sets=` (the template stops needing it — handled in Task 9).
- `/deck/<id>` no longer receives `sets=`.
- `/api/status` returns the full `_scan` summary (which now includes the new counts and lists).
- `/api/cards` returns the new shape (cards with full label fields, plus sets/elements/types lists).
- Startup banner reports the new counts.

Other routes are unchanged.

Note: the old `app.py` may not have had a `_print_banner` block (the existing startup banner was inline). Compare with the previous version and preserve any small lines you find — but the body above is sufficient.

- [ ] **Step 2: Boot the server and verify it starts**

Run in one shell:
```bash
.venv/bin/python app.py > /tmp/bd-app.log 2>&1 &
sleep 2
curl -s http://127.0.0.1:5000/api/status | python3 -m json.tool | head -20
```

Expected: a JSON status response listing `card_count: 272`, `labeled_count: 0`, `unlabeled_count: 272`, and empty `sets`/`elements`/`types` arrays (since `labels.csv` has no rows yet).

- [ ] **Step 3: Verify /api/cards still returns 272 items**

Run:
```bash
curl -s http://127.0.0.1:5000/api/cards | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('cards:', len(d['cards']))
print('first:', d['cards'][0])
print('sets seen:', d['sets'])
"
```

Expected: `cards: 272`, first card with `set/name/element/type` all `None`, empty `sets` list.

- [ ] **Step 4: Stop the server**

```bash
pkill -f "python app.py" || true
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add app.py
git -c commit.gpgsign=false commit -m "Update app routes to new catalog + label shape"
```

---

## Task 8: Shared filter module — static/filters.js

**Files:**
- Create: `static/filters.js`

Pure-JS filter pipeline reused by `cards.html` and `deck.html`. Exports a small set of helpers that operate on the card-list shape returned by `/api/cards`.

- [ ] **Step 1: Create static/filters.js**

```javascript
// Shared filter pipeline for the card grid (used by cards.html and deck.html).
//
// A card has the shape: { id, set, name, element, type } where any of
// set/name/element/type may be null when the card is unlabeled.

// Build chip lists for Set / Element / Type rows from the API response. Each
// entry is just a string — the first-seen casing comes back from the server.
function buildChipRows(meta) {
  return {
    set: meta.sets || [],
    element: meta.elements || [],
    type: meta.types || [],
  };
}

// Returns true when the card passes the active filter state.
// state = { selectedSets: Set<string>, selectedElements: Set<string>,
//           selectedTypes: Set<string>, search: string, hideUnlabeled: bool }
function cardPasses(card, state) {
  if (state.hideUnlabeled && !card.name && !card.set) return false;

  // Within an axis: OR. Across axes: AND. An empty axis selection means "no
  // filter on this axis" — every card passes that axis.
  if (state.selectedSets.size && !state.selectedSets.has(card.set)) return false;
  if (state.selectedElements.size
      && !state.selectedElements.has((card.element || "").toLowerCase())) return false;
  if (state.selectedTypes.size
      && !state.selectedTypes.has((card.type || "").toLowerCase())) return false;

  const q = (state.search || "").trim().toLowerCase();
  if (q) {
    const hay = `${card.id} ${card.name || ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

// Render a single chip row into `container`. Calls `onToggle(value)` whenever
// a chip flips state. `selected` is a Set of currently-selected values.
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

// Convenience: render the three standard chip rows. `state` is the same object
// passed to cardPasses(); this function attaches the right Sets to `state`.
function renderStandardChips(meta, state, onChange) {
  const chips = buildChipRows(meta);
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
```

Note: filters live entirely in the browser; no Python equivalent. See the deviation note at the top of this plan.

- [ ] **Step 2: Add chip styles to static/style.css**

Append the following block to the bottom of `static/style.css`:

```css
/* Filter chip rows (used on cards.html and deck.html). */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  margin: 4px 0;
}
.chip-label {
  font-size: 12px;
  color: var(--muted, #98a0ac);
  margin-right: 6px;
  min-width: 56px;
}
.chip {
  border: 1px solid var(--border, #444);
  background: transparent;
  color: var(--fg, #ddd);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
}
.chip:hover { border-color: var(--accent, #7aa8ff); }
.chip.on {
  background: var(--accent, #7aa8ff);
  color: #0b1220;
  border-color: var(--accent, #7aa8ff);
}
.chip-empty {
  font-size: 12px;
  color: var(--muted, #98a0ac);
  margin-right: 8px;
}
.hide-unlabeled {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--muted, #98a0ac);
  margin-left: 8px;
}
```

This uses CSS custom properties with fallback values so it works even if the existing stylesheet doesn't define them. If `style.css` already defines `--accent`, `--border`, `--fg`, `--muted`, they take precedence.

- [ ] **Step 3: Commit**

This file isn't wired into any template yet, but it's complete on its own.

```bash
git add static/filters.js static/style.css
git -c commit.gpgsign=false commit -m "Add shared static/filters.js + chip styling"
```

---

## Task 9: cards.html — chip rows + filter wiring + name display + hide-unlabeled toggle

**Files:**
- Modify: `templates/cards.html`

Replaces the set-dropdown UI with three chip rows + a Hide-unlabeled toggle. Search box now matches name OR id. Card tiles show `name` as the primary label, `id` as a small subtitle, with `id` as the primary label and no subtitle for unlabeled cards.

- [ ] **Step 1: Rewrite cards.html**

Replace `templates/cards.html` entirely:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Browse Cards · Blue Dragon Deck Builder</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="top">
  <h1>🐉 Blue Dragon Deck Builder</h1>
  <nav>
    <a href="/">Decks</a>
    <a href="/cards" class="active">Browse Cards</a>
  </nav>
  <span class="spacer"></span>
</header>

<div class="wrap">
  <div class="toolbar">
    <input type="text" id="search" placeholder="Search name or code…">
    <label class="hide-unlabeled">
      <input type="checkbox" id="hideUnlabeled"> Hide unlabeled
    </label>
    <label class="notice">Size
      <input type="range" id="sizeRange" min="110" max="240" value="150">
    </label>
    <span class="spacer" style="flex:1"></span>
    <span id="warm" class="notice" style="display:none"></span>
    <span id="count" class="notice"></span>
  </div>
  <div id="chipSet" class="chip-row"></div>
  <div id="chipElement" class="chip-row"></div>
  <div id="chipType" class="chip-row"></div>
  <div id="grid" class="card-grid"></div>
</div>

<script src="/static/common.js"></script>
<script src="/static/filters.js"></script>
<script>
let CARDS = [];
const state = {
  selectedSets: new Set(),
  selectedElements: new Set(),
  selectedTypes: new Set(),
  search: "",
  hideUnlabeled: false,
};
const zoom = setupZoom();
const grid = document.getElementById("grid");

function render() {
  const items = CARDS.filter(c => cardPasses(c, state));
  grid.innerHTML = "";
  const frag = document.createDocumentFragment();
  for (const c of items) {
    const tile = document.createElement("div");
    tile.className = "card-tile";
    const primary = c.name || c.id;
    const subtitle = c.name ? `<div class="code-sub">${c.id}</div>` : "";
    tile.innerHTML = `
      <img loading="lazy" src="/api/card/${encodeURIComponent(c.id)}/thumb" alt="${primary}">
      <div class="code">${primary}</div>
      ${subtitle}`;
    tile.querySelector("img").addEventListener("click", () => zoom(c.id));
    frag.appendChild(tile);
  }
  grid.appendChild(frag);
  document.getElementById("count").textContent = `${items.length} cards`;
}

async function load() {
  const data = await api("/api/cards");
  CARDS = data.cards;
  renderStandardChips(data, state, render);
  render();
}

document.getElementById("search").addEventListener("input", (e) => {
  state.search = e.target.value;
  render();
});
document.getElementById("hideUnlabeled").addEventListener("change", (e) => {
  state.hideUnlabeled = e.target.checked;
  render();
});
setupSizeSlider(document.getElementById("sizeRange"));
load();
watchCacheWarm(document.getElementById("warm"));
</script>
</body>
</html>
```

- [ ] **Step 2: Add a small style for the card-tile subtitle**

Append to `static/style.css`:

```css
.card-tile .code-sub {
  font-size: 10px;
  color: var(--muted, #98a0ac);
  text-align: center;
  margin-top: -2px;
}
```

- [ ] **Step 3: Manual browser smoke test**

Boot the server:
```bash
.venv/bin/python app.py > /tmp/bd-app.log 2>&1 &
sleep 2
```

Open http://127.0.0.1:5000/cards in a browser (or use the chrome browser tools). Verify:

1. Page loads without console errors.
2. Three chip rows render but each shows `Set: —`, `Element: —`, `Type: —` (no labels yet → empty chip rows).
3. All 272 cards render in the grid, each showing the card ID as the primary label (since no labels yet).
4. Typing `BDS1` in search narrows results.
5. The "Hide unlabeled" checkbox, when checked, empties the grid (every card is unlabeled).

Capture a screenshot to confirm.

- [ ] **Step 4: Stop the server**

```bash
pkill -f "python app.py" || true
```

- [ ] **Step 5: Commit**

```bash
git add templates/cards.html static/style.css
git -c commit.gpgsign=false commit -m "cards.html: chip filters, name display, hide-unlabeled toggle"
```

---

## Task 10: deck.html — mirror chip rows, name display, side-panel update

**Files:**
- Modify: `templates/deck.html`

Mirrors the same UI changes onto the deck-edit page (add-cards panel uses chip rows + new search behavior + name display on tiles). Also updates the deck side-panel rendering so each row shows `name` (primary) + `id` (subtitle) instead of the current `id` + `set`.

- [ ] **Step 1: Rewrite deck.html**

Replace `templates/deck.html` entirely:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Edit Deck · Blue Dragon Deck Builder</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="top">
  <h1>🐉 Deck Builder</h1>
  <nav>
    <a href="/">Decks</a>
    <a href="/cards">Browse Cards</a>
  </nav>
  <span class="spacer"></span>
  <span class="notice">max {{ max_copies }}/card · target {{ target }}</span>
</header>

<div class="wrap">
  <div class="editor">
    <!-- Add-cards panel -->
    <div class="panel">
      <div class="toolbar">
        <button id="viewAll" class="mini primary" data-view="all">All cards</button>
        <button id="viewDeck" class="mini" data-view="deck">In deck</button>
        <input type="text" id="search" placeholder="Search name or code…">
        <label class="hide-unlabeled">
          <input type="checkbox" id="hideUnlabeled"> Hide unlabeled
        </label>
        <label class="notice">Size
          <input type="range" id="sizeRange" min="110" max="240" value="150">
        </label>
        <span class="spacer" style="flex:1"></span>
        <span id="warm" class="notice" style="display:none"></span>
        <span id="count" class="notice"></span>
      </div>
      <div id="chipSet" class="chip-row"></div>
      <div id="chipElement" class="chip-row"></div>
      <div id="chipType" class="chip-row"></div>
      <div id="grid" class="card-grid"></div>
    </div>

    <!-- Deck panel -->
    <div class="deck-side">
      <div class="panel">
        <div class="deck-head">
          <input type="text" id="deckName" title="Deck name">
          <span id="pill" class="count-pill">0 / {{ target }}</span>
        </div>
        <div id="missing" class="warn" style="display:none"></div>
        <div id="deckList" class="deck-list"></div>
        <div class="toolbar" style="margin:0">
          <button class="primary" id="dlBtn" onclick="downloadImage()">⬇ Download deck image</button>
          <button class="danger mini" onclick="clearDeck()">Clear all</button>
        </div>
        <p class="notice" style="margin-bottom:0">Image is auto-sized to stay under 10&nbsp;MB for Discord.</p>
      </div>
    </div>
  </div>
</div>

<script src="/static/common.js"></script>
<script src="/static/filters.js"></script>
<script>
const DECK_ID = {{ deck_id|tojson }};
const MAX = {{ max_copies }};
const TARGET = {{ target }};
let CARDS = [];
let cardMeta = {};                // id -> { set, name }
let counts = {};
let deckOnly = false;
const tiles = {};
const zoom = setupZoom();

const filterState = {
  selectedSets: new Set(),
  selectedElements: new Set(),
  selectedTypes: new Set(),
  search: "",
  hideUnlabeled: false,
};

function deckTotal() {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}

/* ---------- card grid (add panel) ---------- */
function tileFor(c) {
  const tile = document.createElement("div");
  tile.className = "card-tile";
  const primary = c.name || c.id;
  const subtitle = c.name ? `<div class="code-sub">${c.id}</div>` : "";
  tile.innerHTML = `
    <div class="count-flag" style="display:none"></div>
    <img loading="lazy" src="/api/card/${encodeURIComponent(c.id)}/thumb" alt="${primary}">
    <div class="code">${primary}</div>
    ${subtitle}
    <div class="add-row">
      <button class="mini" data-act="minus">−</button>
      <span class="qty">0</span>
      <button class="mini" data-act="plus">+</button>
    </div>`;
  tile.querySelector("img").addEventListener("click", () => zoom(c.id));
  const minus = tile.querySelector('[data-act=minus]');
  const plus = tile.querySelector('[data-act=plus]');
  const qty = tile.querySelector(".qty");
  const flag = tile.querySelector(".count-flag");
  minus.addEventListener("click", () => changeCard(c.id, (counts[c.id] || 0) - 1));
  plus.addEventListener("click", () => changeCard(c.id, (counts[c.id] || 0) + 1));
  tiles[c.id] = { flag, qty, minus, plus };
  refreshTile(c.id);
  return tile;
}
function refreshTile(id) {
  const t = tiles[id];
  if (!t) return;
  const n = counts[id] || 0;
  t.qty.textContent = n;
  t.flag.style.display = n ? "block" : "none";
  t.flag.textContent = "×" + n;
  t.minus.disabled = n <= 0;
  t.plus.disabled = n >= MAX;
}
function renderGrid() {
  const items = CARDS.filter(c =>
    cardPasses(c, filterState) &&
    (!deckOnly || (counts[c.id] || 0) > 0));
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  for (const id in tiles) delete tiles[id];
  if (!items.length) {
    grid.innerHTML = `<p class="notice">${deckOnly
      ? "No cards in this deck yet — switch to “All cards” to add some."
      : "No cards match your filter."}</p>`;
  } else {
    const frag = document.createDocumentFragment();
    for (const c of items) frag.appendChild(tileFor(c));
    grid.appendChild(frag);
  }
  document.getElementById("count").textContent = deckOnly
    ? `${items.length} unique · ${deckTotal()} cards in deck`
    : `${items.length} cards`;
}

function setView(view) {
  deckOnly = view === "deck";
  document.getElementById("viewAll").classList.toggle("primary", !deckOnly);
  document.getElementById("viewDeck").classList.toggle("primary", deckOnly);
  renderGrid();
}

/* ---------- deck mutations (optimistic UI + debounced save) ---------- */
const saveTimers = {};

function changeCard(id, target) {
  target = Math.max(0, Math.min(MAX, target));
  const prev = counts[id] || 0;
  if (target === prev) return;
  if (target === 0) delete counts[id]; else counts[id] = target;

  refreshTile(id);
  renderDeckList(localDeck());
  if (deckOnly && (prev === 0 || target === 0)) {
    renderGrid();
  }
  scheduleSave(id);
}

function scheduleSave(id) {
  clearTimeout(saveTimers[id]);
  saveTimers[id] = setTimeout(() => saveCard(id), 250);
}
async function saveCard(id) {
  clearTimeout(saveTimers[id]); delete saveTimers[id];
  try {
    await apiJSON(`/api/decks/${encodeURIComponent(DECK_ID)}/card`,
                  "POST", { card_id: id, count: counts[id] || 0 });
  } catch (e) {
    toast("Save failed: " + e.message);
  }
}
async function flushSaves() {
  await Promise.all(Object.keys(saveTimers).map(saveCard));
}

// Side-panel list from local counts (instant, no round-trip).
function localDeck() {
  const cards = Object.keys(counts).map(id => ({
    id,
    set: cardMeta[id]?.set || null,
    name: cardMeta[id]?.name || null,
    count: counts[id],
  }));
  cards.sort((a, b) => {
    const sa = a.set || "~", sb = b.set || "~";
    if (sa !== sb) return sa < sb ? -1 : 1;
    const na = (a.name || "").toLowerCase(), nb = (b.name || "").toLowerCase();
    if (na !== nb) return na < nb ? -1 : 1;
    return a.id < b.id ? -1 : 1;
  });
  return { cards, total: deckTotal(), missing: [] };
}

function ingest(d) {
  counts = {};
  for (const it of d.cards) counts[it.id] = it.count;
  renderDeckList(d);
}
function applyResolved(d) {
  ingest(d);
  if (deckOnly) renderGrid(); else for (const id in tiles) refreshTile(id);
}

/* ---------- deck side panel ---------- */
function renderDeckList(d) {
  const list = document.getElementById("deckList");
  list.innerHTML = "";
  if (!d.cards.length) {
    list.innerHTML = '<p class="notice">No cards yet — add some from the left.</p>';
  }
  for (const it of d.cards) {
    const primary = it.name || it.id;
    const sub = it.name ? `<small>${it.id}</small>` : "";
    const row = document.createElement("div");
    row.className = "deck-row";
    row.innerHTML = `
      <img src="/api/card/${encodeURIComponent(it.id)}/thumb" loading="lazy">
      <span class="name">${primary}<br>${sub}</span>
      <button class="mini" title="remove one">−</button>
      <span class="qty">${it.count}</span>
      <button class="mini" title="add one">+</button>
      <button class="danger mini" title="remove all">✕</button>`;
    const [minus, plus, rm] = row.querySelectorAll("button");
    minus.addEventListener("click", () => changeCard(it.id, it.count - 1));
    plus.addEventListener("click", () => changeCard(it.id, it.count + 1));
    plus.disabled = it.count >= MAX;
    rm.addEventListener("click", () => changeCard(it.id, 0));
    row.querySelector("img").addEventListener("click", () => zoom(it.id));
    list.appendChild(row);
  }
  const pill = document.getElementById("pill");
  pill.textContent = `${d.total} / ${TARGET}`;
  pill.classList.toggle("over", d.total > TARGET);
  pill.classList.toggle("full", d.total === TARGET);
  const miss = document.getElementById("missing");
  if (d.missing && d.missing.length) {
    miss.style.display = "block";
    miss.textContent = `⚠ ${d.missing.length} saved card(s) not found in catalog and skipped.`;
  } else { miss.style.display = "none"; }
}

async function clearDeck() {
  if (!confirm("Remove all cards from this deck?")) return;
  for (const id in saveTimers) { clearTimeout(saveTimers[id]); delete saveTimers[id]; }
  const d = await apiJSON(`/api/decks/${encodeURIComponent(DECK_ID)}`, "PUT", { cards: {} });
  applyResolved(d);
  toast("Deck cleared");
}

const nameInput = document.getElementById("deckName");
nameInput.addEventListener("change", async () => {
  await apiJSON(`/api/decks/${encodeURIComponent(DECK_ID)}`, "PUT", { name: nameInput.value });
  toast("Renamed");
});

async function downloadImage() {
  const btn = document.getElementById("dlBtn");
  btn.disabled = true; btn.textContent = "Rendering…";
  try {
    await flushSaves();
    const res = await fetch(`/api/decks/${encodeURIComponent(DECK_ID)}/image`);
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    const blob = await res.blob();
    const mb = (blob.size / 1048576).toFixed(1);
    const under = res.headers.get("X-Under-Limit") !== "0";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${DECK_ID}.jpg`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(under ? `Saved (${mb} MB)` : `Saved but ${mb} MB — over limit!`);
  } catch (e) {
    toast("Error: " + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "⬇ Download deck image";
  }
}

document.getElementById("search").addEventListener("input", (e) => {
  filterState.search = e.target.value;
  renderGrid();
});
document.getElementById("hideUnlabeled").addEventListener("change", (e) => {
  filterState.hideUnlabeled = e.target.checked;
  renderGrid();
});
document.getElementById("viewAll").addEventListener("click", () => setView("all"));
document.getElementById("viewDeck").addEventListener("click", () => setView("deck"));
setupSizeSlider(document.getElementById("sizeRange"));

async function init() {
  const grid = document.getElementById("grid");
  grid.innerHTML = '<p class="notice">Loading cards…</p>';
  try {
    const [deck, cards] = await Promise.all([
      api(`/api/decks/${encodeURIComponent(DECK_ID)}`),
      api("/api/cards"),
    ]);
    CARDS = (cards && cards.cards) || [];
    cardMeta = {};
    for (const c of CARDS) cardMeta[c.id] = { set: c.set, name: c.name };
    renderStandardChips(cards, filterState, renderGrid);
    nameInput.value = deck.name;
    ingest(deck);
    setView(deck.total > 0 ? "deck" : "all");
    watchCacheWarm(document.getElementById("warm"));
  } catch (e) {
    grid.innerHTML = `<p class="warn">⚠ Failed to load cards: ${e.message}.` +
      ` Make sure the app is running, then refresh (Ctrl+F5).</p>`;
  }
}
init();

window.addEventListener("beforeunload", () => {
  for (const id in saveTimers) {
    clearTimeout(saveTimers[id]);
    fetch(`/api/decks/${encodeURIComponent(DECK_ID)}/card`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: id, count: counts[id] || 0 }),
      keepalive: true,
    });
  }
});
</script>
</body>
</html>
```

Key changes vs the old `deck.html`:

- Removed `<select id="setFilter">`; added the three chip-row containers + Hide-unlabeled toggle.
- Pulled `static/filters.js`.
- `tileFor` renders `name` primary + `id` subtitle when labeled.
- `renderGrid` uses `cardPasses(c, filterState)` instead of inline filter logic.
- `cardSet` renamed to `cardMeta` (now stores both set and name).
- `renderDeckList` shows `name` primary + `id` small subtitle (was id + set).
- `localDeck` sort matches the server-side `decks.py:get_resolved` sort.

- [ ] **Step 2: Manual browser smoke test**

Boot the server:
```bash
.venv/bin/python app.py > /tmp/bd-app.log 2>&1 &
sleep 2
```

Steps to verify in the browser:
1. Visit `/` and open or create a deck.
2. The deck-edit page loads without console errors.
3. The three chip rows appear above the card grid (empty since no labels yet).
4. The search input narrows the grid as you type.
5. Add a couple of cards using the `+` buttons; the right-side deck list updates with each card's id as the primary label (since no labels yet) and no subtitle.
6. Click ⬇ Download deck image — image downloads and renders.
7. Stop the server with `pkill -f "python app.py" || true`.

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add templates/deck.html
git -c commit.gpgsign=false commit -m "deck.html: chip filters, name display, side-panel update"
```

---

## Task 11: render.py — handle the new catalog shape

**Files:**
- Modify: `render.py:render_deck` (only the sort key)

`render_deck` currently sorts by `catalog.get(e[0])["set"]`. With the new catalog, `set` is on `label`, and `label` may be `None` for unlabeled cards. Fix the sort key with a safe fallback.

- [ ] **Step 1: Update render.py**

In `render.py`, find this block (around line 175–180):

```python
def render_deck(deck, show_badge=True):
    """deck: {"name", "cards": {id: count}}. Returns (bytes, info)."""
    entries = [
        (cid, cnt)
        for cid, cnt in deck.get("cards", {}).items()
        if cnt > 0 and catalog.exists(cid)
    ]
    entries.sort(key=lambda e: (catalog.get(e[0])["set"], e[0]))
```

Replace the sort with a label-aware version:

```python
def render_deck(deck, show_badge=True):
    """deck: {"name", "cards": {id: count}}. Returns (bytes, info)."""
    entries = [
        (cid, cnt)
        for cid, cnt in deck.get("cards", {}).items()
        if cnt > 0 and catalog.exists(cid)
    ]

    def _sort_key(entry):
        cid, _ = entry
        rec = catalog.get(cid)
        label = rec.get("label") if rec else None
        if label is None:
            return (1, "", "", cid)
        return (0, label.set, label.name.lower(), cid)

    entries.sort(key=_sort_key)
```

Rest of the function is unchanged.

- [ ] **Step 2: Boot + smoke test the image export**

Boot the server:
```bash
.venv/bin/python app.py > /tmp/bd-app.log 2>&1 &
sleep 2
```

Create a test deck and export an image:
```bash
DECK=$(curl -s -X POST http://127.0.0.1:5000/api/decks \
  -H 'Content-Type: application/json' \
  -d '{"name":"render-smoke"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://127.0.0.1:5000/api/decks/$DECK/card" \
  -H 'Content-Type: application/json' \
  -d '{"card_id":"BDS1-EN_0001","count":3}' > /dev/null
curl -s -o /tmp/render-smoke.jpg \
  -w "code=%{http_code} bytes=%{size_download}\n" \
  "http://127.0.0.1:5000/api/decks/$DECK/image"
curl -s -X DELETE "http://127.0.0.1:5000/api/decks/$DECK"
```

Expected: `code=200 bytes=` followed by a number > 100000 (the image rendered). Open `/tmp/render-smoke.jpg` to verify visually — it should look the same as the smoke test image generated earlier in the session.

Stop the server:
```bash
pkill -f "python app.py" || true
```

- [ ] **Step 3: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add render.py
git -c commit.gpgsign=false commit -m "Use label-aware sort key in deck-image export"
```

---

## Task 12: .gitignore + README + final integration smoke

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Update .gitignore**

Edit `.gitignore` — change the first stanza so it reads:

```
# Card scans are NOT distributed with this repo — each user supplies their own copy.
/cards/
*.jpg
*.jpeg
*.png

# Local machine configuration (each user sets their own card path).
config.local.json

# Generated thumbnail / view cache.
cache/

# Saved decklists are personal data — keep the folder, ignore its contents.
decks/*.json

# Python.
__pycache__/
*.pyc
.venv/
venv/
```

(Replaced `/English/` with `/cards/`. Wildcards still cover anyone who keeps using a differently-named folder.)

- [ ] **Step 2: Update README.md**

Open `README.md` and replace the "What you need" + "Recommended layout (zero-config)" + "Configure the card folder" sections (top of file through the "Run it" heading) with:

```markdown
## What you need

1. **Python 3.10+** — <https://www.python.org/downloads/> (tick *"Add Python to
   PATH"* during install).
2. **The card image scans.** These are **not** included in this repo (and are
   gitignored so they never get committed). You'll drop your own copy into the
   `cards/` folder during setup, below.

## Setup

1. Clone or download this repo.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Get the card scans from your source (e.g. a personal collection or another
   maintainer) and copy every image into the `cards/` folder at the root of
   this repo. Each image's filename stem is its card ID (e.g.
   `BDS1-EN_0008.jpg` → card `BDS1-EN_0008`).

   If your scans are still organised into per-set subfolders, use the included
   migration tool to flatten them in one go:
   ```bash
   python -m scripts.flatten_cards \
     --source /path/to/your/nested/scans \
     --apply
   ```
   By default it copies into `<repo>/cards/`. Add `--move` to delete the
   sources after copying, or run without `--apply` first to preview the plan.

## Card labels

Metadata for the included card scans lives in `labels.csv` at the repo root.
Columns are `id, set, name, element, type`. This file is committed; if your
scans match the maintainer's, you'll get name search and element/type filters
for free. If your scans differ (different printings, different language), edit
`labels.csv` to match.

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
```

(Everything from "Run it" downward in the existing README stays as-is.)

- [ ] **Step 3: End-to-end smoke test**

Boot the server one more time and exercise the full path:
```bash
.venv/bin/python app.py > /tmp/bd-app.log 2>&1 &
sleep 2
echo "--- status ---"
curl -s http://127.0.0.1:5000/api/status | python3 -m json.tool | head -15
echo "--- cards ---"
curl -s "http://127.0.0.1:5000/api/cards" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('cards:', len(d['cards']))
print('sets:', d['sets'])
print('elements:', d['elements'])
print('types:', d['types'])
print('first card:', d['cards'][0])
"
pkill -f "python app.py" || true
```

Expected: 272 cards reported, all with `set/name/element/type` as `null`, and empty `sets/elements/types` arrays (we haven't labeled anything yet — that's the next conversation per the user's request).

- [ ] **Step 4: Verify the gitignore is doing its job**

Run:
```bash
git status
```

Expected: only the `.gitignore` and `README.md` edits appear as modifications. The `cards/` folder (272 images) should be invisible to git.

- [ ] **Step 5: Run all tests one final time**

Run: `.venv/bin/pytest -q`
Expected: All pass (target: 16 tests — 1 smoke + 6 labels + 7 flatten + 3 catalog, ish; rough count, ok if final count differs slightly).

- [ ] **Step 6: Commit**

```bash
git add .gitignore README.md
git -c commit.gpgsign=false commit -m "README + .gitignore: cards/ folder is the new default"
```

---

## Done state

- `<repo>/cards/` contains 272 card images at the top level (gitignored).
- `labels.csv` is committed with the header but no card rows yet — the user is going to fill it out manually as a follow-up.
- Browse Cards and Edit Deck pages render with three chip filter rows (empty until labels exist), name-or-code search, and a Hide-unlabeled toggle.
- All cards display as "unlabeled" today (id as primary label, no subtitle) — the moment a row is added to `labels.csv` and the app is restarted, that card flips to showing its name with id subtitle, and its set/element/type appear as chip options.
- Catalog reports the three-bucket counts in `/api/status` and the startup banner.
- Image export works end-to-end on the new shape.
- Test suite passes.

Next conversation: labeling strategy — fastest way to populate `labels.csv` for 272 cards.
