"""Generic SSB (Statistics Norway) table fetcher.

Every data_fetch_*.py script in the old project did the same three things:
POST a query to the SSB pxwebapi, parse the JSON-STAT2 response with
pyjstat, and clean the resulting frame down to (Code, Year, Value). This
module is that logic, once, parameterized by table id and query.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import requests
from pyjstat import pyjstat

SSB_TABLE_URL = "https://data.ssb.no/api/pxwebapi/v2/tables/{table_id}/data"


def fetch_ssb(table_id: str, query: Dict[str, Any], min_year: int = 2010) -> pd.DataFrame:
    """Fetch a table from the SSB API and return a clean (Code, Year, Value) frame.

    Keeps only 4-digit municipality codes, drops zero values (SSB uses 0 as a
    placeholder for suppressed/unavailable cells in count tables like
    migration, not a real count) and null cells (json-stat2's own convention
    for a suppressed/unavailable cell, e.g. small-municipality Gini
    coefficients SSB won't disclose), and restricts to years after
    `min_year`.
    """
    url = SSB_TABLE_URL.format(table_id=table_id)
    response = requests.post(
        url, json=query, params={"lang": "en", "outputFormat": "json-stat2"}
    )
    response.raise_for_status()
    dataset = pyjstat.Dataset.read(response.text)

    df = dataset.write("dataframe")
    id_df = dataset.write("dataframe", naming="id")
    df["code"] = id_df.iloc[:, 0]

    df = df[df["code"].str.len() == 4]
    df = df[["code", "year", "value"]]
    df = df.dropna(subset=["value"])
    df = df[df["value"] != 0]
    df["value"] = df["value"].astype(float)
    df["year"] = df["year"].astype(int)
    df = df[df["year"] > min_year]
    df.columns = ["Code", "Year", "Value"]
    return df.reset_index(drop=True)
