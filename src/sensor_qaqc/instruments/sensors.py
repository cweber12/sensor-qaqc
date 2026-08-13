"""Datasheet facts, keyed by product, each carrying its citation (#3).

The catalogue is the answer to "what can this product actually report?" -
today only the set of native units, which ingest checks the export's declared
unit against. That check is cheap and the failure it prevents is not: a degC
threshold compared against a degF series is wrong by a factor no downstream
check would recognise as a unit error, because every number involved is
plausible.

Facts carry ``Provenance`` from ``core`` - the same mandatory (source,
rationale) pair thresholds carry - so "every value carrying its datasheet
citation" is enforced by construction rather than by review. A fact name the
loader does not read is refused rather than ignored: an unread number in a
file like this one wears the authority of the file it sits in without anyone
having verified it.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

import yaml

from sensor_qaqc.core.thresholds import Provenance

if TYPE_CHECKING:
    from collections.abc import Mapping

T = TypeVar("T")

# Grown by the commit whose code reads the new fact (ADR 0005).
KNOWN_FACTS = frozenset({"native_units"})


class MissingSensorError(LookupError):
    """No datasheet facts for the requested product; the run must refuse."""


@dataclass(frozen=True)
class SensorFact(Generic[T]):
    """One datasheet value and the citation that justifies it."""

    value: T
    provenance: Provenance


@dataclass(frozen=True)
class SensorSpec:
    """What the catalogue knows about one product model."""

    product: str
    native_units: SensorFact[frozenset[str]]


class SensorCatalogue:
    """Datasheet facts by product model, with no default and no fallback."""

    def __init__(self, by_product: Mapping[str, SensorSpec]) -> None:
        self._by_product = dict(by_product)

    @property
    def products(self) -> frozenset[str]:
        return frozenset(self._by_product)

    def for_product(self, product: str) -> SensorSpec:
        if product not in self._by_product:
            known = ", ".join(sorted(self._by_product)) or "none"
            raise MissingSensorError(
                f"no sensor metadata for product {product!r}; the catalogue knows: {known}."
                " Refusing to guess what the logger can report."
            )
        return self._by_product[product]


def _fact_provenance(product: str, name: str, raw: Mapping[str, object]) -> Provenance:
    for key in ("source", "rationale"):
        if not str(raw.get(key, "")).strip():
            raise ValueError(f"{product}.{name} in sensors.yaml has no {key}")
    return Provenance(source=str(raw["source"]), rationale=str(raw["rationale"]))


def _spec(product: str, raw: Mapping[str, Mapping[str, object]]) -> SensorSpec:
    unknown = sorted(set(raw) - KNOWN_FACTS)
    if unknown:
        raise ValueError(
            f"sensors.yaml declares {unknown} for {product}, which nothing reads."
            " A fact arrives in the commit whose code reads it (ADR 0005)."
        )
    if "native_units" not in raw:
        raise ValueError(f"sensors.yaml gives {product} no native_units")
    units = raw["native_units"]
    value = units.get("value")
    if not isinstance(value, list) or not value:
        raise ValueError(f"{product}.native_units needs a non-empty list value, got {value!r}")
    return SensorSpec(
        product=product,
        native_units=SensorFact(
            value=frozenset(str(unit) for unit in value),
            provenance=_fact_provenance(product, "native_units", units),
        ),
    )


def parse_sensor_catalogue(text: str) -> SensorCatalogue:
    """Build a catalogue from YAML text, refusing anything under-specified."""
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or "sensors" not in document:
        raise ValueError("sensors.yaml must be a mapping with a top-level 'sensors' key")
    sensors = document["sensors"]
    if not isinstance(sensors, dict) or not sensors:
        raise ValueError("sensors.yaml declares no sensors")
    return SensorCatalogue({str(name): _spec(str(name), raw) for name, raw in sensors.items()})


def load_sensor_catalogue() -> SensorCatalogue:
    """Read the packaged catalogue - through resources, never through __file__."""
    resource = importlib.resources.files("sensor_qaqc.instruments").joinpath("sensors.yaml")
    return parse_sensor_catalogue(resource.read_text(encoding="utf-8"))
