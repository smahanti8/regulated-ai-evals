"""Run and system-under-test identity.

An evidence bundle that cannot name the exact code it tested is not evidence.
Everything in this module exists to make the bundle self-describing: which
commit, which interpreter, which platform, which harness version, and whether
the tree was dirty at the time.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .hashing import content_hash

HARNESS_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class SUTIdentity:
    """Who was tested."""

    name: str
    source: str
    """Where the code came from: a git URL, or a local path for in-tree code."""
    commit: str
    """Full SHA for a pinned clone. For local uncommitted code, "worktree"."""
    dirty: bool
    """True when the tested tree had uncommitted changes. A dirty run can still
    be useful during development but must never be presented as evidence, so
    the flag travels with the bundle rather than being checked and discarded."""
    version: str | None = None

    @property
    def is_reconstructible(self) -> bool:
        return self.commit != "worktree" and not self.dirty


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    python_version: str
    platform: str
    machine: str
    harness_version: str

    @classmethod
    def capture(cls) -> EnvironmentRecord:
        return cls(
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            machine=platform.machine(),
            harness_version=HARNESS_VERSION,
        )


@dataclass(slots=True)
class RunRecord:
    """The spine of a bundle: one run, one id, one clock reading.

    started_at is sampled once and then reused everywhere a timestamp is
    needed. Nothing in the bundle calls the wall clock again, so a bundle
    rebuilt from the same run record is byte-identical.
    """

    run_id: str
    started_at: str
    environment: EnvironmentRecord
    suts: list[SUTIdentity] = field(default_factory=list)
    invocation: str = ""

    @classmethod
    def start(cls, invocation: str = "") -> RunRecord:
        return cls(
            run_id=uuid.uuid4().hex[:12],
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            environment=EnvironmentRecord.capture(),
            invocation=invocation,
        )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "invocation": self.invocation,
            "environment": asdict(self.environment),
            "systems_under_test": [asdict(s) for s in self.suts],
        }


def git_identity(repo: Path, name: str, source: str) -> SUTIdentity:
    """Read commit and dirty state from a git working tree.

    Falls back to a "worktree" commit rather than raising: code that is not
    under version control is a legitimate thing to test, it just cannot produce
    a reconstructible bundle, and SUTIdentity.is_reconstructible says so.
    """

    def _git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return result.stdout.strip()

    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return SUTIdentity(name=name, source=source, commit="worktree", dirty=True)
    status = _git("status", "--porcelain")
    return SUTIdentity(
        name=name, source=source, commit=commit, dirty=bool(status)
    )


def accepting_party() -> str:
    """Resolve who is signing off, or refuse.

    Used only by --accept-risk. An accepted non-conformance with no named
    acceptor is not an acceptance, so this raises rather than defaulting to
    something like "unknown".
    """

    def _git_config(key: str) -> str:
        try:
            result = subprocess.run(
                ["git", "config", "--get", key], capture_output=True, text=True
            )
        except FileNotFoundError:
            return ""
        return result.stdout.strip()

    name, email = _git_config("user.name"), _git_config("user.email")
    if name and email:
        return f"{name} <{email}>"
    if email:
        return email
    raise ValueError(
        "Cannot resolve who is accepting this risk. Pass --accepted-by, or set "
        "git config user.name and user.email. An accepted non-conformance must "
        "name a person."
    )


def config_hash(config: dict) -> str:
    return content_hash(config)
