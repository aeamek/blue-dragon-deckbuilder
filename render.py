"""Render a decklist into a single shareable image (staggered stacks + count
badges), auto-tuned to stay under the Discord file-size limit."""
import io
import math

from PIL import Image, ImageDraw, ImageFont

import catalog
import config

CARD_ASPECT = 4052 / 2824          # height / width of the source scans
BG = (31, 37, 48)                  # dark slate backdrop
CARD_BORDER = (12, 14, 18)
TEXT = (236, 240, 245)
SUBTEXT = (150, 160, 175)
BADGE_BG = (208, 52, 44)
BADGE_TEXT = (255, 255, 255)


# Cross-platform font candidates, tried in order. Bare names let Pillow search
# the system font dirs; absolute paths cover the common locations on each OS.
_FONTS = {
    True: [  # bold
        "arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    False: [  # regular
        "arial.ttf", "segoeui.ttf", "DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
}


def _font(size, bold=True):
    for path in _FONTS[bool(bold)]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _card_image(card_id, width):
    """Return an RGB card image scaled to `width`, from the view cache."""
    path = catalog.view_path(card_id) or catalog.source_path(card_id)
    im = Image.open(path).convert("RGB")
    if im.width != width:
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.LANCZOS)
    return im


def _initial_card_width(unique_count):
    if unique_count <= 9:
        return 760
    if unique_count <= 20:
        return 680
    if unique_count <= 30:
        return 600
    return 540


def _columns(unique_count):
    # Always lay out 5 cards per row (fewer only if the deck has < 5 uniques).
    return max(1, min(5, unique_count))


def _rounded_badge(draw, x, y, r, text, font):
    draw.ellipse([x - r, y - r, x + r, y + r], fill=BADGE_BG,
                 outline=(255, 255, 255), width=max(2, r // 14))
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text((x - tw / 2 - tb[0], y - th / 2 - tb[1]), text, font=font,
              fill=BADGE_TEXT)


def compose(entries, card_w, deck_name, show_badge=True):
    """entries: list of (card_id, count). Returns an RGB PIL image."""
    card_h = round(card_w * CARD_ASPECT)
    max_count = min(config.MAX_COPIES_PER_CARD,
                    max((c for _, c in entries), default=1))
    dx = round(card_w * 0.16)
    dy = round(card_h * 0.10)
    fan_x = (max_count - 1) * dx
    fan_y = (max_count - 1) * dy

    cell_w = card_w + fan_x
    cell_h = card_h + fan_y

    cols = _columns(len(entries))
    rows = math.ceil(len(entries) / cols)
    gap = round(card_w * 0.06)
    margin = round(card_w * 0.08)

    header_h = round(card_w * 0.52)
    total = sum(c for _, c in entries)

    W = margin * 2 + cols * cell_w + (cols - 1) * gap
    H = margin + header_h + rows * cell_h + (rows - 1) * gap + margin

    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)

    # Header.
    title_font = _font(round(header_h * 0.42), bold=True)
    sub_font = _font(round(header_h * 0.24), bold=False)
    draw.text((margin, margin), deck_name or "Untitled Deck",
              font=title_font, fill=TEXT)
    draw.text((margin, margin + round(header_h * 0.55)),
              f"{total} cards  •  {len(entries)} unique",
              font=sub_font, fill=SUBTEXT)

    badge_font = _font(round(card_w * 0.16), bold=True)
    border = max(2, round(card_w * 0.012))

    for idx, (card_id, count) in enumerate(entries):
        r, c = divmod(idx, cols)
        cell_x = margin + c * (cell_w + gap)
        cell_y = margin + header_h + r * (cell_h + gap)

        card = _card_image(card_id, card_w)
        copies = min(count, config.MAX_COPIES_PER_CARD)
        # Draw back-to-front so rear copies peek out top-right.
        for k in range(copies - 1, -1, -1):
            px = cell_x + k * dx
            py = cell_y + fan_y - k * dy
            draw.rectangle(
                [px - border, py - border, px + card_w + border, py + card_h + border],
                fill=CARD_BORDER,
            )
            canvas.paste(card, (px, py))

        if show_badge and count > 1:
            fx = cell_x
            fy = cell_y + fan_y
            br = round(card_w * 0.13)
            _rounded_badge(draw, fx + card_w - br, fy + card_h - br, br,
                           f"×{count}", badge_font)

    return canvas


def _encode_under_limit(img, limit):
    """Try decreasing scales/qualities until the JPEG fits under `limit`."""
    smallest = None
    for scale in (1.0, 0.85, 0.72, 0.6, 0.5, 0.42, 0.35):
        if scale == 1.0:
            im = img
        else:
            im = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.LANCZOS,
            )
        for q in (88, 82, 76, 70, 64, 58):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
            data = buf.getvalue()
            if smallest is None or len(data) < len(smallest):
                smallest = data
            if len(data) <= limit:
                return data
    return smallest  # best effort if nothing fit


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
        primary_set = label.set[0] if label.set else ""
        return (0, primary_set, label.name.lower(), cid)

    entries.sort(key=_sort_key)
    if not entries:
        raise ValueError("Deck has no resolvable cards to render.")

    card_w = _initial_card_width(len(entries))
    img = compose(entries, card_w, deck.get("name", "Untitled Deck"), show_badge)
    data = _encode_under_limit(img, config.EXPORT_MAX_BYTES)
    info = {
        "bytes": len(data),
        "under_limit": len(data) <= config.EXPORT_MAX_BYTES,
        "unique": len(entries),
        "total": sum(c for _, c in entries),
    }
    return data, info
