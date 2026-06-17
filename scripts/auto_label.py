"""One-shot automatic labeler.

Extracts name (OCR), card type (color of the right-edge tab + OCR),
element (color of the kanji badge + OCR), and set (filename prefix or
OCR of the card code) from each card image in cards_dir and merges the
results into labels.csv.

Each field is independent: a failure on one field does NOT prevent the
others from being written. The script also merges field-by-field on
re-runs, so an earlier run that nailed the name but missed the element
won't lose its name when a later run fills in the element.

Run with:
    python -m scripts.auto_label              # dry-run
    python -m scripts.auto_label --apply      # merge into labels.csv
    python -m scripts.auto_label --apply --only BDS1-EN_0001
    python -m scripts.auto_label --debug      # save crops to cache/auto_label_debug/

Requires:
    brew install tesseract
    pip install pytesseract
"""
import argparse
import math
import os
import re
import sys
from collections import Counter

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config        # noqa: E402
import labels        # noqa: E402
import vocab         # noqa: E402


# --------------------------------------------------------------------------- #
# Crop regions (fractions of image W, H)
# --------------------------------------------------------------------------- #
REGIONS = {
    # Big banner with the printed name in serif on a light background.
    "name":          (0.18, 0.62, 0.78, 0.70),
    # Element badge — the round kanji-on-color glyph just left of the name.
    # Tight on the colored disc so we don't average in the gold frame ring.
    "element_color": (0.085, 0.635, 0.135, 0.690),
    # Same box, slightly expanded for OCR of the small element word.
    "element_text":  (0.06, 0.615, 0.16, 0.695),
    # Vertical text reading SHADOW / PARTNER / SKILL / COMMAND. Overlaid on art.
    "type_text":     (0.83, 0.18, 0.91, 0.88),
    # Solid colored strip at the right edge.
    "type_color":    (0.955, 0.40, 0.985, 0.60),
    # Card code in tiny serif at the bottom-right corner.
    "card_code":     (0.78, 0.945, 0.995, 0.99),
}

# Element color centroids (hue_deg, sat, val). Derived from sampling the
# centred kanji-disc crop. Tuning continues based on what we see in real cards.
ELEMENT_COLOR_REFS = {
    "light":  (48,   0.65, 0.80),
    "fire":   (7,    0.70, 0.80),
    "water":  (215,  0.65, 0.70),
    "earth":  (35,   0.60, 0.75),    # green/brown kanji on gold ring
    "wind":   (175,  0.50, 0.80),
    "dark":   (290,  0.50, 0.35),
    "none":   (0,    0.00, 0.55),    # grey (low saturation)
}

# Type color centroids — sampled from the right-edge solid strip.
TYPE_COLOR_REFS = {
    "Shadow":  (208, 0.60, 0.70),
    "Partner": (206, 0.43, 0.90),
    "Command": (0,   0.79, 0.85),
    "Skill":   (140, 0.55, 0.55),
}

# If you migrated card images from a nested per-set folder (as
# scripts/flatten_cards.py does), the original folder is the authoritative
# source of each card's set. The script builds a filename -> set map from
# this directory on startup. Override via --source-tree.
DEFAULT_SOURCE_TREE = "/Users/wadestern/stuff/English"
EXCLUDED_SOURCE_FOLDERS = {"Strategies & Tips"}

TYPE_WORD_TO_VOCAB = {
    "SHADOW":  "Shadow",
    "PARTNER": "Partner",
    "SKILL":   "Skill",
    "COMMAND": "Command",
}

ELEMENT_WORDS = {e.upper(): e for e in vocab.KNOWN_ELEMENTS}


def _import_pytesseract():
    try:
        import pytesseract
    except ImportError:
        sys.exit("pytesseract not installed. Run: pip install pytesseract")
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        sys.exit("tesseract binary not found. Run: brew install tesseract")
    return pytesseract


def crop(im, region):
    W, H = im.size
    x0, y0, x1, y1 = region
    return im.crop((int(x0*W), int(y0*H), int(x1*W), int(y1*H)))


# --------------------------------------------------------------------------- #
# Color helpers — circular hue mean is essential, otherwise red wraps wrong.
# --------------------------------------------------------------------------- #
def median_hsv(im, v_min=0.30, s_min=0.20):
    """Circular-mean H + plain S/V over saturated, bright pixels. Pillow's HSV
    encodes each channel as 0..255; we convert to deg [0,360) and [0,1]."""
    hsv = im.convert("HSV")
    w, h = hsv.size
    step = max(1, max(w, h) // 64)
    # Downsample by `step` first so we don't materialise the full pixel list.
    small = hsv.resize((max(1, w // step), max(1, h // step)), Image.NEAREST)
    pixels = small.tobytes()
    keep = []
    for i in range(0, len(pixels), 3):
        h_b, s_b, v_b = pixels[i], pixels[i+1], pixels[i+2]
        if v_b / 255 > v_min and s_b / 255 > s_min:
            keep.append((h_b, s_b, v_b))
    if not keep:
        return None
    xs = ys = ss = vs = 0.0
    for p in keep:
        ang = p[0] / 255 * 2 * math.pi
        xs += math.cos(ang)
        ys += math.sin(ang)
        ss += p[1] / 255
        vs += p[2] / 255
    n = len(keep)
    h_deg = (math.degrees(math.atan2(ys / n, xs / n)) + 360) % 360
    return (h_deg, ss / n, vs / n)


def _hue_dist(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def closest_match(hsv, refs, hue_weight=1.0, sat_weight=40, val_weight=30):
    if hsv is None:
        return (None, None)
    h, s, v = hsv
    best = None
    best_d = 1e9
    for name, (rh, rs, rv) in refs.items():
        if rs < 0.1:
            hue_term = 0 if s < 0.18 else 100
        else:
            hue_term = _hue_dist(h, rh) * hue_weight
            if s < 0.15:
                hue_term = 100
        sat_term = abs(s - rs) * sat_weight
        val_term = abs(v - rv) * val_weight
        d = hue_term + sat_term + val_term
        if d < best_d:
            best_d = d
            best = name
    return (best, best_d)


# --------------------------------------------------------------------------- #
# Per-field extractors. Each is wrapped so a failure here doesn't crash other
# fields.
# --------------------------------------------------------------------------- #
def _ocr_text(ocr, im, psm=7, charset=None):
    cfg = f"--psm {psm}"
    if charset:
        cfg += f" -c tessedit_char_whitelist={charset}"
    return ocr.image_to_string(im, config=cfg).strip()


def extract_name(im, ocr, debug_dir, card_id):
    """Try several (x0, psm) combos; pick the first result that looks like a
    reasonable name. Different card types have the name banner start at
    different x positions (Commands/Skills extend further left than
    Shadow/Partner, whose element badge eats the leftmost portion)."""
    try:
        W, H = im.size
        if debug_dir:
            c = crop(im, REGIONS["name"])
            c.save(os.path.join(debug_dir, f"{card_id}__name.jpg"), quality=88)

        # Order matters — earlier combos are tried first.
        attempts = [
            (0.16, 8),   # Shadows / Partners: skip badge, single-word mode
            (0.13, 7),   # Commands / Skills: name extends further left
            (0.10, 8),
            (0.18, 7),
        ]
        sane = re.compile(r"^[A-Z][A-Z0-9'\- ]+[A-Z0-9]$")
        for x0, psm in attempts:
            box = im.crop((int(x0*W), int(0.62*H), int(0.78*W), int(0.70*H)))
            txt = _ocr_text(ocr, box, psm=psm)
            cleaned = re.sub(r"[^A-Za-z0-9'\- ]", "", txt).strip().upper()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if cleaned and sane.match(cleaned) and 3 <= len(cleaned) <= 40:
                return cleaned.title(), f"ocr(x0={x0:.2f},psm={psm})"
        return "", "fail"
    except Exception as e:
        return "", f"err:{e.__class__.__name__}"


def has_element_badge(im, debug_dir, card_id):
    """Shadows / Partners have a saturated colored disc here. Skills / Commands
    don't — the same x range falls on the start of the name banner instead."""
    try:
        cc = crop(im, REGIONS["element_color"])
        if debug_dir:
            cc.save(os.path.join(debug_dir, f"{card_id}__elem_color.jpg"), quality=88)
        hsv = median_hsv(cc, v_min=0.15, s_min=0.10)
        if hsv is None:
            return False
        _, s, v = hsv
        return s > 0.35 and v > 0.35
    except Exception:
        return None


def extract_type(im, ocr, debug_dir, card_id):
    """Type: OCR'd vertical tab text + color of right-edge strip.
    Returns (type_or_empty, source_tag)."""
    ocr_type = ""
    try:
        c = crop(im, REGIONS["type_text"])
        rotated = c.rotate(90, expand=True)
        if debug_dir:
            rotated.save(os.path.join(debug_dir, f"{card_id}__type_text.jpg"), quality=88)
        for psm in (7, 11):
            text = _ocr_text(ocr, rotated, psm=psm).upper()
            text = re.sub(r"[^A-Z]", "", text)
            for word, vocab_t in TYPE_WORD_TO_VOCAB.items():
                if word in text:
                    ocr_type = vocab_t
                    break
            if ocr_type:
                break
    except Exception:
        pass

    color_type = None
    try:
        cc = crop(im, REGIONS["type_color"])
        if debug_dir:
            cc.save(os.path.join(debug_dir, f"{card_id}__type_color.jpg"), quality=88)
        hsv = median_hsv(cc)
        color_type, _ = closest_match(hsv, TYPE_COLOR_REFS)
    except Exception:
        pass

    if ocr_type and color_type:
        if ocr_type == color_type:
            return ocr_type, "ocr+color"
        return ocr_type, f"ocr({ocr_type})_color({color_type})"
    if ocr_type:
        return ocr_type, "ocr_only"
    if color_type:
        return color_type, "color_only"
    return "", "fail"


def extract_element(im, ocr, type_str, debug_dir, card_id):
    """Returns (list[str], source_tag).
    Commands / Skills always return ([], 'type_forces_empty')."""
    if type_str in vocab.TYPES_WITHOUT_ELEMENT:
        return [], "type_forces_empty"

    color_el = None
    try:
        cc = crop(im, REGIONS["element_color"])
        hsv = median_hsv(cc)
        color_el, _ = closest_match(hsv, ELEMENT_COLOR_REFS, hue_weight=1.5)
    except Exception:
        pass

    ocr_el = None
    try:
        c = crop(im, REGIONS["element_text"])
        if debug_dir:
            c.save(os.path.join(debug_dir, f"{card_id}__elem_text.jpg"), quality=88)
        for psm in (7, 11):
            text = _ocr_text(ocr, c, psm=psm).upper()
            text = re.sub(r"[^A-Z]", "", text)
            for word, el in ELEMENT_WORDS.items():
                if word in text:
                    ocr_el = el
                    break
            if ocr_el:
                break
    except Exception:
        pass

    chosen = ocr_el or color_el
    if chosen:
        return [chosen], ("ocr+color" if ocr_el and color_el == ocr_el
                          else "ocr" if ocr_el else "color")
    return [], "fail"


def build_source_set_map(source_tree):
    """Walk the original per-set folder structure and produce {stem -> set}.
    Returns empty dict if `source_tree` doesn't exist."""
    mapping = {}
    if not os.path.isdir(source_tree):
        return mapping
    for entry in sorted(os.listdir(source_tree)):
        sub = os.path.join(source_tree, entry)
        if not os.path.isdir(sub) or entry in EXCLUDED_SOURCE_FOLDERS:
            continue
        for fname in os.listdir(sub):
            stem, ext = os.path.splitext(fname)
            if ext.lower() in config.CARD_EXTS:
                mapping[stem] = entry
    return mapping


def extract_set(card_id, source_map):
    """Set comes from the source folder where the image originally lived
    (preserved at DEFAULT_SOURCE_TREE / --source-tree). Pure lookup; no OCR."""
    if card_id in source_map:
        return source_map[card_id], "source_tree"
    return "", "not_in_source_tree"


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #
def classify_card(path, card_id, ocr, debug_dir, source_map):
    im = Image.open(path)
    name, name_src = extract_name(im, ocr, debug_dir, card_id)
    badge_present = has_element_badge(im, debug_dir, card_id)
    type_, type_src = extract_type(im, ocr, debug_dir, card_id)

    # Badge presence is a tiebreaker.
    if type_ == "" and badge_present is not None:
        type_ = "Shadow" if badge_present else "Command"
        type_src = f"badge:{badge_present}_guess"

    element, el_src = extract_element(im, ocr, type_, debug_dir, card_id)
    set_, set_src = extract_set(card_id, source_map)

    return {
        "id": card_id,
        "name": name,
        "set": set_,
        "type": type_,
        "element": element,
        "_sources": {
            "name": name_src,
            "set": set_src,
            "type": type_src,
            "element": el_src,
            "badge_present": badge_present,
        },
    }


def merge_into_existing(card, existing_row):
    """Field-level merge: only fill fields that are currently empty in the
    existing row. Always returns a LabelRow."""
    if existing_row is None:
        return labels.LabelRow(
            id=card["id"], set=card["set"], name=card["name"],
            element=tuple(card["element"]), type=card["type"],
        )
    return labels.LabelRow(
        id=card["id"],
        set=existing_row.set or card["set"],
        name=existing_row.name or card["name"],
        element=existing_row.element if existing_row.element else tuple(card["element"]),
        type=existing_row.type or card["type"],
    )


def is_card_complete(row, type_):
    """A row is 'complete' (skip on default re-run) when name + type + set
    are filled AND element is filled (or the type doesn't need it)."""
    if row is None:
        return False
    if not row.name or not row.type or not row.set:
        return False
    if row.type in vocab.TYPES_WITHOUT_ELEMENT:
        return True
    return bool(row.element)


def print_card(card):
    s = card["_sources"]
    el = "|".join(card["element"]) if card["element"] else ""
    print(f"  {card['id']:30s} "
          f"name={card['name']!r:24s} "
          f"set={card['set']!r:18s} "
          f"type={card['type']!r:11s} "
          f"element={el!r:14s} "
          f"[name:{s['name']} type:{s['type']} elem:{s['element']} set:{s['set']}]")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write merged labels to labels.csv (default: dry-run).")
    parser.add_argument("--force", action="store_true",
                        help="Reprocess cards even if their row is already complete.")
    parser.add_argument("--only", action="append", default=None,
                        help="Process only the listed card_id(s). Repeat for multiple.")
    parser.add_argument("--debug", action="store_true",
                        help="Save all crops to cache/auto_label_debug/ for tuning.")
    parser.add_argument("--source-tree", default=DEFAULT_SOURCE_TREE,
                        help=("Original per-set folder tree, used to resolve "
                              f"each card's set. Default: {DEFAULT_SOURCE_TREE}"))
    args = parser.parse_args(argv)

    ocr = _import_pytesseract()
    cards_dir = config.cards_dir()
    if not os.path.isdir(cards_dir):
        sys.exit(f"cards_dir not found: {cards_dir}")

    debug_dir = None
    if args.debug:
        debug_dir = os.path.join(config.CACHE_DIR, "auto_label_debug")
        os.makedirs(debug_dir, exist_ok=True)

    existing, warnings = labels.load(config.labels_path())
    for w in warnings:
        print(f"warn: {w}")

    source_map = build_source_set_map(args.source_tree)
    if source_map:
        print(f"Loaded {len(source_map)} file->set mappings from {args.source_tree}")
    else:
        print(f"warn: source tree {args.source_tree} not found; set will be left blank")

    paths = []
    for fname in sorted(os.listdir(cards_dir)):
        stem, ext = os.path.splitext(fname)
        if ext.lower() not in config.CARD_EXTS:
            continue
        if args.only and stem not in args.only:
            continue
        paths.append((stem, os.path.join(cards_dir, fname)))

    if not paths:
        sys.exit("no card images found")

    print(f"Processing {len(paths)} card(s) ...")
    results = []
    skipped = 0
    for stem, path in paths:
        existing_row = existing.get(stem)
        if (existing_row is not None
                and not args.force
                and not args.only
                and is_card_complete(existing_row, existing_row.type)):
            skipped += 1
            continue
        try:
            card = classify_card(path, stem, ocr, debug_dir, source_map)
        except Exception as e:
            print(f"  {stem}: classify failed: {e}")
            continue
        results.append(card)
        print_card(card)

    print()
    print(f"Done. {len(results)} classified; {skipped} already-complete (skipped).")

    # Quick breakdown of source agreement.
    src_type = Counter(c["_sources"]["type"] for c in results)
    src_elem = Counter(c["_sources"]["element"] for c in results)
    print(f"Type sources : {dict(src_type)}")
    print(f"Elem sources : {dict(src_elem)}")

    if not args.apply:
        print("\n(dry-run) pass --apply to merge into labels.csv.")
        return 0

    merged = dict(existing)
    written = 0
    for c in results:
        before = merged.get(c["id"])
        after = merge_into_existing(c, before)
        merged[c["id"]] = after
        if before is None or before != after:
            written += 1
    labels.dump(merged, config.labels_path())
    print(f"\nWrote {written} row(s) to {config.labels_path()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
