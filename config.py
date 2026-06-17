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
