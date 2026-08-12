"""The parser tree must match the grammar declared in ADR 0002 (#1).

The table below *is* the declared table, restated as data; the test walks
the real parser structurally and asserts equality in both directions, so a
command added, removed or renamed without updating the ADR's grammar goes
red. Structural comparison rather than help-text matching: --help is
generated from the same tree, and string matching would break on argparse
formatting changes while missing nothing the walk misses.
"""

from __future__ import annotations

import argparse

from sensor_qaqc.cli.__main__ import build_parser

# {group: {subcommand} | None for leaf commands at the top level}
GROUPS: dict[str, set[str] | None] = {
    "stations": {"discover", "diff", "update", "show"},
    "baseline": {"build", "show"},
    "inspect": None,
    "run": None,
    "report": {"render"},
    "checks": {"list", "show", "docs"},
}

# {command path: (required options, optional options, positionals)}
LEAF_SIGNATURES: dict[tuple[str, ...], tuple[set[str], set[str], tuple[str, ...]]] = {
    ("stations", "discover"): ({"--lat", "--lon", "--radius-km"}, set(), ()),
    ("stations", "diff"): (set(), {"--site"}, ()),
    ("stations", "update"): (set(), {"--site"}, ()),
    ("stations", "show"): (set(), set(), ("station_id",)),
    ("baseline", "build"): ({"--site", "--from", "--to"}, set(), ()),
    ("baseline", "show"): (set(), set(), ("site",)),
    ("inspect",): (set(), set(), ("file",)),
    ("run",): (set(), {"--check"}, ("deployment_id",)),
    ("report", "render"): (set(), {"--pdf"}, ("run_folder",)),
    ("checks", "list"): (set(), set(), ()),
    ("checks", "show"): (set(), set(), ("check_id",)),
    ("checks", "docs"): ({"--out"}, set(), ()),
}


def _subparsers(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser] | None:
    # argparse offers no public accessor for a parser's subcommands.
    actions = [
        a
        for a in parser._actions  # noqa: SLF001
        if isinstance(a, argparse._SubParsersAction)  # noqa: SLF001
    ]
    return actions[0] if actions else None


def _signature(parser: argparse.ArgumentParser) -> tuple[set[str], set[str], tuple[str, ...]]:
    required: set[str] = set()
    optional: set[str] = set()
    positionals: list[str] = []
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._HelpAction | argparse._SubParsersAction):  # noqa: SLF001
            continue
        if action.option_strings:
            (required if action.required else optional).add(action.option_strings[0])
        else:
            positionals.append(action.dest)
    return required, optional, tuple(positionals)


def test_top_level_groups_match_declared_table() -> None:
    root = _subparsers(build_parser())
    assert root is not None
    assert set(root.choices) == set(GROUPS)


def test_group_subcommands_match_declared_table() -> None:
    root = _subparsers(build_parser())
    assert root is not None
    actual = {
        name: set(sub.choices) if (sub := _subparsers(parser)) else None
        for name, parser in root.choices.items()
    }
    assert actual == GROUPS


def test_leaf_signatures_match_declared_table() -> None:
    root = _subparsers(build_parser())
    assert root is not None
    actual: dict[tuple[str, ...], tuple[set[str], set[str], tuple[str, ...]]] = {}
    for name, parser in root.choices.items():
        sub = _subparsers(parser)
        if sub is None:
            actual[(name,)] = _signature(parser)
        else:
            for subname, subparser in sub.choices.items():
                actual[(name, subname)] = _signature(subparser)
    assert actual == LEAF_SIGNATURES
