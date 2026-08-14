"""The full command grammar, every body unimplemented (#1, ADR 0002).

The parser tree is the reviewable spec: later PRDs fill in command bodies
without renaming anything. ``--help`` therefore documents commands that do
not work yet; each exits 1 with a message until its PRD lands.

Exit codes (ADR 0002):

- 0: the command produced its output (or its assertion held). PASS is not
  implied - a FAIL verdict is a result, and nothing is gated.
- 1: the tool could not produce a result. Usage errors land here too.
- 2: an assertion failed (``stations diff`` only: the catalogue drifted).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from sensor_qaqc.cli import checks_commands, inspect_command

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_PRODUCED = 0
EXIT_NO_RESULT = 1
EXIT_ASSERTION_FAILED = 2


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors exit 1 instead of argparse's 2.

    Exit 2 is reserved for a failed assertion, so a cron job can tell "the
    catalogue drifted" from "the invocation was wrong". argparse hardwires
    exit 2 for usage errors; unmapped, a typo in a ``stations diff`` cron
    line would read as drift (ADR 0002).
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_NO_RESULT, f"{self.prog}: error: {message}\n")


# argparse does not export its subparsers type; every parser in the tree is a
# _Parser, so usage errors anywhere funnel through _Parser.error.
_Subparsers = argparse._SubParsersAction  # noqa: SLF001


def _not_implemented(args: argparse.Namespace) -> int:
    """Body of every command until the PRD that implements it lands."""
    raise NotImplementedError(str(args.invoked_command))


def _leaf(sub: _Subparsers[_Parser], name: str, help_: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(name, help=help_, description=help_)
    parser.set_defaults(func=_not_implemented, invoked_command=f"{parser.prog}")
    return parser


def _add_stations(sub: _Subparsers[_Parser]) -> None:
    stations = sub.add_parser("stations", help="reference-station catalogue (#5)")
    group = stations.add_subparsers(dest="stations_command", required=True, metavar="<command>")

    discover = _leaf(group, "discover", "search ERDDAP servers for candidate stations")
    discover.add_argument("--lat", type=float, required=True, help="deployment latitude")
    discover.add_argument("--lon", type=float, required=True, help="deployment longitude")
    discover.add_argument("--radius-km", type=float, required=True, help="search radius")

    diff = _leaf(
        group, "diff", "re-probe and compare against the cache; read-only, exit 2 on drift"
    )
    diff.add_argument("--site", help="limit to one site's stations")

    update = _leaf(group, "update", "accept the probed state into the cache; writes")
    update.add_argument("--site", help="limit to one site's stations")

    show = _leaf(group, "show", "one station: asserted facts, probed state, provenance")
    show.add_argument("station_id", metavar="<id>", help="station id from stations.yaml")


def _add_baseline(sub: _Subparsers[_Parser]) -> None:
    baseline = sub.add_parser("baseline", help="site baselines (#9)")
    group = baseline.add_subparsers(dest="baseline_command", required=True, metavar="<command>")

    build = _leaf(group, "build", "compute a site's reusable reference statistics")
    build.add_argument("--site", required=True, help="site name from config")
    build.add_argument(
        "--from", dest="from_", required=True, metavar="FROM", help="window start (UTC date)"
    )
    build.add_argument("--to", dest="to", required=True, metavar="TO", help="window end (UTC date)")

    show = _leaf(group, "show", "a site's current baseline and its provenance")
    show.add_argument("site", metavar="<site>", help="site name from config")


def _add_inspect(sub: _Subparsers[_Parser]) -> None:
    # inspect runs on a file straight off a logger, before any
    # sensor_deployments.yaml entry exists; run requires one. Same ingest
    # function, different preconditions (#1).
    inspect = _leaf(sub, "inspect", "parse a sensor export and report what it contains (#3)")
    inspect.add_argument(
        "file",
        type=Path,
        metavar="<file>",
        help="sensor export: a workbook, a CSV, or a directory of CSV tables",
    )
    inspect.set_defaults(func=inspect_command.inspect_command)


def _add_run(sub: _Subparsers[_Parser]) -> None:
    run = _leaf(sub, "run", "the only command that computes verdicts (#4)")
    run.add_argument(
        "deployment_id", metavar="<deployment-id>", help="{serial}-{deployment_number}"
    )
    run.add_argument(
        "--check",
        action="append",
        metavar="<id>",
        help="run only this check_id; repeatable. The manifest records the selector.",
    )


def _add_report(sub: _Subparsers[_Parser]) -> None:
    report = sub.add_parser("report", help="render finished run folders (#10)")
    group = report.add_subparsers(dest="report_command", required=True, metavar="<command>")

    render = _leaf(group, "render", "render a finished run folder; reads nothing else")
    render.add_argument("run_folder", type=Path, metavar="<run-folder>", help="runs/<run_id>/")
    render.add_argument("--pdf", action="store_true", help="also export PDF")


def _add_checks(sub: _Subparsers[_Parser]) -> None:
    checks = sub.add_parser("checks", help="the check registry (#2)")
    group = checks.add_subparsers(dest="checks_command", required=True, metavar="<command>")

    list_ = _leaf(group, "list", "registered checks with domains, channels and requirements")
    list_.set_defaults(func=checks_commands.checks_list_command)

    show = _leaf(group, "show", "one check: thresholds with provenance, false-alarm bound")
    show.add_argument("check_id", metavar="<id>", help="flat lowercase snake check_id")
    show.set_defaults(func=checks_commands.checks_show_command)

    docs = _leaf(group, "docs", "generate per-check documentation pages (#11)")
    docs.add_argument("--out", type=Path, required=True, metavar="<dir>", help="output directory")


def build_parser() -> argparse.ArgumentParser:
    """Build the full sensor-qaqc parser tree."""
    parser = _Parser(
        prog="sensor-qaqc",
        description=(
            "Verifies in-water temperature records from low-cost loggers "
            "against reference stations."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    _add_stations(sub)
    _add_baseline(sub)
    _add_inspect(sub)
    _add_run(sub)
    _add_report(sub)
    _add_checks(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: parse, dispatch, translate failure into exit codes."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except NotImplementedError as exc:
        sys.stderr.write(f"sensor-qaqc: not implemented yet: {exc}\n")
        return EXIT_NO_RESULT


if __name__ == "__main__":
    sys.exit(main())
