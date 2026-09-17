import pandas as pd

from munpatch.masterlist import generate_changes


def masterlist_df(rows):
    """rows: list of (kilde_kode, maal_kode, kilde_gyldig_til, TypeOfChange), already
    4-digit strings for the codes, matching what load_masterlist() would produce."""
    return pd.DataFrame(
        rows, columns=["kilde_kode", "maal_kode", "kilde_gyldig_til", "TypeOfChange"]
    )


def test_simple_recode():
    df = masterlist_df([("0101", "3001", 2019, "Kodeendring")])
    result = generate_changes(df, min_year=2010)

    assert result.conflicts == {}
    assert result.rows == [{"Code": "0101", "Year": "2019", "Recode": "3001", "Split": "", "Merge": ""}]


def test_name_only_change_is_ignored():
    df = masterlist_df([("0101", "0101", 2019, "Navneendring")])
    result = generate_changes(df, min_year=2010)

    assert result.rows == []
    assert result.conflicts == {}


def test_merge_with_self_absorbing_target():
    # 1141 + 1142 merge into 1103, which keeps its own code.
    df = masterlist_df(
        [
            ("1103", "1103", 2019, "Sammenslåing"),
            ("1141", "1103", 2019, "Sammenslåing"),
            ("1142", "1103", 2019, "Sammenslåing"),
        ]
    )
    result = generate_changes(df, min_year=2010)

    codes = {row["Code"] for row in result.rows}
    assert codes == {"1141", "1142"}  # no row for the absorbing code itself
    row_1141 = next(r for r in result.rows if r["Code"] == "1141")
    assert row_1141["Merge"] == "1103/1103;1141;1142"


def test_clean_merge_of_new_codes():
    df = masterlist_df(
        [("0104", "3002", 2019, "Sammenslåing"), ("0136", "3002", 2019, "Sammenslåing")]
    )
    result = generate_changes(df, min_year=2010)

    assert {r["Code"]: r["Merge"] for r in result.rows} == {
        "0104": "3002/0104;0136",
        "0136": "3002/0104;0136",
    }


def test_split():
    df = masterlist_df(
        [("0122", "3050", 2019, "Deling"), ("0122", "3051", 2019, "Deling")]
    )
    result = generate_changes(df, min_year=2010)

    assert result.rows == [{"Code": "0122", "Year": "2019", "Recode": "", "Split": "3050;3051", "Merge": ""}]


def test_split_where_source_survives_is_a_boundary_tweak_not_a_split():
    # The source keeps existing (appears as one of its own targets) -- just donated
    # some territory, doesn't need a change record.
    df = masterlist_df(
        [("3118", "3118", 2025, "Deling"), ("3118", "3207", 2025, "Deling")]
    )
    result = generate_changes(df, min_year=2010)

    assert result.rows == []
    assert result.conflicts == {}


def test_code_with_multiple_events_is_a_conflict_not_a_guess():
    # 0720 merges partly into 0704 and partly into 0710 in the same year --
    # can't be represented as one row, must be flagged instead of picked for.
    df = masterlist_df(
        [
            ("0720", "0704", 2016, "Sammenslåing"),
            ("0706", "0710", 2016, "Sammenslåing"),
            ("0720", "0710", 2016, "Sammenslåing"),
        ]
    )
    result = generate_changes(df, min_year=2010)

    assert "0720" not in {r["Code"] for r in result.rows}
    assert set(result.conflicts.keys()) == {"0720"}
    assert len(result.conflicts["0720"]) == 2


def test_min_year_filters_out_older_events():
    df = masterlist_df([("0101", "3001", 2005, "Kodeendring")])
    result = generate_changes(df, min_year=2010)

    assert result.rows == []
    assert result.conflicts == {}
