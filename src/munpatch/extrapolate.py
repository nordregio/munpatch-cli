"""Core extrapolation algorithm.

Fills in missing (code, year) values by walking the municipality change
graph built by `munpatch.changes.purple_change_transform`, recursively and
with memoization. See DOCUMENTATION for the extrapolation rules; this module
only implements them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd

from munpatch.changes import (
    Code,
    CodeChangePurple,
    MergeFrom,
    MergeTo,
    RecodeFrom,
    RecodeTo,
    SplitFrom,
    SplitTo,
    Year,
    is_valid_in_year,
)


@dataclass
class InputRecord:
    code: Code
    year: Year
    value: float


class MissingChangeError(ValueError):
    """Raised when input data has a code with no matching entry in changes.csv."""


class MissingPopulationError(ValueError):
    """Raised when a (code, year) needed for ratio extrapolation has no
    matching population figure."""


def parse_input(input_csv: str) -> Dict[Tuple[Code, Year], InputRecord]:
    input_df = pd.read_csv(
        input_csv,
        sep="\t",
        dtype={"Code": "string", "Year": "int64", "Value": "float"},
    )
    return {
        (row["Code"], row["Year"]): InputRecord(
            code=row["Code"], year=row["Year"], value=row["Value"]
        )
        for _, row in input_df.iterrows()
    }


def validate_codes(
    input_records: Dict[Tuple[Code, Year], InputRecord],
    changes: Dict[Code, CodeChangePurple],
) -> None:
    """Raise with a clear message if any code disappears from the input data
    before the last year in it, but has no entry in changes.csv to explain why.
    """
    years_by_code: Dict[Code, list[Year]] = {}
    for code, year in input_records:
        years_by_code.setdefault(code, []).append(year)

    last_year = max(year for _, year in input_records)
    missing = sorted(
        code
        for code, years in years_by_code.items()
        if max(years) < last_year and code not in changes
    )
    if missing:
        raise MissingChangeError(
            "The following codes disappear from the input data before "
            f"{last_year} but have no entry in changes.csv: {', '.join(missing)}"
        )


def extrapolate(
    input_records: Dict[Tuple[Code, Year], InputRecord],
    changes: Dict[Code, CodeChangePurple],
) -> Dict[Tuple[Code, Year], float]:
    result: Dict[Tuple[Code, Year], float] = dict()

    def calculate(code: Code, year: Year) -> float:
        key = (code, year)
        if key in result:
            return result[key]

        if key in input_records:
            value = input_records[key].value

        else:
            change = changes[code]
            value = math.nan

            if year < (change.year_from or 0):
                reason = change.reason_from

                if isinstance(reason, RecodeFrom):
                    value = calculate(reason.old_code, year)

                elif isinstance(reason, SplitFrom):
                    value = (
                        calculate(code, year + 1)
                        / calculate(reason.source, year + 1)
                        * calculate(reason.source, year)
                    )

                elif isinstance(reason, MergeFrom):
                    value = sum(calculate(c, year) for c in reason.source_codes)

            elif year > (change.year_to or 9999):
                reason = change.reason_to

                if isinstance(reason, RecodeTo):
                    value = calculate(reason.new_code, year)

                elif isinstance(reason, SplitTo):
                    value = sum(calculate(c, year) for c in reason.target_codes)

                elif isinstance(reason, MergeTo):
                    value = (
                        calculate(code, year - 1)
                        / sum(calculate(c, year - 1) for c in reason.merged_codes)
                        * calculate(reason.target, year)
                    )

        result[key] = value
        return value

    years = [year for _, year in input_records]
    codes = sorted({code for code, _ in input_records})
    for year in range(min(years), max(years) + 1):
        for code in codes:
            calculate(code, year)

    return result


def extrapolate_ratio(
    input_records: Dict[Tuple[Code, Year], InputRecord],
    changes: Dict[Code, CodeChangePurple],
    population: Dict[Tuple[Code, Year], float],
) -> Dict[Tuple[Code, Year], float]:
    """Extrapolate a rate/percentage indicator across boundary changes.

    `extrapolate`'s merge/split rules (sum on merge, proportional share on
    split) are only valid for absolute counts -- see README, "Absolute
    counts vs. rates/percentages". A rate can't be summed or split that way
    directly, so this converts each rate to an absolute count via
    `population` at that (code, year), extrapolates the counts with the
    normal count rules, then converts back to a rate using `population` at
    the target (code, year).
    """
    missing = sorted(key for key in input_records if key not in population)
    if missing:
        raise MissingPopulationError(
            "No population figure to convert the following to an absolute "
            f"count: {', '.join(f'{code}/{year}' for code, year in missing)}"
        )

    counts = {
        key: InputRecord(key[0], key[1], record.value * population[key])
        for key, record in input_records.items()
    }
    extrapolated_counts = extrapolate(counts, changes)

    missing = sorted(key for key in extrapolated_counts if key not in population)
    if missing:
        raise MissingPopulationError(
            "No population figure to convert the extrapolated count back to "
            f"a rate for: {', '.join(f'{code}/{year}' for code, year in missing)}"
        )

    return {key: value / population[key] for key, value in extrapolated_counts.items()}


def write_output(result: Dict[Tuple[Code, Year], float], output_csv: str) -> None:
    rows = sorted(
        ({"Year": year, "Code": code, "Value": value} for (code, year), value in result.items()),
        key=lambda r: (r["Year"], r["Code"]),
    )
    pd.DataFrame(rows, columns=["Year", "Code", "Value"]).to_csv(
        output_csv, sep="\t", index=False
    )


def cod_mun(code: Code) -> str:
    """The join key used by the Nordregio Nordic municipality shapefiles'
    `COD_MUN` field: the ISO country prefix plus the zero-padded code, e.g.
    '301' -> 'NO0301'.
    """
    return f"NO{code.zfill(4)}"


def write_structure_output(result: Dict[Tuple[Code, Year], float], output_csv: str) -> None:
    """Write one row per code, with a COD_MUN join key for the Nordregio
    Nordic municipality shapefiles' attribute table and one column per year
    -- ready to merge directly onto the map data.
    """
    codes = sorted({code for code, _ in result})
    years = sorted({year for _, year in result})
    rows = [
        {
            "Code": code,
            "COD_MUN": cod_mun(code),
            **{str(year): result.get((code, year)) for year in years},
        }
        for code in codes
    ]
    columns = ["Code", "COD_MUN", *(str(year) for year in years)]
    pd.DataFrame(rows, columns=columns).to_csv(output_csv, sep="\t", index=False)


def read_output(output_csv: str) -> Dict[Tuple[Code, Year], float]:
    """Read back a file written by `write_output`."""
    df = pd.read_csv(
        output_csv,
        sep="\t",
        dtype={"Code": "string", "Year": "int64", "Value": "float"},
    )
    return {(row["Code"], row["Year"]): row["Value"] for _, row in df.iterrows()}


def filter_to_year(
    result: Dict[Tuple[Code, Year], float],
    changes: Dict[Code, CodeChangePurple],
    year: Year,
) -> Dict[Tuple[Code, Year], float]:
    """Keep only the codes that were valid municipality codes in `year`.

    The extrapolated matrix has a full time series for every code that ever
    existed across the input's date range (including codes later merged,
    split, or recoded away). This narrows that down to one consistent set of
    codes -- the municipal structure as of `year` -- each still carrying its
    full extrapolated time series.
    """
    return {
        (code, y): value
        for (code, y), value in result.items()
        if is_valid_in_year(code, changes, year)
    }
