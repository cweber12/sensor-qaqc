"""Assemble the full registry - explicitly, with no import side effects (#2).

Registration by decorator-at-import couples the registry's contents to
which modules happen to have been imported, which is how a check silently
drops out of ``checks list``, the battery and the monotonicity test all
at once. Instead there is exactly one assembly point, and it lives in
``cli`` because that is the only layer allowed to import everything -
the domain packages under ``marine/`` register here as #6-#8 land.

Everything that means "all checks" - ``checks list``/``show``, the
conformance battery, ``tests/test_check_ids.py`` - calls this function,
so a check registered here is battery-covered and documented with no
further wiring.
"""

from __future__ import annotations

from sensor_qaqc.core.registry import Registry


def build_registry() -> Registry:
    """Every registered check, in landing order. Empty until #6-#8."""
    return Registry()
