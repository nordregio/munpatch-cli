"""Municipality code change records, parsed from changes.csv.

A change is recorded once, from the point of view of the code that stopped
being valid ("yellow" record: code, year, and what it became). That's
useful for authoring the file by hand, but the extrapolator needs to walk
both forward and backward in time from any code, so `purple_change_transform`
expands each yellow record into "purple" records for every code involved
(old and new), each carrying the valid year range and the reason it starts
or ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

Code = str
Year = int


@dataclass
class RecodeTo:
    new_code: Code


@dataclass
class RecodeFrom:
    old_code: Code


@dataclass
class MergeTo:
    target: Code
    merged_codes: List[Code]


@dataclass
class MergeFrom:
    source_codes: List[Code]


@dataclass
class SplitTo:
    target_codes: List[Code]


@dataclass
class SplitFrom:
    source: Code
    split_codes: List[Code]


ReasonTo = RecodeTo | MergeTo | SplitTo
ReasonFrom = RecodeFrom | MergeFrom | SplitFrom


@dataclass
class CodeChangeYellow:
    code: Code
    year: Year
    recode: RecodeTo | None
    split: SplitTo | None
    merge: MergeTo | None


@dataclass
class CodeChangePurple:
    code: Code
    year_from: Year | None = None
    year_to: Year | None = None
    reason_from: ReasonFrom | None = None
    reason_to: ReasonTo | None = None


def parse_changes(changes_csv: str) -> Dict[Code, CodeChangeYellow]:
    changes_df = pd.read_csv(
        changes_csv,
        sep=",",
        comment="#",  # lines documenting a manually-resolved conflict row
        dtype={
            "Code": "string",
            "Year": "int64",
            "Recode": "string",
            "Split": "string",
            "Merge": "string",
        },
    )
    changes_yellow = dict()
    for _, row in changes_df.iterrows():
        merge = None if pd.isna(row["Merge"]) else row["Merge"].split("/")
        changes_yellow[row["Code"]] = CodeChangeYellow(
            code=Code(row["Code"]),
            year=row["Year"],
            recode=RecodeTo(new_code=row["Recode"])
            if not pd.isna(row["Recode"])
            else None,
            split=SplitTo(target_codes=row["Split"].split(";"))
            if not pd.isna(row["Split"])
            else None,
            merge=MergeTo(target=merge[0], merged_codes=merge[1].split(";"))
            if merge
            else None,
        )
    return changes_yellow


def _parse_reason(
    code: Code, recode: RecodeTo | None, split: SplitTo | None, merge: MergeTo | None
) -> ReasonTo:
    """Transpose from (maybe recode, maybe split, maybe merge) into (maybe reason)."""
    if recode:
        return RecodeTo(recode.new_code)
    if split:
        return SplitTo(split.target_codes)
    if merge:
        return MergeTo(merge.target, merge.merged_codes)
    raise ValueError(f"Code {code} has no reason for a change")


def purple_change_transform(
    changes_yellow: List[CodeChangeYellow],
) -> Dict[Code, CodeChangePurple]:
    results: Dict[Code, CodeChangePurple] = dict()

    def get_or_create(code: Code) -> CodeChangePurple:
        if code not in results:
            results[code] = CodeChangePurple(code)
        return results[code]

    for r in changes_yellow:
        reason_to = _parse_reason(r.code, r.recode, r.split, r.merge)

        source = get_or_create(r.code)
        source.year_to = r.year
        source.reason_to = reason_to

        if isinstance(reason_to, RecodeTo):
            target = get_or_create(reason_to.new_code)
            target.year_from = r.year + 1
            target.reason_from = RecodeFrom(r.code)

        elif isinstance(reason_to, SplitTo):
            for target_code in reason_to.target_codes:
                target = get_or_create(target_code)
                target.year_from = r.year + 1
                target.reason_from = SplitFrom(
                    source=r.code, split_codes=reason_to.target_codes
                )

        elif isinstance(reason_to, MergeTo):
            # A merge target that already existed under this same code (an
            # absorbing municipality that keeps its number) is continuous,
            # not new -- it must not get a year_from/reason_from of its own,
            # or backward extrapolation would sum it as one of its own
            # sources and recurse forever.
            if reason_to.target not in reason_to.merged_codes:
                target = get_or_create(reason_to.target)
                target.year_from = r.year + 1
                target.reason_from = MergeFrom(source_codes=reason_to.merged_codes)

    return results


def is_valid_in_year(code: Code, changes: Dict[Code, CodeChangePurple], year: Year) -> bool:
    """Whether `code` was a valid, in-use municipality code in `year`.

    A code with no entry in `changes` never changed, so it's valid for the
    whole range. Otherwise it's valid from its year_from (if any, i.e. it was
    born from a recode/split/merge) through its year_to (if any, i.e. it
    later stopped being valid itself).
    """
    change = changes.get(code)
    if change is None:
        return True
    return (change.year_from is None or year >= change.year_from) and (
        change.year_to is None or year <= change.year_to
    )
