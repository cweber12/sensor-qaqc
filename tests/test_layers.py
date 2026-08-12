"""Enforce the layer graph declared in ``sensor_qaqc/layers.toml`` (ADR 0001).

Both axes are checked against the same graph: intra-package imports (core
importing marine) and third-party imports (core importing erddapy) are the
same class of breach. The walk is AST-based over every node in the file, so
imports inside functions (lazy) and inside ``if TYPE_CHECKING:`` blocks are
caught too - and the negative tests below prove it, because acceptance item
3 of #1 is explicit that the test existing is not the same as the test
working.
"""

from __future__ import annotations

import ast
import importlib.resources
import sys
import tomllib
from pathlib import Path

import pytest

import sensor_qaqc

PACKAGE_ROOT = Path(sensor_qaqc.__file__).parent


def load_graph() -> dict[str, dict[str, list[str]]]:
    """Read the graph from package data - which also proves it ships."""
    raw = importlib.resources.files("sensor_qaqc").joinpath("layers.toml").read_bytes()
    graph: dict[str, dict[str, list[str]]] = tomllib.loads(raw.decode("utf-8"))["layers"]
    return graph


def _module_name(package_root: Path, file: Path) -> list[str]:
    """Dotted-name parts of ``file`` within the package rooted at ``package_root``."""
    parts = ["sensor_qaqc", *file.relative_to(package_root).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return parts


def _resolve_relative(node: ast.ImportFrom, module_parts: list[str], *, is_package: bool) -> str:
    """Absolute dotted name of a relative import's base module."""
    package = module_parts if is_package else module_parts[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imported_names(file: Path, package_root: Path) -> list[tuple[int, str]]:
    """Every absolute module name imported anywhere in ``file``, with line numbers."""
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    module_parts = _module_name(package_root, file)
    is_package = file.name == "__init__.py"
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # One name per alias, base-qualified: "from sensor_qaqc import
            # marine" must resolve to sensor_qaqc.marine, not to the bare
            # package - checking only the base would let a layer smuggle
            # another layer in as an attribute import.
            if node.level == 0:
                base = node.module or ""
            else:
                base = _resolve_relative(node, module_parts, is_package=is_package)
            names.extend(
                (node.lineno, f"{base}.{alias.name}" if base else alias.name)
                for alias in node.names
            )
    return names


def _intra_violation(
    name: str, layer: str | None, graph: dict[str, dict[str, list[str]]]
) -> str | None:
    parts = name.split(".")
    target = parts[1] if len(parts) > 1 else None
    if target is None or target not in graph:
        return None  # the root package itself, or a symbol defined on it
    if target == layer or (layer is not None and target in graph[layer]["layers"]):
        return None
    owner = "package-root files" if layer is None else f"layer {layer!r}"
    return f"{owner} may not import layer {target!r}"


def _third_party_violation(
    top: str, layer: str | None, graph: dict[str, dict[str, list[str]]]
) -> str | None:
    if layer is None:
        return f"package-root files may not import third-party {top!r}"
    allowed = graph[layer]["third_party"]
    if "*" in allowed or top in allowed:
        return None
    return f"layer {layer!r} may not import third-party {top!r}"


def _violation(name: str, layer: str | None, graph: dict[str, dict[str, list[str]]]) -> str | None:
    """Why importing ``name`` is not allowed for ``layer``, or None if it is.

    ``layer`` is None for files at the package root (``sensor_qaqc/__init__.py``),
    which belong to no layer and may import only the stdlib.
    """
    top = name.split(".", maxsplit=1)[0]
    if top == "sensor_qaqc":
        return _intra_violation(name, layer, graph)
    if top in sys.stdlib_module_names:
        return None
    return _third_party_violation(top, layer, graph)


def check_tree(package_root: Path, graph: dict[str, dict[str, list[str]]]) -> list[str]:
    """All layer-graph violations under ``package_root``, formatted file:line reason."""
    violations = []
    for file in sorted(package_root.rglob("*.py")):
        relative = file.relative_to(package_root)
        layer = relative.parts[0] if len(relative.parts) > 1 else None
        if layer is not None and layer not in graph:
            violations.append(f"{file}: directory {layer!r} is not a declared layer")
            continue
        for lineno, name in _imported_names(file, package_root):
            reason = _violation(name, layer, graph)
            if reason is not None:
                violations.append(f"{file}:{lineno}: {reason}")
    return violations


def test_layer_graph_holds() -> None:
    assert check_tree(PACKAGE_ROOT, load_graph()) == []


def test_every_layer_directory_is_declared() -> None:
    directories = {
        p.name for p in PACKAGE_ROOT.iterdir() if p.is_dir() and not p.name.startswith("__")
    }
    assert directories == set(load_graph())


# --- Negative tests: the checker must actually catch a violating import. ---


def _fake_package(tmp_path: Path, relative: str, source: str) -> Path:
    """Create a throwaway package tree containing one file with the given source."""
    root = tmp_path / "sensor_qaqc"
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        (
            "core/bad_third_party.py",
            "import erddapy\n",
            "may not import third-party 'erddapy'",
        ),
        (
            "core/bad_intra.py",
            "from sensor_qaqc.marine import integrity\n",
            "layer 'core' may not import layer 'marine'",
        ),
        (
            "core/bad_lazy.py",
            "def f() -> None:\n    import scipy\n",
            "may not import third-party 'scipy'",
        ),
        (
            "core/bad_type_checking.py",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import ioos_qc\n",
            "may not import third-party 'ioos_qc'",
        ),
        (
            "instruments/bad_relative.py",
            "from .. import marine\n",
            "layer 'instruments' may not import layer 'marine'",
        ),
        (
            "bad_root.py",
            "import numpy\n",
            "package-root files may not import third-party 'numpy'",
        ),
    ],
)
def test_checker_catches_violation(
    tmp_path: Path, relative: str, source: str, expected: str
) -> None:
    root = _fake_package(tmp_path, relative, source)
    violations = check_tree(root, load_graph())
    assert len(violations) == 1
    assert expected in violations[0]


def test_checker_allows_declared_imports(tmp_path: Path) -> None:
    root = _fake_package(
        tmp_path,
        "instruments/good.py",
        "import pandas\nfrom sensor_qaqc.core import __doc__ as core_doc\n",
    )
    assert check_tree(root, load_graph()) == []
