"""Coverage for the duplicate_of feature: canonical resolution and the
deck cap that's shared across a duplicate group."""
import importlib

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    cards = tmp_path / "cards"
    cards.mkdir()
    for fname in ("BDS1-EN_0008.jpg", "BDH1-EN_0006.jpg", "BD01-EN_0001.jpg"):
        (cards / fname).write_bytes(b"x")

    labels_csv = tmp_path / "labels.csv"
    labels_csv.write_text(
        "id,set,name,element,type,duplicate_of\n"
        "BDS1-EN_0008,Light Starter,Jiro,earth,Partner,\n"
        "BDH1-EN_0006,Demo Deck,Jiro,earth,Partner,BDS1-EN_0008\n"
        "BD01-EN_0001,Set 1,Sulvier,fire,Shadow,\n",
        encoding="utf-8",
    )

    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    monkeypatch.setenv("BD_CARDS_DIR", str(cards))
    monkeypatch.setenv("BD_LABELS_PATH", str(labels_csv))

    import config
    importlib.reload(config)
    monkeypatch.setattr(config, "DECKS_DIR", str(decks_dir))
    monkeypatch.setattr(config, "CACHE_DIR", str(cache_dir))
    import catalog
    importlib.reload(catalog)
    import decks
    importlib.reload(decks)
    catalog.build()
    return catalog, decks


def test_resolve_canonical_follows_duplicate_of(world):
    catalog, _ = world
    assert catalog.resolve_canonical("BDH1-EN_0006") == "BDS1-EN_0008"
    assert catalog.resolve_canonical("BDS1-EN_0008") == "BDS1-EN_0008"


def test_resolve_canonical_handles_missing_target(world):
    catalog, _ = world
    catalog.save_label("BDH1-EN_0006", {
        "name": "Jiro", "set": "Demo Deck", "type": "Partner",
        "element": ["earth"], "duplicate_of": "NOPE-EN_9999",
    })
    assert catalog.resolve_canonical("BDH1-EN_0006") == "BDH1-EN_0006"


def test_resolve_canonical_breaks_cycles(world):
    catalog, _ = world
    catalog.save_label("BDS1-EN_0008", {
        "name": "Jiro", "set": "Light Starter", "type": "Partner",
        "element": ["earth"], "duplicate_of": "BDH1-EN_0006",
    })
    a = catalog.resolve_canonical("BDS1-EN_0008")
    b = catalog.resolve_canonical("BDH1-EN_0006")
    assert a in {"BDS1-EN_0008", "BDH1-EN_0006"}
    assert b in {"BDS1-EN_0008", "BDH1-EN_0006"}


def test_save_label_refuses_self_reference(world):
    catalog, _ = world
    rec = catalog.save_label("BDS1-EN_0008", {
        "name": "Jiro", "set": "Light Starter", "type": "Partner",
        "element": ["earth"], "duplicate_of": "BDS1-EN_0008",
    })
    assert rec["duplicate_of"] == ""


def test_api_record_exposes_canonical_id(world):
    catalog, _ = world
    rec = catalog.get_api("BDH1-EN_0006")
    assert rec["duplicate_of"] == "BDS1-EN_0008"
    assert rec["canonical_id"] == "BDS1-EN_0008"


def test_deck_cap_aggregates_across_duplicate_group(world):
    _, decks = world
    deck_id = decks.create("dup-cap-test")["id"]
    decks.set_card(deck_id, "BDS1-EN_0008", 3)
    after = decks.set_card(deck_id, "BDH1-EN_0006", 2)
    assert after["cards"].get("BDH1-EN_0006", 0) == 0
    assert after["cards"]["BDS1-EN_0008"] == 3


def test_deck_update_distributes_within_group_cap(world):
    _, decks = world
    deck_id = decks.create("dup-update-test")["id"]
    after = decks.update(deck_id, cards={
        "BDS1-EN_0008": 2,
        "BDH1-EN_0006": 2,
    })
    counts = after["cards"]
    total_in_group = counts.get("BDS1-EN_0008", 0) + counts.get("BDH1-EN_0006", 0)
    assert total_in_group == 3


def test_unrelated_cards_have_independent_caps(world):
    _, decks = world
    deck_id = decks.create("unrelated-test")["id"]
    decks.set_card(deck_id, "BDS1-EN_0008", 3)
    after = decks.set_card(deck_id, "BD01-EN_0001", 3)
    assert after["cards"]["BD01-EN_0001"] == 3
    assert after["cards"]["BDS1-EN_0008"] == 3
