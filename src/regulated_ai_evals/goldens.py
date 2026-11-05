"""Versioned golden sets.

Two questions an auditor will ask about any number you publish: which data
produced it, and has that data changed since. A directory of CSVs answers
neither. A golden set here is a manifest — id, semantic version, content hash,
provenance, and a PHI attestation — sitting next to the data it describes.

The content hash is the real identity. The version is for humans.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .hashing import content_hash, file_hash


@dataclass(frozen=True, slots=True)
class GoldenSetRef:
    """A pointer that survives being written down.

    Carried into calibration evidence and evidence bundles so a reader can tell
    whether two results came from the same data without having the data.
    """

    id: str
    version: str
    content_hash: str

    def to_dict(self) -> dict:
        return {"id": self.id, "version": self.version, "content_hash": self.content_hash}

    def __str__(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class GoldenProvenance:
    derived_from: str
    synthetic: bool
    contains_phi: bool
    deidentification: str | None
    labelled_by: str
    """Who applied the labels. Ground truth is an assertion by a person; the
    person is part of the evidence."""
    frozen_on: date

    def to_dict(self) -> dict:
        return {
            "derived_from": self.derived_from,
            "synthetic": self.synthetic,
            "contains_phi": self.contains_phi,
            "deidentification": self.deidentification,
            "labelled_by": self.labelled_by,
            "frozen_on": self.frozen_on.isoformat(),
        }


class GoldenSetError(ValueError):
    pass


# Shapes that should never appear in a set attested as synthetic. Deliberately
# broad: a false positive costs a reviewer thirty seconds, a false negative
# costs a disclosure. Patterns are structural only -- no real identifiers here.
_IDENTIFIER_SHAPES: tuple[tuple[str, str], ...] = (
    (r"\b\d{3}-\d{2}-\d{4}\b", "US SSN shape (NNN-NN-NNNN)"),
    (r"\b\d{10}\b", "10-digit run (NHS number / MRN shape)"),
    (r"\b\d{4}-\d{2}-\d{2}T?\b(?!\d)", "ISO date (possible DOB)"),
    (r"\b[A-Z]{2}\d{6}[A-Z]?\b", "national insurance / passport shape"),
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "email address"),
)


@dataclass(slots=True)
class GoldenSet:
    id: str
    version: str
    description: str
    provenance: GoldenProvenance
    records: list[dict[str, Any]]
    label_field: str
    directory: Path | None = None
    _manifest_hash: str | None = field(default=None, repr=False)

    @property
    def content_hash(self) -> str:
        return content_hash({"id": self.id, "records": self.records})

    @property
    def ref(self) -> GoldenSetRef:
        return GoldenSetRef(self.id, self.version, self.content_hash)

    @property
    def positives(self) -> int:
        return sum(1 for r in self.records if r[self.label_field])

    def scan_identifiers(self) -> list[str]:
        """Structural search for identifier-shaped values.

        Runs on every set attested synthetic. It cannot prove the absence of
        PHI, and does not claim to -- it catches the realistic failure, which
        is a real extract being copied into a fixture and relabelled.
        """
        findings: list[str] = []
        for index, record in enumerate(self.records):
            for key, value in record.items():
                text = str(value)
                for pattern, label in _IDENTIFIER_SHAPES:
                    if re.search(pattern, text):
                        findings.append(f"record {index} field {key!r}: {label}")
        return findings

    def verify(self) -> None:
        """Fail if the data has drifted from what the manifest describes."""
        if self._manifest_hash and self._manifest_hash != self.content_hash:
            raise GoldenSetError(
                f"{self.id}@{self.version} content hash does not match its manifest.\n"
                f"  manifest: {self._manifest_hash}\n"
                f"  on disk : {self.content_hash}\n"
                "The data changed without the version changing. Any result "
                "previously attributed to this set is now unattributable."
            )
        if self.provenance.synthetic and self.provenance.contains_phi:
            raise GoldenSetError(
                f"{self.id} is attested synthetic and contains_phi at the same time."
            )
        if self.provenance.synthetic:
            findings = self.scan_identifiers()
            if findings:
                raise GoldenSetError(
                    f"{self.id} is attested synthetic but contains identifier-shaped "
                    "values:\n  " + "\n  ".join(findings[:10])
                )

    @classmethod
    def load(cls, directory: Path) -> GoldenSet:
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise GoldenSetError(f"No manifest.json in {directory}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        data_path = directory / manifest["data_file"]
        if file_hash(data_path) != manifest["data_file_hash"]:
            raise GoldenSetError(
                f"{manifest['id']}: {manifest['data_file']} does not match the hash "
                "recorded in its manifest."
            )

        with data_path.open(newline="", encoding="utf-8") as handle:
            records = [_coerce(row) for row in csv.DictReader(handle)]

        provenance = manifest["provenance"]
        return cls(
            id=manifest["id"],
            version=manifest["version"],
            description=manifest["description"],
            label_field=manifest["label_field"],
            records=records,
            directory=directory,
            _manifest_hash=manifest["content_hash"],
            provenance=GoldenProvenance(
                derived_from=provenance["derived_from"],
                synthetic=provenance["synthetic"],
                contains_phi=provenance["contains_phi"],
                deidentification=provenance.get("deidentification"),
                labelled_by=provenance["labelled_by"],
                frozen_on=date.fromisoformat(provenance["frozen_on"]),
            ),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "description": self.description,
            "content_hash": self.content_hash,
            "records": len(self.records),
            "positives": self.positives,
            "label_field": self.label_field,
            "provenance": self.provenance.to_dict(),
        }


def _coerce(row: dict[str, str]) -> dict[str, Any]:
    """CSV gives strings; labels and numbers need to be what they claim to be.

    Done at load rather than at use so the content hash is computed over typed
    values and does not shift when a caller parses a column differently.
    """
    out: dict[str, Any] = {}
    for key, value in row.items():
        if value in ("true", "false"):
            out[key] = value == "true"
        else:
            try:
                out[key] = float(value) if "." in value else int(value)
            except ValueError:
                out[key] = value
    return out


def load_all(directory: Path) -> dict[str, GoldenSet]:
    sets: dict[str, GoldenSet] = {}
    for manifest in sorted(directory.glob("*/manifest.json")):
        golden = GoldenSet.load(manifest.parent)
        sets[golden.id] = golden
    return sets
