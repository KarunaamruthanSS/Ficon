"""The converter registry.

Every conversion the tool can do is one entry here: a (source, target) pair
mapped to a function. Adding a new format means writing a function and
decorating it with @converter; nothing else in the tool has to change.

When there is no direct converter between two formats, find_route() chains
several of them (for example HEIC -> PNG -> PDF).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# A converter takes the source path, the destination path and the options
# the user passed, and writes the destination file.
ConvertFn = Callable[[Path, Path, "Options"], None]

QUALITY_RANGE = (1, 100)


class ConversionError(Exception):
    """A conversion failed for a reason worth showing to the user."""


@dataclass
class Options:
    """Settings the user can pass on the command line.

    Validated here rather than only in the argument parser, so that a GUI
    or another program using offconv as a library cannot reach a converter
    with values Pillow would either reject with a stack trace or silently
    accept as nonsense.
    """

    quality: int = 90
    resize: tuple[int, int] | None = None  # max width, max height
    max_pixels: int = 0  # 0 means "use the default budget"
    keep_metadata: bool = False
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        low, high = QUALITY_RANGE
        if not isinstance(self.quality, int) or not low <= self.quality <= high:
            raise ValueError(f"quality must be a whole number from {low} to {high}")
        if self.resize is not None:
            width, height = self.resize
            if width < 1 or height < 1:
                raise ValueError("resize width and height must be 1 or more")
        if self.max_pixels < 0:
            raise ValueError("max_pixels cannot be negative")


_CONVERTERS: dict[tuple[str, str], ConvertFn] = {}
# src -> targets reachable in one step. Kept alongside _CONVERTERS so that
# route finding walks only real neighbours instead of rescanning every
# registered pair for every node it visits.
_EDGES: dict[str, set[str]] = defaultdict(set)


def converter(sources: Iterable[str], targets: Iterable[str]):
    """Register a function for every (source, target) pair given."""

    def decorate(fn: ConvertFn) -> ConvertFn:
        for src in sources:
            for dst in targets:
                if src != dst:
                    _CONVERTERS[(src, dst)] = fn
                    _EDGES[src].add(dst)
        return fn

    return decorate


def _reachable(src: str) -> dict[str, str]:
    """Breadth-first walk from `src`, returning {format: came_from}."""
    came_from: dict[str, str] = {}
    seen = {src}
    queue = deque([src])
    while queue:
        current = queue.popleft()
        for nxt in _EDGES.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                came_from[nxt] = current
                queue.append(nxt)
    return came_from


def targets_for(src: str) -> list[str]:
    """Every format reachable from `src`, directly or through a chain."""
    return sorted(_reachable(src))


def sources() -> list[str]:
    return sorted(_EDGES)


def find_route(src: str, dst: str) -> list[tuple[str, str]] | None:
    """Shortest chain of conversions from src to dst, or None."""
    if src == dst:
        return None
    if (src, dst) in _CONVERTERS:
        return [(src, dst)]
    came_from = _reachable(src)
    if dst not in came_from:
        return None
    route: list[tuple[str, str]] = []
    step = dst
    while step != src:
        route.append((came_from[step], step))
        step = came_from[step]
    route.reverse()
    return route


def get(src: str, dst: str) -> ConvertFn:
    return _CONVERTERS[(src, dst)]


@contextmanager
def isolated() -> Iterator[None]:
    """Restore the registry on exit, so tests can register fake formats.

    Without this, a converter registered by a test stays in the global
    table and shows up in `offconv formats` for every later test.
    """
    saved_converters = dict(_CONVERTERS)
    saved_edges = {key: set(value) for key, value in _EDGES.items()}
    try:
        yield
    finally:
        _CONVERTERS.clear()
        _CONVERTERS.update(saved_converters)
        _EDGES.clear()
        _EDGES.update(saved_edges)
