import pandas as pd
import pytest

from munpatch import indicators
from munpatch.cli import build_parser, main
from munpatch.extrapolate import MissingChangeError, MissingPopulationError, read_output
from munpatch.indicators import IndicatorConfig


def make_config(tmp_path, name="test"):
    return IndicatorConfig(
        table_id="00000",
        contents_code="Test",
        raw_path=str(tmp_path / f"{name}_raw.csv"),
        processed_path=str(tmp_path / f"{name}_processed.csv"),
    )


def use_test_indicator(monkeypatch, config):
    """Point the "test" indicator (and only it) at `config`, so CLI commands
    that iterate indicators.resolve() work against tmp_path files instead of
    the real data/ directory."""
    monkeypatch.setattr(indicators, "INDICATORS", {"test": config})


def write_changes(tmp_path, content):
    path = tmp_path / "changes.csv"
    path.write_text(content)
    return str(path)


def write_tsv(path, rows):
    """rows: list of (Year, Code, Value)."""
    pd.DataFrame(rows, columns=["Year", "Code", "Value"]).to_csv(path, sep="\t", index=False)


def run(monkeypatch, argv):
    """Build a fresh parser (so --indicator choices reflect the currently
    patched indicator registry) and dispatch it, like main() does."""
    monkeypatch.setattr("sys.argv", ["munpatch", *argv])
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return args


def test_indicator_choices_reflect_the_registry(monkeypatch, tmp_path):
    use_test_indicator(monkeypatch, make_config(tmp_path))
    parser = build_parser()

    args = parser.parse_args(["fetch", "--indicator", "test"])
    assert args.indicator == "test"

    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--indicator", "not-a-real-indicator"])


def test_indicator_flag_is_required(monkeypatch, tmp_path):
    use_test_indicator(monkeypatch, make_config(tmp_path))
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["fetch"])


def test_cmd_fetch_writes_raw_file(monkeypatch, tmp_path):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)

    fake_df = pd.DataFrame({"Code": ["0301"], "Year": [2020], "Value": [100.0]})
    monkeypatch.setattr("munpatch.cli.fetch_ssb", lambda *args, **kwargs: fake_df)

    run(monkeypatch, ["fetch", "--indicator", "test"])

    written = pd.read_csv(config.raw_path, sep="\t", dtype={"Code": "string"})
    assert written.to_dict("records") == [{"Code": "0301", "Year": 2020, "Value": 100.0}]


def test_cmd_extrapolate_fills_gaps_across_a_recode(monkeypatch, tmp_path, capsys):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    write_tsv(
        config.raw_path,
        [(2018, "0101", 100.0), (2019, "0101", 110.0), (2020, "3001", 120.0), (2021, "3001", 130.0)],
    )
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n0101,2019,3001,,\n")

    run(monkeypatch, ["extrapolate", "--indicator", "test", "--changes", changes_path])

    result = read_output(config.processed_path)
    assert result[("0101", 2020)] == 120.0  # forward: old code copies the new code
    assert result[("3001", 2019)] == 110.0  # backward: new code copies the old code
    assert "(count)" in capsys.readouterr().out


def test_cmd_extrapolate_reports_missing_change_via_main(monkeypatch, tmp_path, capsys):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    write_tsv(config.raw_path, [(2019, "0101", 100.0), (2020, "3001", 120.0)])
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n")  # 0101 unexplained

    monkeypatch.setattr(
        "sys.argv", ["munpatch", "extrapolate", "--indicator", "test", "--changes", changes_path]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert "0101" in capsys.readouterr().err


def test_cmd_extrapolate_uses_population_weight_for_a_ratio_indicator(monkeypatch, tmp_path, capsys):
    rate_config = make_config(tmp_path, name="rate")
    pop_config = make_config(tmp_path, name="pop")
    rate_config.weight_by = "pop"
    monkeypatch.setattr(indicators, "INDICATORS", {"rate": rate_config, "pop": pop_config})

    # As if `munpatch extrapolate --indicator pop` already ran.
    write_tsv(
        pop_config.processed_path,
        [
            (2019, "0104", 100.0), (2019, "0136", 50.0), (2019, "3002", 150.0),
            (2020, "0104", 100.0), (2020, "0136", 50.0), (2020, "3002", 150.0),
        ],
    )
    write_tsv(rate_config.raw_path, [(2019, "0104", 0.40), (2019, "0136", 0.20), (2020, "3002", 0.40)])
    changes_path = write_changes(
        tmp_path, "Code,Year,Recode,Split,Merge\n0104,2019,,,3002/0104;0136\n0136,2019,,,3002/0104;0136\n"
    )

    run(monkeypatch, ["extrapolate", "--indicator", "rate", "--changes", changes_path])

    result = read_output(rate_config.processed_path)
    assert result[("3002", 2019)] == pytest.approx(50.0 / 150.0)  # not 0.40 + 0.20
    assert "rate, weighted by pop" in capsys.readouterr().out


def test_cmd_extrapolate_requires_the_weight_indicator_extrapolated_first(monkeypatch, tmp_path):
    rate_config = make_config(tmp_path, name="rate")
    pop_config = make_config(tmp_path, name="pop")
    rate_config.weight_by = "pop"
    monkeypatch.setattr(indicators, "INDICATORS", {"rate": rate_config, "pop": pop_config})
    write_tsv(rate_config.raw_path, [(2019, "0301", 0.10)])
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n")

    with pytest.raises(MissingPopulationError, match="pop"):
        run(monkeypatch, ["extrapolate", "--indicator", "rate", "--changes", changes_path])


def test_cmd_extrapolate_reports_missing_population_via_main(monkeypatch, tmp_path, capsys):
    rate_config = make_config(tmp_path, name="rate")
    pop_config = make_config(tmp_path, name="pop")
    rate_config.weight_by = "pop"
    monkeypatch.setattr(indicators, "INDICATORS", {"rate": rate_config, "pop": pop_config})
    write_tsv(rate_config.raw_path, [(2019, "0301", 0.10)])
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n")

    monkeypatch.setattr(
        "sys.argv", ["munpatch", "extrapolate", "--indicator", "rate", "--changes", changes_path]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert "pop" in capsys.readouterr().err


def test_cmd_check_changes_passes_when_covered(monkeypatch, tmp_path, capsys):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    write_tsv(config.raw_path, [(2019, "0101", 100.0), (2020, "3001", 120.0)])
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n0101,2019,3001,,\n")

    run(monkeypatch, ["check-changes", "--input", config.raw_path, "--changes", changes_path])

    assert "OK" in capsys.readouterr().out


def test_cmd_check_changes_raises_for_uncovered_code(monkeypatch, tmp_path):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    write_tsv(config.raw_path, [(2019, "0101", 100.0), (2020, "3001", 120.0)])
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n")

    with pytest.raises(MissingChangeError, match="0101"):
        run(monkeypatch, ["check-changes", "--input", config.raw_path, "--changes", changes_path])


def test_cmd_structure_filters_to_the_codes_valid_that_year(monkeypatch, tmp_path):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    # 0101 recoded to 3001 after 2019; the (already-extrapolated) processed
    # file has both codes' full series across all four years.
    write_tsv(
        config.processed_path,
        [
            (2018, "0101", 100.0), (2019, "0101", 110.0), (2020, "0101", 120.0), (2021, "0101", 130.0),
            (2018, "3001", 100.0), (2019, "3001", 110.0), (2020, "3001", 120.0), (2021, "3001", 130.0),
        ],
    )
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n0101,2019,3001,,\n")

    run(monkeypatch, ["structure", "--indicator", "test", "--changes", changes_path, "--year", "2019"])

    output_path = tmp_path / "test_processed_structure_2019.csv"
    df = pd.read_csv(output_path, sep="\t", dtype={"Code": "string"})
    assert list(df.columns) == ["Code", "COD_MUN", "2018", "2019", "2020", "2021"]
    assert df.to_dict("records") == [
        {"Code": "0101", "COD_MUN": "NO0101", "2018": 100.0, "2019": 110.0, "2020": 120.0, "2021": 130.0}
    ]


def test_cmd_structure_defaults_to_the_latest_year_in_the_data(monkeypatch, tmp_path):
    config = make_config(tmp_path)
    use_test_indicator(monkeypatch, config)
    write_tsv(
        config.processed_path,
        [
            (2018, "0101", 100.0), (2019, "0101", 110.0), (2020, "0101", 120.0), (2021, "0101", 130.0),
            (2018, "3001", 100.0), (2019, "3001", 110.0), (2020, "3001", 120.0), (2021, "3001", 130.0),
        ],
    )
    changes_path = write_changes(tmp_path, "Code,Year,Recode,Split,Merge\n0101,2019,3001,,\n")

    run(monkeypatch, ["structure", "--indicator", "test", "--changes", changes_path])

    output_path = tmp_path / "test_processed_structure_2021.csv"
    df = pd.read_csv(output_path, sep="\t", dtype={"Code": "string"})
    assert df["Code"].tolist() == ["3001"]  # 3001, not 0101, is valid in 2021


def test_cmd_generate_changes_writes_csv_and_reports_conflicts(monkeypatch, tmp_path, capsys):
    masterlist_path = tmp_path / "masterlist.xlsx"
    pd.DataFrame(
        [
            ("0101", "3001", 2019, "Kodeendring"),
            # 0720 splits into two competing merge targets in the same year -- a conflict.
            ("0720", "0704", 2016, "Sammenslåing"),
            ("0706", "0710", 2016, "Sammenslåing"),
            ("0720", "0710", 2016, "Sammenslåing"),
        ],
        columns=["kilde_kode", "maal_kode", "kilde_gyldig_til", "TypeOfChange"],
    ).to_excel(masterlist_path, sheet_name="MASTERLISTE", index=False)
    output_path = tmp_path / "generated_changes.csv"

    monkeypatch.setattr(
        "sys.argv",
        [
            "munpatch", "generate-changes",
            "--masterlist", str(masterlist_path),
            "--min-year", "2010",
            "--output", str(output_path),
        ],
    )
    main()

    written = pd.read_csv(output_path, dtype={"Code": "string"})
    assert "0101" in written["Code"].tolist()
    assert "0720" not in written["Code"].tolist()  # left out as a conflict, not guessed at

    out = capsys.readouterr().out
    assert "1 code(s) have more than one qualifying change" in out
    assert "0720:" in out
