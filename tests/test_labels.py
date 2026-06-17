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
        BDS1-EN_0001,Light Starter,Phoenix,light,Shadow
        BDS1-EN_0008,Light Starter,Jiro,earth,Partner
    """)
    rows, warnings = labels.load(str(p))
    assert set(rows.keys()) == {"BDS1-EN_0001", "BDS1-EN_0008"}
    jiro = rows["BDS1-EN_0008"]
    assert jiro.id == "BDS1-EN_0008"
    assert jiro.set == ("Light Starter",)
    assert jiro.name == "Jiro"
    assert jiro.element == ("earth",)
    assert jiro.type == "Partner"
    assert warnings == []


def test_load_trims_whitespace(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
         BDS1-EN_0001 , Light Starter , Phoenix , light , Shadow
    """)
    rows, _ = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == ("Light Starter",)
    assert row.name == "Phoenix"
    assert row.element == ("light",)


def test_blank_cells_allowed_and_warned(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,,,
    """)
    rows, warnings = labels.load(str(p))
    row = rows["BDS1-EN_0001"]
    assert row.set == ("Light Starter",)
    assert row.name == ""
    assert row.element == ()
    assert row.type == ""
    assert any("blank" in w.lower() for w in warnings)


def test_duplicate_id_raises(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,Shadow
        BDS1-EN_0001,Light Starter,Phoenix2,light,Partner
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
        "BDS1-EN_0001,Light Starter,Phoenix,light,Shadow\n"
    )
    p.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    rows, _ = labels.load(str(p))
    assert "BDS1-EN_0001" in rows


def test_element_parses_pipe_separated(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDX1-EN_0001,Set 1,Twoface,light|dark,Shadow
    """)
    rows, _ = labels.load(str(p))
    row = rows["BDX1-EN_0001"]
    # Sorted, lowercased, tuple of strings.
    assert row.element == ("dark", "light")


def test_element_lowercased_and_sorted(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDX1-EN_0001,Set 1,X,Wind|Fire|EARTH,Shadow
    """)
    rows, _ = labels.load(str(p))
    assert rows["BDX1-EN_0001"].element == ("earth", "fire", "wind")


def test_single_element_becomes_singleton_tuple(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDS1-EN_0001,Light Starter,Phoenix,light,Shadow
    """)
    rows, _ = labels.load(str(p))
    assert rows["BDS1-EN_0001"].element == ("light",)


def test_empty_element_is_empty_tuple(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDC1-EN_0001,Set 1,Bolt,,Command
    """)
    rows, _ = labels.load(str(p))
    assert rows["BDC1-EN_0001"].element == ()


def test_unknown_element_warns(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDX1-EN_0001,Set 1,X,purple,Shadow
    """)
    rows, warnings = labels.load(str(p))
    assert rows["BDX1-EN_0001"].element == ("purple",)
    assert any("purple" in w and "element" in w.lower() for w in warnings)


def test_unknown_type_warns(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDX1-EN_0001,Set 1,X,light,Vehicles
    """)
    rows, warnings = labels.load(str(p))
    assert rows["BDX1-EN_0001"].type == "Vehicles"
    assert any("Vehicles" in w and "type" in w.lower() for w in warnings)


def test_command_with_element_warns(tmp_path):
    p = write_csv(tmp_path, """
        id,set,name,element,type
        BDC1-EN_0001,Set 1,Bolt,fire,Command
    """)
    rows, warnings = labels.load(str(p))
    # Loaded as-is; the API layer will drop the element. Warning surfaces here.
    assert rows["BDC1-EN_0001"].element == ("fire",)
    assert any("Command" in w and "element" in w.lower() for w in warnings)


def test_dump_roundtrip(tmp_path):
    src_path = write_csv(tmp_path, """
        id,set,name,element,type
        BDB-EN_0002,Set 1,Beta,light|dark,Shadow
        BDA-EN_0001,Set 1,Alpha,fire,Partner
    """)
    rows, _ = labels.load(str(src_path))

    out = tmp_path / "out.csv"
    labels.dump(rows, str(out))

    # File is sorted by id.
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "id,set,name,element,type"
    assert lines[1].startswith("BDA-EN_0001,")
    assert lines[2].startswith("BDB-EN_0002,")
    # Multi-element joined with |, alphabetical.
    assert "dark|light" in lines[2]

    # Round-trip: loading the output yields identical rows.
    rows2, _ = labels.load(str(out))
    assert rows2 == rows


def test_dump_is_atomic(tmp_path, monkeypatch):
    """If os.replace fails the original file must be intact."""
    out = tmp_path / "labels.csv"
    out.write_text("id,set,name,element,type\noriginal,Set,O,light,Shadow\n",
                   encoding="utf-8")
    original_bytes = out.read_bytes()

    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr("os.replace", boom)

    rows_to_write = {"X": labels.LabelRow("X", "Set", "X", ("light",), "Shadow")}
    with pytest.raises(OSError):
        labels.dump(rows_to_write, str(out))

    assert out.read_bytes() == original_bytes