"""Registry of SSB indicators this tool knows how to fetch and extrapolate.

Adding a new absolute-count indicator (poverty, employment, ...) means
adding one more `IndicatorConfig` entry below with its own table id, query
parameters, and output paths -- fetch, extrapolate, and the CLI all work off
this registry without further changes. A rate/percentage indicator (a
share, a rate, an average -- anything that can't be summed or split the way
a count can) additionally needs `weight_by` set to the name of a count
indicator to weight it by (usually "population") -- see README, "Absolute
counts vs. rates/percentages".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class IndicatorConfig:
    table_id: str
    contents_code: str
    raw_path: str
    processed_path: str
    age_code: str | None = "999A"  # SSB code for "all ages combined"; None if the table has no Alder dimension
    region_codelist: str = "vs_Kommune"
    weight_by: str | None = None  # name of the population indicator, for a rate/percentage indicator
    min_year: int = 2010

    def query(self) -> Dict[str, Any]:
        selection = [
            {"variableCode": "ContentsCode", "valueCodes": [self.contents_code]},
            {"variableCode": "Tid", "valueCodes": ["*"]},
            {
                "variableCode": "Region",
                "valueCodes": ["*"],
                "codelist": self.region_codelist,
            },
        ]
        stub = ["Region"]
        if self.age_code is not None:
            selection.append({"variableCode": "Alder", "valueCodes": [self.age_code]})
            stub.append("Alder")

        return {
            "selection": selection,
            "placement": {
                "heading": ["ContentsCode", "Tid"],
                "stub": stub,
            },
        }


INDICATORS: Dict[str, IndicatorConfig] = {
    "migration_in": IndicatorConfig(
        table_id="13255",
        contents_code="Innflytting",
        raw_path="data/raw/migration_in.csv",
        processed_path="data/processed/migration_in.csv",
    ),
    "migration_out": IndicatorConfig(
        table_id="13255",
        contents_code="Utflytting",
        raw_path="data/raw/migration_out.csv",
        processed_path="data/processed/migration_out.csv",
    ),
    # No Alder dimension on this table -- Folkemengde is already the total
    # population, not broken down by age/sex the way 07459 is. Used as the
    # weight for extrapolating rate/percentage indicators (see weight_by).
    "population": IndicatorConfig(
        table_id="06913",
        contents_code="Folkemengde",
        raw_path="data/raw/population.csv",
        processed_path="data/processed/population.csv",
        age_code=None,
        region_codelist="vs_Kommuner1951",
    ),
    # A rate, not a count -- extrapolated via extrapolate_ratio(), weighted
    # by population (see README, "Absolute counts vs. rates/percentages").
    # No Alder dimension on this table either.
    "gini": IndicatorConfig(
        table_id="09114",
        contents_code="Ginikoeffisient",
        raw_path="data/raw/gini.csv",
        processed_path="data/processed/gini.csv",
        age_code=None,
        weight_by="population",
    ),
}


def resolve(name: str) -> Dict[str, IndicatorConfig]:
    """Resolve a CLI --indicator value ("all" or a single name) to a dict of configs."""
    if name == "all":
        return INDICATORS
    if name not in INDICATORS:
        known = ", ".join(sorted(INDICATORS))
        raise KeyError(f"Unknown indicator '{name}'. Known indicators: {known}")
    return {name: INDICATORS[name]}
