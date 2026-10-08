"""Provider-independent data model shared by the upstream clients."""

from __future__ import annotations

from dataclasses import dataclass, field


class ProviderUnavailable(Exception):
    """The provider cannot be used (for example a missing API key)."""


@dataclass
class FileInfo:
    filename: str
    url: str
    sha512: str | None = None
    sha1: str | None = None
    size: int | None = None


@dataclass
class DependencyRef:
    provider: str
    project_id: str
    version_id: str | None
    kind: str  # required | optional | incompatible | embedded


@dataclass
class ProjectInfo:
    provider: str
    project_id: str
    slug: str
    name: str | None
    description: str | None
    authors: list[str] = field(default_factory=list)
    license: str | None = None
    homepage: str | None = None
    server_side: str = "unknown"  # required | optional | unsupported | unknown
    distribution_allowed: bool | None = None  # None = not reported
    missing: list[str] = field(default_factory=list)


@dataclass
class ReleaseInfo:
    provider: str
    project_id: str
    version_id: str
    version_number: str
    name: str
    release_type: str  # release | beta | alpha
    published: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    file: FileInfo | None = None
    dependencies: list[DependencyRef] = field(default_factory=list)
