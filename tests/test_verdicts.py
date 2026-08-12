"""The verdict vocabulary is exactly four states and INCONCLUSIVE needs a reason (#2)."""

from __future__ import annotations

import dataclasses

import pytest

from sensor_qaqc.core.verdicts import CheckResult, Verdict


def test_the_vocabulary_is_exactly_four_states() -> None:
    assert [v.value for v in Verdict] == ["PASS", "MARGINAL", "FAIL", "INCONCLUSIVE"]


def test_verdicts_serialise_as_their_names() -> None:
    # Verdicts land in results.json and archived run folders as strings.
    assert str(Verdict.INCONCLUSIVE) == "INCONCLUSIVE"
    assert Verdict("PASS") is Verdict.PASS


def test_there_is_no_ok_attribute() -> None:
    # ok = verdict == "PASS" is banned; the types must not offer a shortcut.
    assert not hasattr(Verdict.PASS, "ok")
    assert not hasattr(CheckResult(verdict=Verdict.PASS), "ok")


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_inconclusive_without_a_reason_cannot_be_constructed(reason: str | None) -> None:
    with pytest.raises(ValueError, match="without a reason"):
        CheckResult(verdict=Verdict.INCONCLUSIVE, reason=reason)


def test_inconclusive_with_a_reason_carries_it() -> None:
    result = CheckResult(verdict=Verdict.INCONCLUSIVE, reason="n_valid=34 < required 50")
    assert result.reason == "n_valid=34 < required 50"


@pytest.mark.parametrize("verdict", [Verdict.PASS, Verdict.MARGINAL, Verdict.FAIL])
def test_other_verdicts_need_no_reason_but_may_carry_one(verdict: Verdict) -> None:
    assert CheckResult(verdict=verdict).reason is None
    assert CheckResult(verdict=verdict, reason="why").reason == "why"


def test_results_are_frozen_and_compare_by_value() -> None:
    # Battery case 5 (determinism) compares results by equality.
    a = CheckResult(verdict=Verdict.PASS, metrics={"sqnr_db": 41.2})
    b = CheckResult(verdict=Verdict.PASS, metrics={"sqnr_db": 41.2})
    assert a == b
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.verdict = Verdict.FAIL  # type: ignore[misc]
