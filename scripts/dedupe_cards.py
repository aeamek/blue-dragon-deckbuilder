"""Find and remove duplicate card images in cards_dir.

Two detection modes:

* Default: byte-for-byte identical (SHA-256). Catches the case where the
  same file was copied into two source folders.

* `--perceptual`: visually identical but byte-different (independent scans
  of the same card produce slightly different JPEGs). Uses a difference
  hash; group cards whose hashes differ by at most `--threshold` bits
  (default 6 out of 64).

Default mode is dry-run: it groups duplicates, picks a canonical
filename per group, and prints the plan. `--apply` deletes the
non-canonical copies and drops their rows from labels.csv.
`--remap-decks` also rewrites saved decks (decks/*.json) so any deck
that referenced a removed copy points at the canonical instead.

Run via:
    python -m scripts.dedupe_cards                   # exact, dry-run
    python -m scripts.dedupe_cards --perceptual      # visually-identical, dry-run
    python -m scripts.dedupe_cards --perceptual --apply --remap-decks
"""
import argparse
import hashlib
import json
import os
import re
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config        # noqa: E402
import labels        # noqa: E402


_BD_PREFIX = re.compile(r"^BD[A-Z0-9]+-EN_\d+$")


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_exact_dupe_groups(cards_dir):
    """Return list[list[(stem, fname)]] for files sharing a SHA-256."""
    by_hash = {}
    for fname in sorted(os.listdir(cards_dir)):
        stem, ext = os.path.splitext(fname)
        if ext.lower() not in config.CARD_EXTS:
            continue
        h = _file_hash(os.path.join(cards_dir, fname))
        by_hash.setdefault(h, []).append((stem, fname))
    return [sorted(grp) for grp in by_hash.values() if len(grp) > 1]


def _fingerprint(path, size=8):
    """Return (dhash_int, mean_rgb_tuple). dhash captures composition; the
    mean RGB makes sure we don't lump two elemental dragons together just
    because their layouts look alike at 8x8."""
    with Image.open(path) as im:
        rgb = im.convert("RGB").resize((32, 32), Image.LANCZOS)
        g = rgb.convert("L").resize((size + 1, size), Image.LANCZOS)
    gpix = list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            i = row * (size + 1) + col
            bits = (bits << 1) | (1 if gpix[i] > gpix[i + 1] else 0)
    rpix = list(rgb.getdata())
    n = len(rpix)
    mean = (sum(p[0] for p in rpix) / n,
            sum(p[1] for p in rpix) / n,
            sum(p[2] for p in rpix) / n)
    return bits, mean


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _rgb_dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def find_perceptual_dupe_groups(cards_dir, threshold=6, color_threshold=20.0):
    """Group files whose dhash differs by <= `threshold` bits AND whose
    mean RGB differs by <= `color_threshold` Euclidean units (out of ~442)."""
    fingerprints = []
    for fname in sorted(os.listdir(cards_dir)):
        stem, ext = os.path.splitext(fname)
        if ext.lower() not in config.CARD_EXTS:
            continue
        h, mean = _fingerprint(os.path.join(cards_dir, fname))
        fingerprints.append((stem, fname, h, mean))

    groups = []
    for stem, fname, h, mean in fingerprints:
        placed = False
        for grp in groups:
            _, _, rep_h, rep_mean = grp[0]
            if (_hamming(rep_h, h) <= threshold
                    and _rgb_dist(rep_mean, mean) <= color_threshold):
                grp.append((stem, fname, h, mean))
                placed = True
                break
        if not placed:
            groups.append([(stem, fname, h, mean)])

    return [
        sorted([(s, f) for (s, f, _h, _m) in grp])
        for grp in groups if len(grp) > 1
    ]


def find_dupe_groups(cards_dir, perceptual, threshold, color_threshold):
    if perceptual:
        return find_perceptual_dupe_groups(
            cards_dir, threshold=threshold, color_threshold=color_threshold)
    return find_exact_dupe_groups(cards_dir)


def canonical_pick(group):
    """Pick the stem to keep. Prefers BD-prefix filenames over Receipt_*."""
    bd = [(s, f) for (s, f) in group if _BD_PREFIX.match(s)]
    if bd:
        return sorted(bd)[0]
    return sorted(group)[0]


def list_deck_files():
    return [os.path.join(config.DECKS_DIR, f)
            for f in os.listdir(config.DECKS_DIR) if f.endswith(".json")]


def collect_deck_references(removed_ids):
    """Return {deck_file: {removed_id -> count}} for any deck that uses a
    removed card."""
    out = {}
    for path in list_deck_files():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        cards = data.get("cards", {}) or {}
        hits = {cid: cnt for cid, cnt in cards.items() if cid in removed_ids}
        if hits:
            out[path] = hits
    return out


def remap_decks(removed_to_canonical):
    """Rewrite each deck json that mentions a removed id, swapping it for
    the canonical id (counts are merged if both ids were present)."""
    touched = 0
    for path in list_deck_files():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        cards = data.get("cards", {}) or {}
        if not any(cid in removed_to_canonical for cid in cards):
            continue
        new_cards = {}
        for cid, cnt in cards.items():
            target = removed_to_canonical.get(cid, cid)
            new_cards[target] = new_cards.get(target, 0) + int(cnt)
        # Cap at max copies (deck rule already enforces this on the route
        # side but it's harmless to clip here too).
        cap = config.MAX_COPIES_PER_CARD
        new_cards = {cid: min(c, cap) for cid, c in new_cards.items()}
        data["cards"] = new_cards
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
        touched += 1
    return touched


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Delete non-canonical files + drop their rows from labels.csv.")
    parser.add_argument("--remap-decks", action="store_true",
                        help="Also rewrite decks/*.json to swap removed ids for the canonical one.")
    parser.add_argument("--perceptual", action="store_true",
                        help="Match visually-identical scans, not just byte-identical files.")
    parser.add_argument("--threshold", type=int, default=6,
                        help="Max Hamming distance for perceptual matches (default 6 / 64 bits).")
    parser.add_argument("--color-threshold", type=float, default=20.0,
                        help="Max mean-RGB Euclidean distance (default 20, range 0..~442).")
    args = parser.parse_args(argv)

    cards_dir = config.cards_dir()
    if not os.path.isdir(cards_dir):
        sys.exit(f"cards_dir not found: {cards_dir}")

    mode = "perceptual" if args.perceptual else "byte-identical"
    print(f"Scanning {cards_dir} ({mode})...")
    groups = find_dupe_groups(cards_dir, args.perceptual, args.threshold,
                              args.color_threshold)
    if not groups:
        print("No duplicates found.")
        return 0

    existing_for_display, _ = labels.load(config.labels_path())

    def annotated(stem):
        row = existing_for_display.get(stem)
        if row and row.name:
            return f"{stem}  ({row.name!r}, {row.set!r}, {row.type!r})"
        return stem

    removed_to_canonical = {}
    print(f"\nFound {len(groups)} duplicate group(s):")
    for grp in groups:
        keep_stem, keep_fname = canonical_pick(grp)
        print(f"  keep    {annotated(keep_stem)}")
        for stem, fname in grp:
            if stem == keep_stem:
                continue
            print(f"  remove  {annotated(stem)}")
            removed_to_canonical[stem] = keep_stem
        print()

    deck_refs = collect_deck_references(set(removed_to_canonical))
    if deck_refs:
        print(f"\n{len(deck_refs)} deck file(s) reference cards that would be removed:")
        for path, hits in deck_refs.items():
            for cid, cnt in hits.items():
                print(f"  {os.path.basename(path)}: {cnt}x {cid}  ->  {removed_to_canonical[cid]}")

    existing, warnings = labels.load(config.labels_path())
    rows_to_drop = [cid for cid in removed_to_canonical if cid in existing]
    if rows_to_drop:
        print(f"\n{len(rows_to_drop)} row(s) would be dropped from labels.csv.")

    if not args.apply:
        print("\n(dry-run) pass --apply to delete the files + drop label rows.")
        if deck_refs and not args.remap_decks:
            print("Pass --remap-decks with --apply to also fix the affected decks.")
        return 0

    # Apply: delete files, drop label rows, optionally remap decks.
    for stem in removed_to_canonical:
        # We need the original filename for the os.remove call.
        for grp in groups:
            for s, f in grp:
                if s == stem:
                    os.remove(os.path.join(cards_dir, f))
                    break

    if rows_to_drop:
        for cid in rows_to_drop:
            existing.pop(cid, None)
        labels.dump(existing, config.labels_path())
        print(f"\nWrote {len(existing)} row(s) to {config.labels_path()}.")

    if args.remap_decks:
        touched = remap_decks(removed_to_canonical)
        print(f"Remapped card ids in {touched} deck file(s).")
    elif deck_refs:
        print("Skipped deck remapping (no --remap-decks). Affected decks will "
              "now have 'missing card' warnings.")

    print(f"\nRemoved {len(removed_to_canonical)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
