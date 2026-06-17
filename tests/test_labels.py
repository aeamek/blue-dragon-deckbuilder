import textwrap

import pytest

import labels


def write_csv(tmp_path, content):
    p = tmp_path / "labels.csv"
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


def test_load_basic(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,shadow
        BDS1-EN_0008,Light Starter,Jiro,earth,partner
    """)
    rows, warnings = labels.load(str(p))
    assert set(rows.keys()) == {"BDS1-EN_0001", "BDS1-EN_0008"}
    jiro = rows["BDS1-EN_0008"]
    assert jiro.id == "BDS1-EN_0008"
    assert jiro.set == "Light Starter"
    assert jiro.name == "Jiro"
    assert jiro.element == "earth"
    assert jiro.type == "partner"
    assert warnings == []


def test_load_trims_whitespace(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
         BDS1-EN_0001 , Light Starter , Phoenix , light , shadow
    """)
    rows, _ = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == "Light Starter"
    assert row.name == "Phoenix"
    assert row.element == "light"


def test_blank_cells_allowed_and_warned(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,,,
    """)
    rows, warnings = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == "Light Starter"
    assert row.name == ""
    assert row.element == ""
    assert row.type == ""
    assert any("blank" in w.lower() for w in warnings)


def test_duplicate_id_raises(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,shadow
        BDS1-EN_0001,Light Starter,Phoenix2,light,event
    """)
    with pytest.raises(labels.LabelError) as exc:
        labels.load(str(p))
    assert "BDS1-EN_0001" in str(exc.value)


def test_missing_required_column_raises(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element
        BDS1-EN_0001,Light Starter,Phoenix,light
    """)
    with pytest.raises(labels.LabelError) as exc:
        labels.load(str(p))
    assert "type" in str(exc.value)


def test_missing_file_returns_empty_with_warning(tmp_path):
    rows, warnings = labels.load(str(tmp_path / "nope.csv"))
    assert rows == {}
    assert len(warnings) == 1
    assert "not found" in warnings[0].lower()


def test_load_handles_utf8_bom(tmp_path):
    """A CSV saved by Excel / Numbers / Google Sheets starts with a UTF-8 BOM.
    If we open with plain utf-8 the BOM ends up on the first header so the
    `id` column 'goes missing' — verify the loader strips it transparently."""
    p = tmp_path / "labels.csv"
    body = (
        "id,set,name,element,type\n"
        "BDS1-EN_0001,Light Starter,Phoenix,light,shadow\n"
    )
    p.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    rows, _ = labels.load(str(p))
    assert "BDS1-EN_0001" in rows
