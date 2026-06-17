"""Scan the flat cards folder into an in-memory catalog joined with labels.csv,
and serve cached thumbnails / medium-size views."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import config
import labels
import vocab

# id -> {"id", "filename", "path", "label": LabelRow | None}
_catalog = {}
_label_rows = {}        # id -> LabelRow ; the live in-memory copy of labels.csv
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

    sets_list = _first_seen_display(
        s for rec in labeled for s in rec["label"].set
    )
    elements_list = _first_seen_display(
        el for rec in labeled for el in rec["label"].element
    )
    types_list = _first_seen_display(rec["label"].type for rec in labeled)

    with _lock:
        _catalog.clear()
        _catalog.update(catalog)
        _label_rows.clear()
        _label_rows.update(rows)
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
    if label is None:
        return {"id": rec["id"], "set": [], "name": None,
                "element": [], "type": None}
    return {
        "id": rec["id"],
        "set": list(label.set),
        "name": label.name,
        "element": list(label.element),
        "type": label.type,
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
        # Sort by the card's first set membership (sets are ordered in the
        # label, with the first one acting as the primary for sort purposes).
        primary_set = label.set[0] if label.set else ""
        return (0, set_index.get(primary_set, len(set_index)),
                label.name.lower(), rec["id"])

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


def save_label(card_id, payload):
    """Persist a label edit. Mutates labels.csv atomically and updates the
    in-memory catalog so the next /api/cards call sees the change without a
    full rescan.

    payload = {"name": str, "set": list[str], "type": str,
               "element": list[str]}

    Raises KeyError if `card_id` is not in the image scan.
    Returns the updated public API record for the card.
    """
    name = (payload.get("name") or "").strip()
    raw_sets = payload.get("set") or []
    type_ = (payload.get("type") or "").strip()
    raw_elements = payload.get("element") or []

    # Sets: trim, drop empties, preserve user-specified order, dedupe.
    seen_sets = []
    for s in raw_sets:
        s = (s or "").strip()
        if s and s not in seen_sets:
            seen_sets.append(s)
    set_tuple = tuple(seen_sets)

    if type_ in vocab.TYPES_WITHOUT_ELEMENT:
        element = ()
    else:
        element = tuple(sorted({
            e.strip().lower() for e in raw_elements if e and e.strip()
        }))

    with _lock:
        if card_id not in _catalog:
            raise KeyError(card_id)

        row = labels.LabelRow(
            id=card_id, set=set_tuple, name=name,
            element=element, type=type_,
        )
        _label_rows[card_id] = row
        labels.dump(_label_rows, config.labels_path())

        _catalog[card_id]["label"] = row

        for s in seen_sets:
            if s not in _sets:
                _sets.append(s)

        return _record_to_api(_catalog[card_id])


def exists(card_id):
    with _lock:
        return card_id in _catalog


# --------------------------------------------------------------------------- #
# Cached resized images
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
# Background cache pre-warming
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
