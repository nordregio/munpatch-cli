import pytest

from munpatch.changes import (
    CodeChangePurple,
    MergeFrom,
    MergeTo,
    RecodeFrom,
    RecodeTo,
    SplitFrom,
    SplitTo,
)
from munpatch.extrapolate import (
    InputRecord,
    MissingChangeError,
    MissingPopulationError,
    cod_mun,
    extrapolate,
    extrapolate_ratio,
    filter_to_year,
    validate_codes,
    write_structure_output,
)


def records(*triples):
    return {(code, year): InputRecord(code, year, value) for code, year, value in triples}


def test_recode_extrapolates_both_directions():
    # 0101 was renamed to 3001 after 2019: old code only has data up to 2019,
    # new code only has data from 2020.
    input_records = records(
        ("0101", 2018, 100.0),
        ("0101", 2019, 110.0),
        ("3001", 2020, 120.0),
        ("3001", 2021, 130.0),
    )
    changes = {
        "0101": CodeChangePurple("0101", year_to=2019, reason_to=RecodeTo("3001")),
        "3001": CodeChangePurple("3001", year_from=2020, reason_from=RecodeFrom("0101")),
    }

    result = extrapolate(input_records, changes)

    assert result[("0101", 2020)] == 120.0  # forward: old code copies the new code
    assert result[("0101", 2021)] == 130.0
    assert result[("3001", 2018)] == 100.0  # backward: new code copies the old code
    assert result[("3001", 2019)] == 110.0


def test_merge_extrapolates_both_directions():
    # 0104 + 0136 merged into 3002 after 2019.
    merge_to = MergeTo(target="3002", merged_codes=["0104", "0136"])
    input_records = records(
        ("0104", 2019, 40.0),
        ("0136", 2019, 10.0),
        ("3002", 2020, 60.0),
    )
    changes = {
        "0104": CodeChangePurple("0104", year_to=2019, reason_to=merge_to),
        "0136": CodeChangePurple("0136", year_to=2019, reason_to=merge_to),
        "3002": CodeChangePurple(
            "3002", year_from=2020, reason_from=MergeFrom(["0104", "0136"])
        ),
    }

    result = extrapolate(input_records, changes)

    # backward: merged code's past value is the sum of its components
    assert result[("3002", 2019)] == 50.0
    # forward: each component keeps its 2019 share of the merged total
    assert result[("0104", 2020)] == pytest.approx(48.0)  # 40/50 * 60
    assert result[("0136", 2020)] == pytest.approx(12.0)  # 10/50 * 60


def test_extrapolate_ratio_converts_through_absolute_counts_not_by_summing_rates():
    # Same merge as test_merge_extrapolates_both_directions, but as a rate:
    # 0104 (rate 0.40, pop 100 -> count 40) + 0136 (rate 0.20, pop 50 -> count
    # 10) merged into 3002 (rate 0.40, pop 150 -> count 60) after 2019.
    # Naively summing the rates (0.40 + 0.20) would be wrong; going through
    # population-weighted counts gives the same counts as the count-only
    # test above, then converts back to a rate.
    merge_to = MergeTo(target="3002", merged_codes=["0104", "0136"])
    input_records = records(
        ("0104", 2019, 0.40),
        ("0136", 2019, 0.20),
        ("3002", 2020, 0.40),
    )
    changes = {
        "0104": CodeChangePurple("0104", year_to=2019, reason_to=merge_to),
        "0136": CodeChangePurple("0136", year_to=2019, reason_to=merge_to),
        "3002": CodeChangePurple(
            "3002", year_from=2020, reason_from=MergeFrom(["0104", "0136"])
        ),
    }
    population = {
        ("0104", 2019): 100.0, ("0104", 2020): 100.0,
        ("0136", 2019): 50.0, ("0136", 2020): 50.0,
        ("3002", 2019): 150.0, ("3002", 2020): 150.0,
    }

    result = extrapolate_ratio(input_records, changes, population)

    assert result[("3002", 2019)] == pytest.approx(50.0 / 150.0)  # not 0.40 + 0.20
    assert result[("0104", 2020)] == pytest.approx(0.48)  # 48/100, matching the 40/50*60 count
    assert result[("0136", 2020)] == pytest.approx(0.24)  # 12/50, matching the 10/50*60 count


def test_extrapolate_ratio_raises_when_raw_input_has_no_population():
    input_records = records(("0101", 2019, 0.10))

    with pytest.raises(MissingPopulationError, match="0101/2019"):
        extrapolate_ratio(input_records, changes={}, population={})


def test_extrapolate_ratio_raises_when_an_extrapolated_year_has_no_population():
    # 0101 recoded to 3001 after 2019. Population covers the years the raw
    # rate data actually has, but not the years extrapolate() fills in on
    # the *other* side of the recode for each code -- that gap must be
    # caught explicitly, not produce a silent division by a KeyError.
    input_records = records(
        ("0101", 2018, 0.10), ("0101", 2019, 0.11), ("3001", 2020, 0.12), ("3001", 2021, 0.13)
    )
    changes = {
        "0101": CodeChangePurple("0101", year_to=2019, reason_to=RecodeTo("3001")),
        "3001": CodeChangePurple("3001", year_from=2020, reason_from=RecodeFrom("0101")),
    }
    population = {
        ("0101", 2018): 100.0, ("0101", 2019): 100.0,
        ("3001", 2020): 100.0, ("3001", 2021): 100.0,
    }

    with pytest.raises(MissingPopulationError, match="0101/2020"):
        extrapolate_ratio(input_records, changes, population)


def test_split_extrapolates_both_directions():
    # 0122 split into 3050 + 3051 after 2019.
    split_to = SplitTo(["3050", "3051"])
    input_records = records(
        ("0122", 2019, 50.0),
        ("3050", 2020, 36.0),
        ("3051", 2020, 24.0),
    )
    changes = {
        "0122": CodeChangePurple("0122", year_to=2019, reason_to=split_to),
        "3050": CodeChangePurple(
            "3050", year_from=2020, reason_from=SplitFrom("0122", ["3050", "3051"])
        ),
        "3051": CodeChangePurple(
            "3051", year_from=2020, reason_from=SplitFrom("0122", ["3050", "3051"])
        ),
    }

    result = extrapolate(input_records, changes)

    # forward: the parent's future value is the sum of its children
    assert result[("0122", 2020)] == 60.0
    # backward: each child keeps its 2020 share of the parent's past value
    assert result[("3050", 2019)] == pytest.approx(30.0)  # 36/60 * 50
    assert result[("3051", 2019)] == pytest.approx(20.0)  # 24/60 * 50


def test_validate_codes_raises_for_missing_change_entry():
    input_records = records(("0101", 2018, 100.0), ("0101", 2019, 110.0), ("3001", 2020, 120.0))

    with pytest.raises(MissingChangeError, match="0101"):
        validate_codes(input_records, changes={})


def test_validate_codes_passes_when_change_entry_exists():
    input_records = records(("0101", 2019, 110.0), ("3001", 2020, 120.0))
    changes = {"0101": CodeChangePurple("0101", year_to=2019, reason_to=RecodeTo("3001"))}

    validate_codes(input_records, changes)  # should not raise


def test_filter_to_year_keeps_only_codes_valid_that_year():
    # 0101 recoded to 3001 after 2019. The extrapolated matrix has both
    # codes' full time series; filtering to a given year picks one or the
    # other, never both.
    changes = {
        "0101": CodeChangePurple("0101", year_to=2019, reason_to=RecodeTo("3001")),
        "3001": CodeChangePurple("3001", year_from=2020, reason_from=RecodeFrom("0101")),
    }
    result = {
        ("0101", 2018): 100.0,
        ("0101", 2019): 110.0,
        ("0101", 2020): 120.0,
        ("3001", 2018): 100.0,
        ("3001", 2019): 110.0,
        ("3001", 2020): 120.0,
    }

    filtered_2019 = filter_to_year(result, changes, 2019)
    assert set(filtered_2019) == {("0101", 2018), ("0101", 2019), ("0101", 2020)}

    filtered_2020 = filter_to_year(result, changes, 2020)
    assert set(filtered_2020) == {("3001", 2018), ("3001", 2019), ("3001", 2020)}


def test_cod_mun_pads_and_prefixes_the_code():
    # Matches the join key used by the Nordregio Nordic municipality
    # shapefiles' COD_MUN field, e.g. Oslo (301) -> "NO0301".
    assert cod_mun("301") == "NO0301"
    assert cod_mun("0301") == "NO0301"
    assert cod_mun("3001") == "NO3001"


def test_write_structure_output_is_wide_with_cod_mun_and_year_columns(tmp_path):
    output_path = tmp_path / "structure.csv"
    write_structure_output(
        {("0301", 2019): 100.0, ("0301", 2020): 110.0, ("1101", 2019): 5.0, ("1101", 2020): 6.0},
        str(output_path),
    )

    lines = output_path.read_text().splitlines()
    assert lines[0].split("\t") == ["Code", "COD_MUN", "2019", "2020"]
    assert lines[1].split("\t") == ["0301", "NO0301", "100.0", "110.0"]
    assert lines[2].split("\t") == ["1101", "NO1101", "5.0", "6.0"]
