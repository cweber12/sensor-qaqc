"""Run every local gate and print a row per gate (CLAUDE.md: Verification).

The gate set lives in this table, not in prose - prose cannot be run, so
nothing notices when it drifts. Add a gate by adding a row.

Every row runs even when an earlier one fails, so a failure cannot hide
behind another - the same property ci.yml gets by fanning the rows out as
separate jobs. If CI and a local run of this script ever disagree, that
divergence is the first bug to fix.

Usage: uv run python scripts/gate.py
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Gate:
    name: str
    argv: tuple[str, ...]
    # A must_fail gate is red when it *passes*: used to prove a regression
    # test fails before its fix lands.
    must_fail: bool = False


GATES = (
    # pre-commit covers format and lint (ruff-check, ruff-format, codespell,
    # pyproject-fmt, zizmor, file hygiene) - the same set CI's lint job runs.
    Gate("lint", (sys.executable, "-m", "pre_commit", "run", "--all-files")),
    Gate("typecheck", (sys.executable, "-m", "mypy")),
    Gate("test", (sys.executable, "-m", "pytest")),
    # uv is in the dev group so this needs nothing on PATH beyond `uv sync`.
    # CI's build job additionally twine-checks and installs the wheel.
    Gate("build", (sys.executable, "-m", "uv", "build")),
)


def _run(gate: Gate) -> tuple[bool, str]:
    result = subprocess.run(gate.argv, capture_output=True, text=True, check=False)
    passed = (result.returncode == 0) != gate.must_fail
    return passed, result.stdout + result.stderr


def main() -> int:
    width = max(len(gate.name) for gate in GATES)
    failures: list[tuple[Gate, str]] = []
    for gate in GATES:
        passed, output = _run(gate)
        if passed:
            status = "ok"
        elif gate.must_fail:
            status = "FAIL (must_fail gate passed)"
        else:
            status = "FAIL"
        print(f"{gate.name:<{width}}  {status}")
        if not passed:
            failures.append((gate, output))
    for gate, output in failures:
        print(f"\n--- {gate.name} ---")
        print(output, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
