import importlib
import os
import threading

import pytest


@pytest.fixture
def fake_world(tmp_path, monkeypatch):
    """A cards dir + empty labels.csv, with config/catalog reloaded to point
    at them. Returns (catalog_module, labels_csv_path)."""
    cards = tmp_path / "cards"
    cards.mkdir()
    for fname in ("BDS1-EN_0001.jpg", "BDS1-EN_0002.jpg", "BDC1-EN_0001.jpg"):
        (cards / fname).write_bytes(b"x")

    labels_csv = tmp_path / "labels.csv"
    labels_csv.write_text("id,set,name,element,type\n", encoding="utf-8")

    monkeypatch.setenv("BD_CARDS_DIR", str(cards))
    monkeypatch.setenv("BD_LABELS_PATH", str(labels_csv))

    import config
    import catalog
    importlib.reload(config)
    importlib.reload(catalog)
    catalog.build()
    return catalog, labels_csv


def test_save_creates_row(fake_world):
    catalog, csv_path = fake_world
    rec = catalog.save_label("BDS1-EN_0001", {
        "name": "Phoenix",
        "set": ["Light Starter"],
        "type": "Shadow",
        "element": ["light"],
    })
    assert rec["name"] == "Phoenix"
    assert rec["element"] == ["light"]

    text = csv_path.read_text(encoding="utf-8")
    assert "Phoenix" in text
    assert "BDS1-EN_0001,Light Starter,Phoenix,light,Shadow" in text


def test_save_updates_existing_row(fake_world):
    catalog, _ = fake_world
    catalog.save_label("BDS1-EN_0001", {
        "name": "Phoenix",
        "set": ["Light Starter"],
        "type": "Shadow",
        "element": ["light"],
    })
    rec = catalog.save_label("BDS1-EN_0001", {
        "name": "Phoenix Reborn",
        "set": ["Light Starter"],
        "type": "Shadow",
        "element": ["light", "fire"],
    })
    assert rec["name"] == "Phoenix Reborn"
    assert rec["element"] == ["fire", "light"]   # sorted


def test_save_unknown_card_raises(fake_world):
    catalog, _ = fake_world
    with pytest.raises(KeyError):
        catalog.save_label("NOPE-EN_9999", {
            "name": "Ghost",
            "set": ["Set 1"],
            "type": "Shadow",
            "element": ["light"],
        })


def test_save_command_clears_element(fake_world):
    catalog, csv_path = fake_world
    rec = catalog.save_label("BDC1-EN_0001", {
        "name": "Bolt",
        "set": ["Set 1"],
        "type": "Command",
        "element": ["fire", "light"],
    })
    assert rec["element"] == []
    text = csv_path.read_text(encoding="utf-8")
    assert "BDC1-EN_0001,Set 1,Bolt,,Command" in text


def test_concurrent_saves_dont_corrupt(fake_world):
    catalog, csv_path = fake_world
    ready = threading.Barrier(2)
    errors = []

    def worker(cid, name):
        ready.wait()
        try:
            catalog.save_label(cid, {
                "name": name, "set": ["Light Starter"],
                "type": "Shadow", "element": ["light"],
            })
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker, args=("BDS1-EN_0001", "Alpha"))
    t2 = threading.Thread(target=worker, args=("BDS1-EN_0002", "Beta"))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errors == []

    text = csv_path.read_text(encoding="utf-8")
    assert "BDS1-EN_0001,Light Starter,Alpha,light,Shadow" in text
    assert "BDS1-EN_0002,Light Starter,Beta,light,Shadow" in text


def test_in_memory_catalog_updates(fake_world):
    catalog, _ = fake_world
    catalog.save_label("BDS1-EN_0001", {
        "name": "Phoenix",
        "set": ["Light Starter"],
        "type": "Shadow",
        "element": ["light"],
    })
    rec = catalog.get_api("BDS1-EN_0001")
    assert rec["name"] == "Phoenix"
    assert rec["element"] == ["light"]
