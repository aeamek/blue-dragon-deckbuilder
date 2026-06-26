"""Blue Dragon Deck Builder — local Flask app.

Run:  python app.py     (or double-click run.bat)
Then open http://127.0.0.1:5000 in your browser.
"""
import io

from flask import Flask, abort, jsonify, render_template, request, send_file

import catalog
import config
import decks
import render
import vocab

app = Flask(__name__)
# Local dev tool: don't let browsers cache static JS/CSS, so updates always load.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Populated by init(); kept as a module-level handle so the routes can read it
# without re-scanning on every request.
_scan = None


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    if _scan is None:
        init()
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
# Card API
# --------------------------------------------------------------------------- #
@app.route("/api/status")
def api_status():
    return jsonify(catalog.build())  # rescan + report


@app.route("/api/cards")
def api_cards():
    return jsonify({
        "cards": catalog.all_cards(),
        "sets": catalog.sets_seen(),
        "elements": catalog.elements_seen(),
        "types": catalog.types_seen(),
    })


@app.route("/api/vocab")
def api_vocab():
    """Vocabularies used by the editor (and, in a follow-up task, the chip
    filters). Sets are the union of seeded defaults and anything seen in
    labels.csv."""
    seeded = list(vocab.SEEDED_SETS)
    seen = catalog.sets_seen()
    merged = list(seeded) + [s for s in seen if s not in seeded]
    return jsonify({
        "types": list(vocab.KNOWN_TYPES),
        "elements": list(vocab.KNOWN_ELEMENTS),
        "sets": merged,
    })


@app.route("/api/labels/<card_id>", methods=["PUT"])
def api_label_put(card_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400)
    # Normalize: missing/null fields default to empty; save_label tolerates these.
    payload = {
        "name": body.get("name") or "",
        "set": body.get("set") or [],
        "type": body.get("type") or "",
        "element": body.get("element") or [],
    }
    # Reject only genuinely wrong shapes (e.g. a string where a list is expected).
    if not isinstance(payload["name"], str): abort(400)
    if not isinstance(payload["set"], list): abort(400)
    if not isinstance(payload["type"], str): abort(400)
    if not isinstance(payload["element"], list): abort(400)
    try:
        rec = catalog.save_label(card_id, payload)
    except KeyError:
        abort(404)
    return jsonify(rec)


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
# Deck API
# --------------------------------------------------------------------------- #
@app.route("/api/decks", methods=["GET", "POST"])
def api_decks():
    if request.method == "POST":
        name = (request.get_json(silent=True) or {}).get("name", "Untitled Deck")
        deck = decks.create(name)
        return jsonify({"id": deck["id"], "name": deck["name"]}), 201
    return jsonify(decks.list_decks())


@app.route("/api/decks/<deck_id>", methods=["GET", "PUT", "DELETE"])
def api_deck(deck_id):
    if request.method == "DELETE":
        return ("", 204) if decks.delete(deck_id) else abort(404)
    if request.method == "PUT":
        body = request.get_json(silent=True) or {}
        deck = decks.update(deck_id, name=body.get("name"),
                            cards=body.get("cards"))
        if deck is None:
            abort(404)
    resolved = decks.get_resolved(deck_id)
    if resolved is None:
        abort(404)
    return jsonify(resolved)


@app.route("/api/decks/<deck_id>/card", methods=["POST"])
def api_deck_card(deck_id):
    body = request.get_json(silent=True) or {}
    card_id = body.get("card_id")
    count = body.get("count", 0)
    if not isinstance(card_id, str) or not isinstance(count, (int, float)):
        abort(400)
    deck = decks.set_card(deck_id, card_id, count)
    if deck is None:
        abort(404)
    return jsonify(decks.get_resolved(deck_id))


@app.route("/api/decks/<deck_id>/image")
def api_deck_image(deck_id):
    deck = decks.get(deck_id)
    if deck is None:
        abort(404)
    show_badge = request.args.get("badge", "1") != "0"
    try:
        data, info = render.render_deck(deck, show_badge=show_badge)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    fname = f"{deck_id}.jpg"
    resp = send_file(io.BytesIO(data), mimetype="image/jpeg",
                     as_attachment=True, download_name=fname)
    resp.headers["X-Image-Bytes"] = str(info["bytes"])
    return resp


@app.route("/api/decks/<deck_id>/text")
def api_deck_text(deck_id):
    text = decks.export_text(deck_id)
    if text is None:
        abort(404)
    resp = send_file(io.BytesIO(text.encode("utf-8")),
                     mimetype="text/plain; charset=utf-8",
                     as_attachment=True,
                     download_name=f"{deck_id}.txt")
    return resp


@app.route("/api/decks/import", methods=["POST"])
def api_deck_import():
    """Accept a deck-text payload and create a new deck. Body is
    application/json with a 'text' key (preferred) or raw text/plain."""
    name = None
    text = ""
    if request.is_json:
        body = request.get_json(silent=True) or {}
        text = body.get("text") or ""
        name = body.get("name")
    else:
        text = request.get_data(as_text=True) or ""
    if not text.strip():
        return jsonify({"error": "empty payload"}), 400
    deck, warnings = decks.import_text(text, name=name)
    if deck is None:
        return jsonify({"error": "no recognisable cards", "warnings": warnings}), 400
    return jsonify({"id": deck["id"], "name": deck["name"],
                    "warnings": warnings}), 201


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


def init():
    """Scan the catalog and (optionally) kick off the thumbnail prewarm.

    Lives in a function so `import app` (e.g. from tests or a REPL) has zero
    side effects. Call this before app.run()."""
    global _scan
    _scan = catalog.build()
    if config.PREWARM_THUMBS and _scan["exists"]:
        catalog.warm_cache_async(warm_views=config.PREWARM_VIEWS)


if __name__ == "__main__":
    init()
    print(f"Cards dir : {_scan['root']}")
    print(f"Found     : {_scan['card_count']} images "
          f"({_scan['labeled_count']} labeled, "
          f"{_scan['unlabeled_count']} unlabeled)")
    print(f"Labels    : {_scan['labels_path']} "
          f"({_scan['labeled_count']} rows used, "
          f"{_scan['orphaned_label_count']} orphaned)")
    for w in _scan.get("warnings", []):
        print(f"  warn: {w}")
    if not _scan["exists"]:
        print("  !! Card directory not found — drop your scans into "
              f"{_scan['root']} or set BD_CARDS_DIR (see README).")
    if config.PREWARM_THUMBS:
        print("Pre-building thumbnail cache in the background…")
    print("Open your browser to:  http://127.0.0.1:5000   (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
