"""Bodies for ``checks list`` and ``checks show`` (#2, ADR 0002).

The registry's inspection surface: what is registered, under which domain
and channel, requiring what, bounded by which declared false-alarm rate
and on whose authority. Rendering is separated from the command handlers
so the formatting is testable against any registry, not only the
assembled one.

``checks docs`` stays unimplemented here - it is #11's consumer of this
registry, and its diff gate lands there.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from sensor_qaqc.cli.registry import build_registry
from sensor_qaqc.core.registry import UnknownCheckError

if TYPE_CHECKING:
    import argparse

    from sensor_qaqc.core.checks import Check
    from sensor_qaqc.core.registry import Registry

# ADR 0002: 0 = output was produced (an honest empty listing is output);
# 1 = the tool could not produce a result. Local names rather than an
# import from __main__, which would be circular - __main__ imports this
# module to wire the handlers.
_EXIT_PRODUCED = 0
_EXIT_NO_RESULT = 1


def render_list(registry: Registry) -> str:
    """One line per check: id, domain, channel, bound, requirements."""
    if len(registry) == 0:
        # Nothing fails silently: an empty registry is stated, not blank.
        return "no checks registered (the first checks land with #6-#8)"
    lines = []
    for check in registry:
        requirements = ", ".join(repr(r) for r in check.requirements) or "none"
        lines.append(
            f"{check.check_id}  domain={check.domain}  channel={check.channel}"
            f"  far<={check.false_alarm_bound.value:g}  requires: {requirements}"
        )
    return "\n".join(lines)


def render_show(check: Check) -> str:
    """Everything a check declares, provenance included."""
    bound = check.false_alarm_bound
    requirements = [repr(r) for r in check.requirements] or ["none"]
    lines = [
        f"check_id: {check.check_id}",
        f"domain: {check.domain}",
        f"channel: {check.channel}",
        f"false-alarm bound: {bound.value:g} (declared FAIL rate on the AR(1) null)",
        f"  source: {bound.provenance.source}",
        f"  rationale: {bound.provenance.rationale}",
        "requirements:",
        *(f"  - {requirement}" for requirement in requirements),
        f"provides: {', '.join(check.provides) or 'none'}",
        f"consumes: {', '.join(check.consumes) or 'none'}",
    ]
    return "\n".join(lines)


def checks_list_command(args: argparse.Namespace) -> int:  # noqa: ARG001 - argparse contract
    print(render_list(build_registry()))
    return _EXIT_PRODUCED


def checks_show_command(args: argparse.Namespace) -> int:
    try:
        check = build_registry().get(str(args.check_id))
    except UnknownCheckError as exc:
        # KeyError reprs its message in quotes; unwrap for the operator.
        sys.stderr.write(f"sensor-qaqc: {exc.args[0]}\n")
        return _EXIT_NO_RESULT
    print(render_show(check))
    return _EXIT_PRODUCED
