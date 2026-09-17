from __future__ import annotations

import argparse
import sys
from pathlib import Path

from munpatch import indicators
from munpatch.changes import parse_changes, purple_change_transform
from munpatch.extrapolate import (
    MissingChangeError,
    MissingPopulationError,
    extrapolate,
    extrapolate_ratio,
    filter_to_year,
    parse_input,
    read_output,
    validate_codes,
    write_output,
    write_structure_output,
)
from munpatch.masterlist import generate_changes, load_masterlist, write_changes_csv
from munpatch.ssb_fetch import fetch_ssb


def cmd_fetch(args: argparse.Namespace) -> None:
    for name, config in indicators.resolve(args.indicator).items():
        df = fetch_ssb(config.table_id, config.query(), min_year=config.min_year)
        df.to_csv(config.raw_path, sep="\t", index=False)
        print(f"{name}: wrote {len(df)} rows to {config.raw_path}")


def cmd_extrapolate(args: argparse.Namespace) -> None:
    changes_yellow = parse_changes(args.changes)
    changes_purple = purple_change_transform(list(changes_yellow.values()))

    for name, config in indicators.resolve(args.indicator).items():
        input_records = parse_input(config.raw_path)
        validate_codes(input_records, changes_purple)

        if config.weight_by is None:
            result = extrapolate(input_records, changes_purple)
            mode = "count"
        else:
            population_config = indicators.INDICATORS[config.weight_by]
            if not Path(population_config.processed_path).exists():
                raise MissingPopulationError(
                    f"{name} is weighted by '{config.weight_by}', which hasn't been "
                    f"extrapolated yet -- run `munpatch extrapolate --indicator "
                    f"{config.weight_by}` first (or --indicator all)."
                )
            population = read_output(population_config.processed_path)
            result = extrapolate_ratio(input_records, changes_purple, population)
            mode = f"rate, weighted by {config.weight_by}"

        write_output(result, config.processed_path)
        print(f"{name}: wrote {len(result)} rows to {config.processed_path} ({mode})")


def cmd_pipeline(args: argparse.Namespace) -> None:
    cmd_fetch(args)
    cmd_extrapolate(args)


def cmd_structure(args: argparse.Namespace) -> None:
    changes_yellow = parse_changes(args.changes)
    changes_purple = purple_change_transform(list(changes_yellow.values()))

    for name, config in indicators.resolve(args.indicator).items():
        result = read_output(config.processed_path)
        year = args.year if args.year is not None else max(y for _, y in result)
        filtered = filter_to_year(result, changes_purple, year)

        processed_path = Path(config.processed_path)
        output_path = processed_path.with_name(f"{processed_path.stem}_structure_{year}.csv")
        write_structure_output(filtered, str(output_path))

        codes = {code for code, _ in filtered}
        print(f"{name}: wrote {len(codes)} codes to {output_path}")


def cmd_check_changes(args: argparse.Namespace) -> None:
    changes_yellow = parse_changes(args.changes)
    changes_purple = purple_change_transform(list(changes_yellow.values()))
    input_records = parse_input(args.input)
    validate_codes(input_records, changes_purple)
    print("OK: every code that disappears from the input has a matching entry in changes.csv")


def cmd_generate_changes(args: argparse.Namespace) -> None:
    masterlist = load_masterlist(args.masterlist)
    result = generate_changes(masterlist, min_year=args.min_year)
    write_changes_csv(result.rows, args.output)
    print(f"Wrote {len(result.rows)} rows to {args.output}")

    if result.conflicts:
        print(
            f"\n{len(result.conflicts)} code(s) have more than one qualifying change "
            "and were left out -- add these by hand after checking the masterlist:"
        )
        for code, events in sorted(result.conflicts.items()):
            print(f"  {code}:")
            for year, kind, payload in events:
                print(f"    {year} {kind} {payload}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="munpatch",
        description="Extrapolate Norwegian municipal statistics across administrative boundary changes",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    indicator_choices = ["all", *sorted(indicators.INDICATORS)]

    p_fetch = subparsers.add_parser("fetch", help="Fetch raw data from the SSB API")
    p_fetch.add_argument("--indicator", required=True, choices=indicator_choices)
    p_fetch.set_defaults(func=cmd_fetch)

    p_extrapolate = subparsers.add_parser(
        "extrapolate", help="Extrapolate fetched data across boundary changes"
    )
    p_extrapolate.add_argument("--indicator", required=True, choices=indicator_choices)
    p_extrapolate.add_argument("--changes", default="data/changes.csv")
    p_extrapolate.set_defaults(func=cmd_extrapolate)

    p_pipeline = subparsers.add_parser("pipeline", help="Fetch, then extrapolate")
    p_pipeline.add_argument("--indicator", required=True, choices=indicator_choices)
    p_pipeline.add_argument("--changes", default="data/changes.csv")
    p_pipeline.set_defaults(func=cmd_pipeline)

    p_structure = subparsers.add_parser(
        "structure",
        help="Filter already-extrapolated data down to one year's municipal structure",
    )
    p_structure.add_argument("--indicator", required=True, choices=indicator_choices)
    p_structure.add_argument("--changes", default="data/changes.csv")
    p_structure.add_argument(
        "--year",
        type=int,
        default=None,
        help="Municipal structure to filter to (default: latest year in the processed data)",
    )
    p_structure.set_defaults(func=cmd_structure)

    p_check = subparsers.add_parser(
        "check-changes",
        help="Verify every code missing from an input file is explained in changes.csv",
    )
    p_check.add_argument("--input", required=True)
    p_check.add_argument("--changes", default="data/changes.csv")
    p_check.set_defaults(func=cmd_check_changes)

    p_generate = subparsers.add_parser(
        "generate-changes",
        help="Generate a changes.csv from the KOM Masterliste (flags cases needing manual review)",
    )
    p_generate.add_argument("--masterlist", required=True, help="Path to a KOM_Masterliste_*.xlsx file")
    p_generate.add_argument(
        "--min-year",
        type=int,
        default=2010,
        help="Only include masterlist events from this year onward (default: 2010)",
    )
    p_generate.add_argument("--output", default="data/changes.csv")
    p_generate.set_defaults(func=cmd_generate_changes)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (MissingChangeError, MissingPopulationError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
