"""Decklist persistence: one JSON file per deck under decks/."""
import json
import os
import re
import time

import catalog
import config


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
            "count": cnt,
        })
    items.sort(key=lambda i: ((i["set"][0] if i["set"] else "~"),
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
