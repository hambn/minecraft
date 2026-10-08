"""Minecraft release-ID parsing, ordering and compatibility-family expansion.

Both the old scheme (``1.21.4``) and the new scheme (``26.1.2``) are dotted
integer sequences, so they share one parser.  Everything compares by integer
components, never by string prefix: ``26.1.x`` matches ``26.1``, ``26.1.1`` and
``26.1.2`` but not ``26.10``.
"""

from __future__ import annotations

import re
from typing import Iterable

_RELEASE_RE = re.compile(r"^\d+(?:\.\d+)*$")


def parse(version: str) -> tuple[int, ...]:
    """Parse a release ID into an int tuple; raise ValueError for snapshots etc."""
    text = str(version).strip()
    if not _RELEASE_RE.match(text):
        raise ValueError(f"not a Minecraft release version: {version!r}")
    return tuple(int(part) for part in text.split("."))


def try_parse(version: str) -> tuple[int, ...] | None:
    try:
        return parse(version)
    except ValueError:
        return None


def compare(a: str, b: str) -> int:
    """-1, 0, 1 like ``cmp``."""
    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)


def sort_versions(versions: Iterable[str], *, reverse: bool = False) -> list[str]:
    """Sort by components; unparseable IDs (snapshots) go last, alphabetically."""
    items = list(dict.fromkeys(versions))
    good = sorted((v for v in items if try_parse(v) is not None), key=parse, reverse=reverse)
    bad = sorted(v for v in items if try_parse(v) is None)
    return good + bad


def is_family(declared: str) -> bool:
    """True for a family label such as ``26.1.x`` (or ``26.x``)."""
    text = str(declared).strip().lower()
    return text.endswith(".x") and try_parse(text[:-2]) is not None


def family_prefix(declared: str) -> tuple[int, ...]:
    text = str(declared).strip().lower()
    if not is_family(text):
        raise ValueError(f"not a version family: {declared!r}")
    return parse(text[:-2])


def validate_declared(declared: str) -> None:
    """Raise ValueError unless ``declared`` is an exact release or a family."""
    if is_family(declared):
        return
    parse(declared)


def matches_family(family: str, version: str) -> bool:
    prefix = family_prefix(family)
    parsed = try_parse(version)
    return parsed is not None and parsed[: len(prefix)] == prefix


def expand_family(family: str, known_releases: Iterable[str]) -> list[str]:
    """Concrete releases from ``known_releases`` covered by ``family``, oldest first."""
    return sort_versions(v for v in known_releases if matches_family(family, v))


def expand(declared: Iterable[str], known_releases: Iterable[str]) -> list[str]:
    """Expand a declared list (exact IDs and families) to concrete IDs, oldest first."""
    known = list(known_releases)
    out: list[str] = []
    for item in declared:
        if is_family(item):
            out.extend(expand_family(item, known))
        else:
            out.append(str(item))
    return sort_versions(out)


def covers(declared: Iterable[str], minecraft: str) -> bool:
    """Whether any declared exact ID or family covers ``minecraft``."""
    target = try_parse(minecraft)
    if target is None:
        return False
    for item in declared:
        if is_family(item):
            if matches_family(item, minecraft):
                return True
        else:
            parsed = try_parse(item)
            if parsed is not None and parsed == target:
                return True
    return False
