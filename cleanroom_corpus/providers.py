"""Optional external adapters used only on registry cache misses."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


NAME_CLASSIFIER_REPOSITORY = (
    "https://github.com/name-ethnicity-classifier/name-ethnicity-classifier"
)
NAME_CLASSIFIER_REVISION = "282016c123c81de48f4524aacd5a1728ecc330c4"
DIFFSYNFACE_REPOSITORY = "https://github.com/tanusreeg/DiffSynFace"
DIFFSYNFACE_REVISION = "5150cf91c5c6d7ed5eddfd44b8acbf4933b06002"


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    distribution: dict[str, float]
    provider: str
    revision: str
    model: str


class SurnameClassifier(Protocol):
    provider: str
    revision: str
    model: str

    def classify(self, surname: str) -> Classification: ...


class HeadshotProvider(Protocol):
    provider: str
    revision: str

    def render(self, *, person_key: str, prompt: str, attributes: dict[str, Any]) -> bytes: ...


class NameEthnicityCommandClassifier:
    """Run a pinned checkout of name-ethnicity-classifier out of process.

    Keeping the AGPL program across a process boundary avoids importing or
    copying its implementation into this package. The checkout must be at the
    configured revision; this adapter rejects a moving or dirty dependency.
    """

    provider = NAME_CLASSIFIER_REPOSITORY

    def __init__(
        self,
        checkout: Path,
        *,
        revision: str = NAME_CLASSIFIER_REVISION,
        model: str = "8_groups",
        python: str = "python3",
        device: str = "cpu",
        timeout: int = 120,
    ) -> None:
        self.checkout = checkout.resolve()
        self.revision = revision
        self.model = model
        self.python = python
        if device not in {"cpu", "gpu"}:
            raise ValueError("classifier device must be 'cpu' or 'gpu'")
        self.device = device
        self.timeout = timeout

    def _path_for_runtime(self, path: Path) -> str:
        if self.python.casefold().endswith(".exe") and os.name != "nt":
            return subprocess.run(
                ["wslpath", "-w", str(path)], check=True,
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        return str(path)

    def _verify_checkout(self) -> None:
        result = subprocess.run(
            ["git", "-C", str(self.checkout), "status", "--porcelain", "--untracked-files=no"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        head = subprocess.run(
            ["git", "-C", str(self.checkout), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if result.stdout or head != self.revision:
            raise RuntimeError("name classifier checkout must be clean and at pinned revision")

    def classify(self, surname: str) -> Classification:
        self._verify_checkout()
        with tempfile.TemporaryDirectory(prefix="ficta-name-classifier-") as temporary:
            input_path = Path(temporary) / "surname.csv"
            output = Path(temporary) / "prediction.csv"
            input_path.write_text(f"names\n{json.dumps(surname)}\n", encoding="utf-8")
            command = [
                self.python, "predict_ethnicity.py", "-i", self._path_for_runtime(input_path),
                "-o", self._path_for_runtime(output), "-m", self.model,
                "-d", self.device, "--distribution",
            ]
            completed = subprocess.run(
                command, cwd=self.checkout, check=True, capture_output=True,
                text=True, timeout=self.timeout,
            )
            # Prefer a structured final JSON line when supplied by a wrapper.
            for line in reversed(completed.stdout.splitlines()):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and "label" in row:
                    distribution = {str(k): float(v) for k, v in row.get("distribution", {}).items()}
                    return Classification(
                        str(row["label"]), float(row.get("confidence", 0.0)),
                        distribution, self.provider, self.revision, self.model,
                    )
            if output.exists():
                import csv
                with output.open(encoding="utf-8", newline="") as handle:
                    row = next(csv.DictReader(handle))
                label = str(row.pop("predictions"))
                distribution = {
                    key: float(value) / 100.0 for key, value in row.items()
                    if key.casefold() != "names" and value not in (None, "")
                }
                confidence = distribution.get(label, 0.0)
                return Classification(
                    label, confidence, distribution, self.provider,
                    self.revision, self.model,
                )
        raise RuntimeError("classifier returned no structured prediction")


class DiffSynFaceDirectoryProvider:
    """Deterministically select an authorized DiffSynFace image directory."""

    provider = DIFFSYNFACE_REPOSITORY

    def __init__(self, root: Path, *, revision: str = DIFFSYNFACE_REVISION) -> None:
        self.root = root.resolve()
        self.revision = revision

    def render(self, *, person_key: str, prompt: str, attributes: dict[str, Any]) -> bytes:
        candidates = sorted(
            path for path in self.root.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if not candidates:
            raise FileNotFoundError(f"no DiffSynFace images under {self.root}")
        digest = hashlib.sha256(
            json.dumps([person_key, prompt, attributes], sort_keys=True).encode()
        ).digest()
        return candidates[int.from_bytes(digest[:8], "big") % len(candidates)].read_bytes()


class MappedHeadshotDirectoryProvider:
    """Read one pre-generated image named ``<person-key>.png`` per profile."""

    def __init__(self, root: Path, *, provider: str, revision: str) -> None:
        self.root = root.resolve()
        self.provider = provider
        self.revision = revision

    def render(self, *, person_key: str, prompt: str, attributes: dict[str, Any]) -> bytes:
        path = self.root / f"{person_key}.png"
        if not path.is_file():
            raise FileNotFoundError(f"missing generated headshot: {path}")
        return path.read_bytes()


class HeadshotCommandProvider:
    """Invoke a deterministic image generator that writes to ``$OUTPUT_PATH``."""

    def __init__(self, command: list[str], *, provider: str, revision: str, timeout: int = 600) -> None:
        if not command:
            raise ValueError("headshot command is required")
        self.command = command
        self.provider = provider
        self.revision = revision
        self.timeout = timeout

    def render(self, *, person_key: str, prompt: str, attributes: dict[str, Any]) -> bytes:
        with tempfile.TemporaryDirectory(prefix="ficta-headshot-") as temporary:
            output = Path(temporary) / "headshot.png"
            environment = os.environ.copy()
            environment.update({
                "OUTPUT_PATH": str(output),
                "SYNTHETIC_PERSON_KEY": person_key,
                "SYNTHETIC_PROMPT": prompt,
                "SYNTHETIC_ATTRIBUTES_JSON": json.dumps(attributes, sort_keys=True),
            })
            subprocess.run(
                self.command, check=True, env=environment,
                capture_output=True, timeout=self.timeout,
            )
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError("headshot command did not create OUTPUT_PATH")
            return output.read_bytes()
