"""Parse the labels.csv metadata file into in-memory rows.

Returned by load():
  rows:     dict[id, LabelRow]  -- whitespace-trimmed, raw-case fields
  warnings: list[str]           -- non-fatal issues (missing file, blank
                                   cells, unknown vocab, ...)

Raises LabelError on structural problems (duplicate id, missing required
column, malformed CSV)."""
import csv
import os
from dataclasses import dataclass

import vocab


REQUIRED_COLUMNS = ("id", "set", "name", "element", "type", "duplicate_of")


class LabelError(ValueError):
    """Structural problem with labels.csv that prevents the app from running."""


@dataclass(frozen=True)
class LabelRow:
    id: str
    set: str
    name: str
    element: tuple    # sorted, lowercased, deduped
    type: str
    duplicate_of: str = ""    # id of the canonical card (empty if this is canonical)


def _parse_elements(cell):
    """`light|Dark` -> ('dark', 'light'). Empty / blank -> ()."""
    parts = [p.strip().lower() for p in cell.split("|")]
    return tuple(sorted({p for p in parts if p}))


def load(path):
    if not os.path.isfile(path):
        return {}, [f"labels.csv not found at {os.path.abspath(path)}"]

    rows = {}
    warnings = []

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise LabelError(f"{path}: file is empty (expected header row)")

        header = [h.strip() for h in header]
        # `duplicate_of` is a later addition — old files without the column
        # are tolerated; the field just defaults to empty for every row.
        missing = [c for c in REQUIRED_COLUMNS if c not in header
                   and c != "duplicate_of"]
        if missing:
            raise LabelError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        idx = {c: header.index(c) for c in REQUIRED_COLUMNS if c in header}

        for line_no, raw in enumerate(reader, start=2):
            if not raw or all(not (c or "").strip() for c in raw):
                continue
            cells = [(raw[i].strip() if i < len(raw) else "")
                     for i in range(len(header))]
            row_id = cells[idx["id"]]
            if not row_id:
                warnings.append(f"{path}:{line_no} blank id, row skipped")
                continue
            if row_id in rows:
                raise LabelError(
                    f"{path}:{line_no} duplicate id {row_id!r}"
                )

            row = LabelRow(
                id=row_id,
                set=cells[idx["set"]],
                name=cells[idx["name"]],
                element=_parse_elements(cells[idx["element"]]),
                type=cells[idx["type"]],
                duplicate_of=(cells[idx["duplicate_of"]]
                              if "duplicate_of" in idx else ""),
            )

            blanks = [f for f in ("name", "type") if not getattr(row, f)]
            if not row.element and row.type not in vocab.TYPES_WITHOUT_ELEMENT:
                blanks.append("element")
            if blanks:
                warnings.append(
                    f"{path}:{line_no} {row.id} has blank {', '.join(blanks)}"
                )

            for el in row.element:
                if el not in vocab.KNOWN_ELEMENTS:
                    warnings.append(
                        f"{path}:{line_no} {row.id} has unknown element {el!r}"
                    )
            if row.type and row.type not in vocab.KNOWN_TYPES:
                warnings.append(
                    f"{path}:{line_no} {row.id} has unknown type {row.type!r}"
                )
            if row.type in vocab.TYPES_WITHOUT_ELEMENT and row.element:
                warnings.append(
                    f"{path}:{line_no} {row.id} type={row.type} carries element "
                    f"{list(row.element)!r}; element will be ignored over the API"
                )

            rows[row_id] = row

    return rows, warnings


def dump(rows, path):
    """Atomically rewrite `path` with the rows sorted by id."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(REQUIRED_COLUMNS)
            for cid in sorted(rows):
                row = rows[cid]
                writer.writerow([
                    row.id,
                    row.set,
                    row.name,
                    "|".join(row.element),
                    row.type,
                    row.duplicate_of,
                ])
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
