from munpatch.changes import (
    CodeChangePurple,
    MergeFrom,
    MergeTo,
    RecodeFrom,
    RecodeTo,
    SplitFrom,
    SplitTo,
    is_valid_in_year,
    parse_changes,
    purple_change_transform,
)


def write_changes(tmp_path, content):
    path = tmp_path / "changes.csv"
    path.write_text(content)
    return str(path)


def test_parse_changes_reads_recode_split_merge(tmp_path):
    csv_path = write_changes(
        tmp_path,
        "Code,Year,Recode,Split,Merge\n"
        "0101,2019,3001,,\n"
        "0104,2019,,,3002/0104;0136\n"
        "0122,2019,,3050;3051,\n",
    )
    parsed = parse_changes(csv_path)

    assert parsed["0101"].recode.new_code == "3001"
    assert parsed["0104"].merge.target == "3002"
    assert parsed["0104"].merge.merged_codes == ["0104", "0136"]
    assert parsed["0122"].split.target_codes == ["3050", "3051"]


def test_purple_transform_recode_is_bidirectional(tmp_path):
    csv_path = write_changes(
        tmp_path, "Code,Year,Recode,Split,Merge\n0101,2019,3001,,\n"
    )
    purple = purple_change_transform(list(parse_changes(csv_path).values()))

    assert purple["0101"].year_to == 2019
    assert purple["0101"].reason_to == RecodeTo("3001")
    assert purple["3001"].year_from == 2020
    assert purple["3001"].reason_from == RecodeFrom("0101")


def test_purple_transform_merge_is_bidirectional(tmp_path):
    csv_path = write_changes(
        tmp_path, "Code,Year,Recode,Split,Merge\n0104,2019,,,3002/0104;0136\n"
    )
    purple = purple_change_transform(list(parse_changes(csv_path).values()))

    assert purple["0104"].reason_to == MergeTo("3002", ["0104", "0136"])
    assert purple["3002"].year_from == 2020
    assert purple["3002"].reason_from == MergeFrom(["0104", "0136"])


def test_purple_transform_self_absorbing_merge_target_gets_no_backward_rule(tmp_path):
    # 1141/1142 merge into 1103, which keeps its own code (Stavanger absorbing
    # Finnøy + Rennesøy). 1103 is continuous, not new, so it must not end up
    # with a year_from/reason_from that references itself as a merge source
    # -- that would recurse forever the first time 1103's own data has a gap.
    csv_path = write_changes(
        tmp_path,
        "Code,Year,Recode,Split,Merge\n"
        "1141,2019,,,1103/1103;1141;1142\n"
        "1142,2019,,,1103/1103;1141;1142\n",
    )
    purple = purple_change_transform(list(parse_changes(csv_path).values()))

    assert "1103" not in purple
    assert purple["1141"].reason_to == MergeTo("1103", ["1103", "1141", "1142"])


def test_purple_transform_split_is_bidirectional(tmp_path):
    csv_path = write_changes(
        tmp_path, "Code,Year,Recode,Split,Merge\n0122,2019,,3050;3051,\n"
    )
    purple = purple_change_transform(list(parse_changes(csv_path).values()))

    assert purple["0122"].reason_to == SplitTo(["3050", "3051"])
    assert purple["3050"].year_from == 2020
    assert purple["3050"].reason_from == SplitFrom("0122", ["3050", "3051"])
    assert purple["3051"].reason_from == SplitFrom("0122", ["3050", "3051"])


def test_is_valid_in_year_code_with_no_changes_is_always_valid():
    assert is_valid_in_year("0301", changes={}, year=2010)
    assert is_valid_in_year("0301", changes={}, year=2030)


def test_is_valid_in_year_respects_year_to():
    # 0101 recoded to 3001 after 2019: 0101 valid through 2019, not after.
    changes = {"0101": CodeChangePurple("0101", year_to=2019, reason_to=RecodeTo("3001"))}

    assert is_valid_in_year("0101", changes, 2019)
    assert not is_valid_in_year("0101", changes, 2020)


def test_is_valid_in_year_respects_year_from():
    # 3001 only came into existence from 2020 onward.
    changes = {"3001": CodeChangePurple("3001", year_from=2020, reason_from=RecodeFrom("0101"))}

    assert not is_valid_in_year("3001", changes, 2019)
    assert is_valid_in_year("3001", changes, 2020)
