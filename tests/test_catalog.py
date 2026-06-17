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
        "BDS1-EN_0002,Light Starter,Jiro,light,partner\n"   # same element, different case
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
    assert summary["card_count"] == 3
    assert summary["labeled_count"] == 2
    assert summary["unlabeled_count"] == 1
    assert summary["orphaned_label_count"] == 1

    rec = catalog.get("BDS1-EN_0001")
    assert rec["label"].name == "Phoenix"
    assert rec["label"].set == "Light Starter"

    rec = catalog.get("BDS1-EN_9999")
    assert rec["label"] is None

    assert catalog.get("BDS1-EN_8888") is None


def test_seen_values_dedupe_case_insensitive(fake_cards):
    catalog = fake_cards
    catalog.build()
    # Both labeled cards use "light"/"Light" — dedupe to one chip.
    elements = catalog.elements_seen()
    assert len(elements) == 1
    assert elements[0].lower() == "light"
    # First-seen casing wins for display.
    assert elements[0] == "Light"

    # Two distinct types — Shadow and partner.
    types = catalog.types_seen()
    assert sorted(t.lower() for t in types) == ["partner", "shadow"]


def test_sets_seen_from_labels(fake_cards):
    catalog = fake_cards
    catalog.build()
    assert catalog.sets_seen() == ["Light Starter"]
