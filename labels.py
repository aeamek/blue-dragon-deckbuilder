"""Parse the labels.csv metadata file into in-memory rows.

Returned by load():
  rows:     dict[id, LabelRow]  -- whitespace-trimmed, raw-case fields
  warnings: list[str]           -- non-fatal issues (missing file, blank cells, ...)

Raises LabelError on structural problems (duplicate id, missing required column,
malformed CSV)."""
import csv
import os
from dataclasses import dataclass


REQUIRED_COLUMNS = ("id", "set", "name", "element", "type")


class LabelError(ValueError):
    """Structural problem with labels.csv that prevents the app from running."""


@dataclass(frozen=True)
class LabelRow:
    id: str
    set: str
    name: str
    element: str
    type: str


def load(path):
    if not os.path.isfile(path):
        return {}, [f"labels.csv not found at {os.path.abspath(path)}"]

    rows = {}
    warnings = []

    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise LabelError(f"{path}: file is empty (expected header row)")

        header = [h.strip() for h in header]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise LabelError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        idx = {c: header.index(c) for c in REQUIRED_COLUMNS}

        for line_no, raw in enumerate(reader, start=2):
            if not raw or all(not (c or "").strip() for c in raw):
                continue
            cells = [(raw[i].strip() if i < len(raw) else "") for i in range(len(header))]
            row = LabelRow(
                id=cells[idx["id"]],
                set=cells[idx["set"]],
                name=cells[idx["name"]],
                element=cells[idx["element"]],
                type=cells[idx["type"]],
            )
            if not row.id:
                warnings.append(f"{path}:{line_no} blank id, row skipped")
                continue
            if row.id in rows:
                raise LabelError(
                    f"{path}:{line_no} duplicate id {row.id!r} "
                    f"(also at line where it was first seen)"
                )
            blanks = [f for f in ("name", "element", "type")
                      if not getattr(row, f)]
            if blanks:
                warnings.append(
                    f"{path}:{line_no} {row.id} has blank {', '.join(blanks)}"
                )
            rows[row.id] = row

    return rows, warnings
