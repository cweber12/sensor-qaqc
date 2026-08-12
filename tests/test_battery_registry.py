"""The battery is inherited: every registered check, no opt-out (#2).

Parametrised over ``build_registry()``, so a check registered there is
battery-covered with no further wiring. Empty today - the first real
checks arrive with #6-#8 - so these parametrise to nothing and skip.

Thresholds: each check's resolved thresholds arrive with the catalog the
domain PRDs build (#6/#7); until then the empty mapping documents the
seam. When the catalog lands, it plugs in here and nothing else moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sensor_qaqc.cli.registry import build_registry
from sensor_qaqc.core.battery import run_full_battery, run_smoke_battery

if TYPE_CHECKING:
    from sensor_qaqc.core.checks import Check
    from sensor_qaqc.core.thresholds import ThresholdLike

REGISTRY = build_registry()
CHECKS = list(REGISTRY)
THRESHOLDS: dict[str, ThresholdLike] = {}


@pytest.mark.parametrize("check", CHECKS, ids=[check.check_id for check in CHECKS])
def test_smoke_battery(check: Check) -> None:
    run_smoke_battery(REGISTRY, check, THRESHOLDS)


@pytest.mark.battery
@pytest.mark.parametrize("check", CHECKS, ids=[check.check_id for check in CHECKS])
def test_full_battery(check: Check) -> None:
    # The returned measurement is the declared bound's provenance
    # (ADR 0006); assert_full_far has already held it to the declaration.
    run_full_battery(REGISTRY, check, THRESHOLDS)
