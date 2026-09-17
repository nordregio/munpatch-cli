"""Generate a changes.csv from the SSB/Kartverket KOM Masterliste.

The masterlist (a KOM_Masterliste_*.xlsx file, sheet "MASTERLISTE") is the
authoritative history of every Norwegian municipality code back to 1838:
one row per (old code, new code) pair, with a TypeOfChange telling you what
kind of change it was.

This module turns that into the same Code,Year,Recode,Split,Merge format
`munpatch.changes.parse_changes` reads -- one row per code that stopped
being valid. Most of the masterlist can be translated mechanically. A few
real cases can't be represented by the one-row-per-code format at all (a
code that splits its territory across two different merge targets in the
same year, for instance) -- those are reported as conflicts instead of
guessed at, for a human to resolve by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import pandas as pd

Code = str
Year = int

# A code changing purely in TypeOfChange terms; "Navneendring" (name-only,
# same code) and self-absorbing merge/split rows (kilde_kode == maal_kode)
# don't represent a code change and are excluded elsewhere.
RECODE_TYPES = {"Kodeendring", "Kode- og navneendring"}

Event = Tuple[Year, str, Any]  # (year, "Recode"|"Merge"|"Split", payload)


@dataclass
class GeneratedChanges:
    rows: List[Dict[str, str]]
    # code -> its competing events, when a code has more than one qualifying
    # event in the window (it genuinely changed twice, or split its
    # territory across multiple targets in one change) -- needs a human to
    # pick/reconcile, so no row is emitted for it.
    conflicts: Dict[Code, List[Event]] = field(default_factory=dict)


def load_masterlist(path: str, sheet_name: str = "MASTERLISTE") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    df["kilde_kode"] = df["kilde_kode"].astype(int).astype(str).str.zfill(4)
    df["maal_kode"] = df["maal_kode"].astype(int).astype(str).str.zfill(4)
    df["kilde_gyldig_til"] = df["kilde_gyldig_til"].astype(int)
    return df


def generate_changes(masterlist: pd.DataFrame, min_year: int) -> GeneratedChanges:
    ml = masterlist[masterlist["kilde_gyldig_til"] >= min_year]
    events: Dict[Code, List[Event]] = {}

    # Recode: 1-to-1, only where the code actually changes.
    recodes = ml[ml["TypeOfChange"].isin(RECODE_TYPES) & (ml["kilde_kode"] != ml["maal_kode"])]
    for _, r in recodes.iterrows():
        events.setdefault(r["kilde_kode"], []).append(
            (r["kilde_gyldig_til"], "Recode", r["maal_kode"])
        )

    # Merge: group over ALL rows sharing (target, year), including a
    # self-absorbing row (kilde_kode == maal_kode) when the absorbing
    # municipality keeps its own code -- that code belongs in the source
    # list (matches the file's existing convention) but, since it doesn't
    # disappear, gets no row of its own.
    merges = ml[ml["TypeOfChange"] == "Sammenslåing"]
    for (target, year), grp in merges.groupby(["maal_kode", "kilde_gyldig_til"]):
        sources = tuple(sorted(grp["kilde_kode"].unique()))
        for source in sources:
            if source == target:
                continue
            events.setdefault(source, []).append((year, "Merge", (target, sources)))

    # Split: group by (source, year). If the source also appears among its
    # own targets, it's a boundary tweak (the source keeps existing, just
    # donates territory) rather than a real split -- skip it, it needs no
    # change record.
    splits = ml[ml["TypeOfChange"] == "Deling"]
    for (source, year), grp in splits.groupby(["kilde_kode", "kilde_gyldig_til"]):
        targets = tuple(sorted(grp["maal_kode"].unique()))
        if source in targets:
            continue
        events.setdefault(source, []).append((year, "Split", targets))

    rows: List[Dict[str, str]] = []
    conflicts: Dict[Code, List[Event]] = {}
    for code in sorted(events):
        code_events = events[code]
        if len(code_events) > 1:
            conflicts[code] = code_events
            continue

        year, kind, payload = code_events[0]
        row = {"Code": code, "Year": str(year), "Recode": "", "Split": "", "Merge": ""}
        if kind == "Recode":
            row["Recode"] = payload
        elif kind == "Split":
            row["Split"] = ";".join(payload)
        elif kind == "Merge":
            target, sources = payload
            row["Merge"] = f"{target}/{';'.join(sources)}"
        rows.append(row)

    return GeneratedChanges(rows=rows, conflicts=conflicts)


def write_changes_csv(rows: List[Dict[str, str]], output_path: str) -> None:
    fieldnames = ["Code", "Year", "Recode", "Split", "Merge"]
    pd.DataFrame(rows, columns=fieldnames).to_csv(output_path, index=False)
