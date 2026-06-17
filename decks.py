"""Decklist persistence: one JSON file per deck under decks/."""
import datetime
import json
import os
import re
import time

import catalog
import config
import vocab


def _slug(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "deck"


def _path(deck_id):
    return os.path.join(config.DECKS_DIR, f"{deck_id}.json")


def _unique_id(base):
    deck_id = base
    n = 2
    while os.path.exists(_path(deck_id)):
        deck_id = f"{base}-{n}"
        n += 1
    return deck_id


def list_decks():
    out = []
    for fname in os.listdir(config.DECKS_DIR):
        if not fname.endswith(".json"):
            continue
        deck = _read(fname[:-5])
        if deck is None:
            continue
        cards = deck.get("cards", {})
        out.append({
            "id": deck["id"],
            "name": deck.get("name", deck["id"]),
            "total": sum(cards.values()),
            "unique": len(cards),
            "modified": deck.get("modified", 0),
            "sample": list(cards.keys())[:5],
        })
    out.sort(key=lambda d: d.get("modified", 0), reverse=True)
    return out


def _read(deck_id):
    path = _path(deck_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    data.setdefault("id", deck_id)
    data.setdefault("name", deck_id)
    data.setdefault("cards", {})
    return data


def get(deck_id):
    return _read(deck_id)


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
            "set": list(label.set) if label else [],
            "name": label.name if label else None,
            "type": label.type if label else None,
            "count": cnt,
        })
    items.sort(key=lambda i: (vocab.type_rank(i["type"]),
                              (i["name"] or "").lower(), i["id"]))
    return {
        "id": deck["id"],
        "name": deck["name"],
        "cards": items,
        "total": sum(i["count"] for i in items),
        "missing": missing,
    }


def _write(deck):
    deck["modified"] = int(time.time())
    with open(_path(deck["id"]), "w", encoding="utf-8") as fh:
        json.dump(deck, fh, indent=2)
    return deck


def create(name):
    deck_id = _unique_id(_slug(name))
    deck = {"id": deck_id, "name": name.strip() or "Untitled Deck",
            "cards": {}, "created": int(time.time())}
    return _write(deck)


def update(deck_id, name=None, cards=None):
    deck = _read(deck_id)
    if deck is None:
        return None
    if name is not None:
        deck["name"] = name.strip() or deck["name"]
    if cards is not None:
        clean = {}
        for cid, cnt in cards.items():
            cnt = int(cnt)
            if cnt <= 0 or not catalog.exists(cid):
                continue
            clean[cid] = min(cnt, config.MAX_COPIES_PER_CARD)
        deck["cards"] = clean
    return _write(deck)


def set_card(deck_id, card_id, count):
    """Set the count for a single card (0 removes it). Returns updated deck."""
    deck = _read(deck_id)
    if deck is None or not catalog.exists(card_id):
        return None
    count = max(0, min(int(count), config.MAX_COPIES_PER_CARD))
    if count == 0:
        deck["cards"].pop(card_id, None)
    else:
        deck["cards"][card_id] = count
    return _write(deck)


def delete(deck_id):
    path = _path(deck_id)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def export_text(deck_id):
    """Return a plain-text representation of the deck suitable for sharing.

    Format:
        # Blue Dragon Deck — "<name>"
        # <total> cards · <unique> unique · exported YYYY-MM-DD
        <count>  <card_id>   <card_name>
        ...

    Lines starting with '#' are comments. Cards that aren't in the catalog
    are written with '???' as the name so the human reader knows."""
    deck = _read(deck_id)
    if deck is None:
        return None
    cards = deck.get("cards", {})
    total = sum(cards.values())
    unique = len(cards)
    today = datetime.date.today().isoformat()
    out = [
        f'# Blue Dragon Deck — "{deck["name"]}"',
        f"# {total} cards · {unique} unique · exported {today}",
        "",
    ]
    # Sort: by type (Shadow, Partner, Command, Skill), then name, then id.
    rows = []
    for cid, cnt in cards.items():
        rec = catalog.get(cid)
        label = rec["label"] if rec else None
        name = label.name if label and label.name else "???"
        type_ = label.type if label else None
        rows.append((vocab.type_rank(type_), name.lower(), cid, cnt, name))
    rows.sort()
    for _tr, _ln, cid, cnt, name in rows:
        out.append(f"{cnt}  {cid:<28} {name}")
    return "\n".join(out) + "\n"


_IMPORT_LINE = re.compile(r"""
    ^\s*
    (?P<count>\d+)              # leading copy count
    \s+
    (?P<id>[A-Za-z0-9_\-]+)     # card id
    (?:\s+.*)?                  # optional trailing name (ignored)
    \s*$
""", re.VERBOSE)


def import_text(text, name=None):
    """Parse a deck-text payload and create a new deck.

    Returns a tuple (deck_dict, warnings). Unknown card ids end up in
    warnings; everything else still imports. Comments (lines starting with
    '#') and blank lines are skipped."""
    counts = {}
    warnings = []
    derived_name = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # Pick up the first quoted name in a comment as the default deck name.
            if derived_name is None:
                m = re.search(r'"([^"]+)"', line)
                if m:
                    derived_name = m.group(1)
            continue
        m = _IMPORT_LINE.match(line)
        if not m:
            warnings.append(f"unrecognised line: {raw!r}")
            continue
        cid = m.group("id")
        cnt = int(m.group("count"))
        if cnt <= 0:
            continue
        if not catalog.exists(cid):
            warnings.append(f"unknown card id: {cid}")
            continue
        # Cap at MAX_COPIES_PER_CARD if the file says more.
        cnt = min(cnt, config.MAX_COPIES_PER_CARD)
        counts[cid] = counts.get(cid, 0) + cnt
        if counts[cid] > config.MAX_COPIES_PER_CARD:
            counts[cid] = config.MAX_COPIES_PER_CARD

    if not counts:
        return None, warnings + ["no recognisable cards"]

    final_name = (name or derived_name or "Imported Deck").strip() or "Imported Deck"
    deck = create(final_name)
    update(deck["id"], cards=counts)
    return _read(deck["id"]), warnings
