"""Pinned acquisition of the systems under test.

An evidence bundle that cannot name the exact code it tested is not evidence.
So the harness never tests whatever happens to be checked out on the machine:
it materialises each system under test into .sut/ at a pinned identity recorded
in sut.lock, and puts that identity in the bundle.

Two kinds, because not every system is a git repository:

  git   -- pinned by commit SHA, fetched from a remote.
  path  -- pinned by content hash, copied from a local file or directory. Used
           for code that is not under version control. Weaker provenance than a
           SHA, and honest about it: the hash still fails the run if the source
           moves underneath you.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import yaml

from .calibration import Threshold
from .hashing import content_hash, file_hash
from .identity import SUTIdentity
from .structural import DecisionPath


class SystemUnderTest(Protocol):
    """What an adapter must expose for the harness to evaluate a system.

    Deliberately small. An adapter declares where the decisions live and where
    the magic numbers live; it does not run the system, because running it is
    the test suite's job and mixing the two would let an adapter quietly decide
    what counts as a pass.
    """

    name: str

    def identity(self) -> SUTIdentity: ...

    def thresholds(self) -> Sequence[Threshold]: ...

    def decision_paths(self) -> Sequence[DecisionPath]: ...


@dataclass(frozen=True, slots=True)
class PinnedSource:
    name: str
    kind: str
    location: str
    pin: str
    """Commit SHA for kind=git, content hash for kind=path."""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "location": self.location,
            "pin": self.pin,
        }


class FetchError(RuntimeError):
    pass


def load_lock(path: Path) -> list[PinnedSource]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        PinnedSource(
            name=raw["name"],
            kind=raw["kind"],
            location=raw["location"],
            pin=raw["pin"],
        )
        for raw in document.get("systems", [])
    ]


def fetch(source: PinnedSource, into: Path) -> Path:
    """Materialise one pinned source. Returns its directory in .sut/."""
    destination = into / source.name
    if source.kind == "git":
        return _fetch_git(source, destination)
    if source.kind == "path":
        return _fetch_path(source, destination)
    raise FetchError(f"{source.name}: unknown kind {source.kind!r}")


def _fetch_git(source: PinnedSource, destination: Path) -> Path:
    if (destination / ".git").exists():
        head = _git(destination, "rev-parse", "HEAD")
        if head == source.pin:
            return destination
        shutil.rmtree(destination, ignore_errors=True)

    destination.mkdir(parents=True, exist_ok=True)
    _git(destination, "init", "-q")
    _git(destination, "remote", "add", "origin", source.location)
    # Fetching the single pinned commit rather than a branch: a branch tip moves,
    # and the whole point of the lock file is that this one does not.
    _git(destination, "fetch", "-q", "--depth", "1", "origin", source.pin)
    _git(destination, "checkout", "-q", "FETCH_HEAD")

    head = _git(destination, "rev-parse", "HEAD")
    if head != source.pin:
        raise FetchError(
            f"{source.name}: checked out {head}, expected {source.pin}"
        )
    return destination


def _fetch_path(source: PinnedSource, destination: Path) -> Path:
    origin = Path(source.location).expanduser()
    if not origin.exists():
        raise FetchError(f"{source.name}: {origin} does not exist")

    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    if origin.is_file():
        shutil.copy2(origin, destination / origin.name)
    else:
        shutil.copytree(origin, destination, dirs_exist_ok=True)

    actual = directory_hash(destination)
    if actual != source.pin:
        raise FetchError(
            f"{source.name}: content hash {actual} does not match the pin in "
            f"sut.lock ({source.pin}).\n"
            "The source changed since the lock was written. Review the change, "
            "then re-pin with `rae pin`. Any bundle produced against the old pin "
            "still describes the old code, which is the point."
        )
    return destination


def directory_hash(directory: Path) -> str:
    """Hash of a tree's contents, ignoring anything git or Python leaves behind."""
    entries = {}
    for file in sorted(directory.rglob("*")):
        if file.is_dir() or _ignored(file):
            continue
        entries[str(file.relative_to(directory)).replace("\\", "/")] = file_hash(file)
    return content_hash(entries)


def _ignored(file: Path) -> bool:
    parts = set(file.parts)
    return bool(parts & {".git", "__pycache__", ".pytest_cache", ".venv"})


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise FetchError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr.strip()}"
        )
    return result.stdout.strip()
