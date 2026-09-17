from munpatch.indicators import IndicatorConfig


def test_query_includes_age_selection_by_default():
    config = IndicatorConfig(
        table_id="13255", contents_code="Innflytting", raw_path="raw.csv", processed_path="processed.csv"
    )

    query = config.query()

    variables = {s["variableCode"]: s for s in query["selection"]}
    assert variables["Alder"]["valueCodes"] == ["999A"]
    assert variables["Region"]["codelist"] == "vs_Kommune"
    assert "Alder" in query["placement"]["stub"]


def test_query_omits_age_selection_when_age_code_is_none():
    # Some SSB tables (e.g. 06913, population) have no Alder dimension at
    # all -- their ContentsCode is already the total, not broken down by age.
    config = IndicatorConfig(
        table_id="06913",
        contents_code="Folkemengde",
        raw_path="raw.csv",
        processed_path="processed.csv",
        age_code=None,
        region_codelist="vs_Kommuner1951",
    )

    query = config.query()

    variables = {s["variableCode"]: s for s in query["selection"]}
    assert "Alder" not in variables
    assert variables["Region"]["codelist"] == "vs_Kommuner1951"
    assert "Alder" not in query["placement"]["stub"]
