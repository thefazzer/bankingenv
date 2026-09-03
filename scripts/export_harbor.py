#!/usr/bin/env python3
"""Export BankingEnv sealed episodes as harbor task directories.

Layout, one directory per sealed episode (docs/HARBOR-PACKAGING.md):

    <out>/bankingenv-<slug>-<sha8>/
        instruction.md            agent-facing prompt, rendered from the task card
        task.toml                 harbor task config and metadata
        bankingenv.json           recipe-side metadata (the archipelago.json analogue)
        environment/Dockerfile    per-family environment image (placeholder)
        tests/test.sh             verifier entrypoint harbor runs after the agent
        tests/grade.py            deterministic trajectory-replay verifier
        tests/Dockerfile          separate verifier image
        tests/sealed_episode.json the sealed episode, byte-identical to the asset
        tests/checks.json         the deterministic check list the verifier applies
        tests/certificate.json    per-task certificate, NOT_ISSUED until certified
        tests/canary.json         present only when a canary was minted
        tests/runner/             vendored grading code (--vendor-runner)

Nothing under tests/ is visible to the agent. The task card is verified
against its episode (cleanroom_eval.episode_contract.verify_contract) before
anything is rendered, and the rendered instruction is checked again for
oracle leakage. No task content is invented: every rendered field comes from
the sealed assets. Certificates are written NOT_ISSUED; this script never
fills one.

Dry run (writes nothing):

    python3 scripts/export_harbor.py --dry-run --set v2 --out /tmp/harbor-tasks
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cleanroom_eval.contract import (  # noqa: E402
    ASSET_DIR,
    CLASSIFICATION,
    ContractError,
    digest,
    file_sha256,
    load_json,
)
from cleanroom_eval.episode_contract import (  # noqa: E402
    ORACLE_FIELDS,
    TASK_SUFFIX,
    build_contract,
    contract_path,
    verify_contract,
)
from cleanroom_eval.free_run import episode_canary  # noqa: E402

SETS = {
    "v1": ("episodes", "sealed-set.manifest.v1.json"),
    "v2": ("episodes_v2", "sealed-set.manifest.v2.json"),
}
SPLITS = ("public_dev", "private_test")
TASK_SCHEMA = "bankingenv.harbor-task/v1"
CERTIFICATE_SCHEMA = "bankingenv.task-certificate/v1"
TRAJECTORY_SCHEMA = "bankingenv.trajectory/v1"
TRAJECTORY_PATH = "/logs/agent/trajectory.json"
EM_DASH = "\u2014"

CERTIFICATE_REQUIREMENTS = (
    {
        "id": "unaided_fails",
        "description": (
            "A frozen reference model given instruction.md and no environment "
            "access does not produce a trajectory that grades 1."
        ),
    },
    {
        "id": "naive_retrieval_fails",
        "description": (
            "The same model given instruction.md plus the most lexically similar "
            "public evidence records, without interacting with the boundary, does "
            "not produce a trajectory that grades 1."
        ),
    },
    {
        "id": "oracle_passes",
        "description": (
            "The sealed script replayed through the boundary grades 1. The "
            "verifier executes this as a self-check on every grading run; the "
            "certificate records it once under the certification protocol."
        ),
    },
)


class ExportError(ValueError):
    """Raised when the export would publish something it must not."""


@dataclass(frozen=True)
class EpisodeSource:
    path: Path
    episode: dict[str, Any]
    card: dict[str, Any]
    sha256: str
    set_id: str
    manifest_path: str | None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _manifest_index(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {asset["path"]: asset["sha256"] for asset in manifest["assets"]}


def discover(
    *,
    set_name: str | None,
    episodes_dir: Path | None,
    split: str,
    limit: int | None,
) -> list[EpisodeSource]:
    if (set_name is None) == (episodes_dir is None):
        raise ExportError("give exactly one of --set and --episodes")
    manifest_index: dict[str, str] = {}
    set_id = "external"
    if set_name is not None:
        subdir, manifest_name = SETS[set_name]
        episodes_dir = ASSET_DIR / subdir
        manifest = load_json(ASSET_DIR / manifest_name)
        manifest_index = _manifest_index(manifest)
        set_id = manifest["set_id"]
    assert episodes_dir is not None
    episodes_dir = episodes_dir.resolve()
    if split == "private_test":
        try:
            episodes_dir.relative_to(ASSET_DIR.resolve())
        except ValueError:
            pass
        else:
            raise ExportError(
                "the private test split must come from an unpublished world; "
                f"{episodes_dir} is under the public asset tree"
            )
    sources: list[EpisodeSource] = []
    for path in sorted(episodes_dir.glob("*.json")):
        if path.name.endswith(TASK_SUFFIX):
            continue
        episode = load_json(path)
        card_path = contract_path(path)
        card = load_json(card_path) if card_path.is_file() else build_contract(episode)
        verify_contract(card, episode)
        sha = file_sha256(path)
        manifest_path = None
        if manifest_index:
            manifest_path = str(path.relative_to(ASSET_DIR.resolve()))
            expected = manifest_index.get(manifest_path)
            if expected is None:
                raise ContractError(f"{manifest_path} is not in the sealed-set manifest")
            if expected != sha:
                raise ContractError(f"sealed asset differs from its manifest entry: {manifest_path}")
        sources.append(EpisodeSource(path, episode, card, sha, set_id, manifest_path))
    if not sources:
        raise ExportError(f"no episodes under {episodes_dir}")
    return sources[:limit] if limit else sources


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _plain(text: str) -> str:
    """House style for rendered text: no U+2014. Sealed bytes are untouched."""

    return text.replace(f" {EM_DASH} ", ": ").replace(EM_DASH, ":")


def task_slug(episode_id: str) -> str:
    return episode_id.removeprefix("episode_").removesuffix("_v1").replace("_", "-")


def task_dir_name(episode_id: str, sha256: str) -> str:
    return f"bankingenv-{task_slug(episode_id)}-{sha256[:8]}"


def render_instruction(card: Mapping[str, Any], canary: str | None) -> str:
    lines: list[str] = []
    lines.append(f"# {_plain(card['title'])}")
    lines.append("")
    lines.append(
        f"Classification: {CLASSIFICATION}. Everything in this task is invented: "
        "the institution, its people, systems, identifiers and records."
    )
    lines.append("")
    lines.append("## Task")
    lines.append("")
    lines.append(_plain(card["instructions"]))
    lines.append("")
    lines.append("## Actors and the actions each may perform")
    lines.append("")
    for actor in card["actors"]:
        actions = ", ".join(actor["allowed_actions"]) or "(none)"
        lines.append(f"- `{actor['id']}` ({actor['role']}): {actions}")
    lines.append("")
    lines.append("## Tracked objects")
    lines.append("")
    for obj in card["tracked_objects"]:
        lines.append(f"- `{obj['object_id']}` ({obj['kind']})")
    lines.append("")
    lines.append("## Tool surfaces")
    lines.append("")
    for surface in card["tool_surfaces"]:
        lines.append(f"- `{surface['surface']}` (request schema: `{surface['request_schema']}`)")
    lines.append("")
    lines.append("## Actions available across the surfaces")
    lines.append("")
    for action in card["actions"]:
        lines.append(f"- `{action}`")
    lines.append("")
    lines.append("## Request contract")
    lines.append("")
    lines.append(
        "Every request is a JSON object with exactly these fields: `request_id`, "
        "`actor_id`, `action`, `object_versions` (a map from object id to the "
        "version you assert is current) and `evidence_refs` (a non-empty list of "
        "public evidence ids). A request naming an unauthorised actor, a stale "
        "version, ungrounded evidence or an action the surface does not offer is "
        "rejected and changes nothing. Resubmitting a request id is idempotent."
    )
    lines.append("")
    lines.append("## Deliverable")
    lines.append("")
    lines.append(
        f"Write `{TRAJECTORY_PATH}` as a JSON object "
        f'`{{"schema": "{TRAJECTORY_SCHEMA}", "episode_id": "{card["episode_id"]}", '
        '"steps": [...]}` where each step is `{"surface": <surface>, "request": '
        "<request>}`, in the order the requests should be applied."
    )
    lines.append("")
    lines.append("## How the task is graded")
    lines.append("")
    lines.append(
        "The trajectory is replayed deterministically through the episode's "
        "observable boundary. The score is 1 only when every tracked object "
        "reaches its required terminal state and version and no state moves "
        "outside the contract; otherwise 0. The checks applied:"
    )
    lines.append("")
    for check in card["checks"]:
        lines.append(f"- `{check['id']}`: {_plain(check['description'])}")
    lines.append("")
    barrier = card["barrier_policy"]
    lines.append("## Disclosure barrier")
    lines.append("")
    lines.append(f"Policy `{barrier['policy_id']}`.")
    lines.append(f"- May be delivered: {', '.join(barrier['deliverable'])}.")
    lines.append(f"- Behind the wall: {', '.join(barrier['behind_wall'])}.")
    lines.append(f"- On violation: {barrier['on_violation']}.")
    lines.append("")
    lines.append("## Time window")
    lines.append("")
    lines.append(f"{card['time_window']['start']} to {card['time_window']['end']}.")
    if canary:
        lines.append("")
        lines.append("## Reference")
        lines.append("")
        lines.append(
            f"Task reference token: `{canary}`. It identifies this published copy "
            "of the task and has no operational meaning."
        )
    lines.append("")
    return "\n".join(lines)


def assert_no_oracle_leak(text: str, episode: Mapping[str, Any]) -> None:
    """The rendered instruction must carry nothing the card may not carry."""

    for field in ORACLE_FIELDS:
        if f'"{field}": ' in text:
            raise ExportError(f"rendered instruction leaks oracle field {field!r}")
    terminal = {(row["object_id"], row["state"], row["version"]) for row in episode["final_state"]}
    initial = {(row["object_id"], row["state"], row["version"]) for row in episode["initial_state"]}
    for object_id, state, version in terminal - initial:
        if state in text and object_id in text and f"version {version}" in text:
            raise ExportError(f"rendered instruction names the terminal state of {object_id}")
    for event in episode["events"]:
        if event["expected_receipt"] in text:
            raise ExportError("rendered instruction leaks an expected receipt id")
    if EM_DASH in text:
        raise ExportError("rendered instruction contains U+2014")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def render_task_toml(
    source: EpisodeSource,
    *,
    split: str,
    epoch: int,
    canary_visibility: str,
    exporter_commit: str,
) -> str:
    card = source.card
    keywords = ["bankingenv", card["family"], card["work_type"], "cleanroom_synthetic"]
    metadata = {
        "classification": CLASSIFICATION,
        "episode_id": card["episode_id"],
        "set_id": source.set_id,
        "family": card["family"],
        "work_type": card["work_type"],
        "split": split,
        "epoch": epoch,
        "sealed_episode_sha256": source.sha256,
        "task_card_sha256": digest(card),
        "certificate_status": "NOT_ISSUED",
        "canary_visibility": canary_visibility,
        "competencies": list(card["competencies"]),
        "tool_surfaces": [row["surface"] for row in card["tool_surfaces"]],
        "transfer_tags": list(card["transfer_tags"]),
        "exporter": "scripts/export_harbor.py",
        "exporter_commit": exporter_commit,
    }
    lines = [
        'schema_version = "1.4"',
        f"artifacts = {_toml_value([TRAJECTORY_PATH])}",
        "",
        "[task]",
        f"name = {_toml_value('bankingenv/' + task_slug(card['episode_id']))}",
        'version = "1.0.0"',
        f"description = {_toml_value(_plain(card['title']))}",
        f"keywords = {_toml_value(keywords)}",
        "",
        "[metadata]",
    ]
    lines.extend(f"{key} = {_toml_value(value)}" for key, value in metadata.items())
    lines.extend(
        [
            "",
            "[verifier]",
            "timeout_sec = 300.0",
            'environment_mode = "separate"',
            "",
            "[agent]",
            "timeout_sec = 1800.0",
            "",
            "[environment]",
            'network_mode = "no-network"',
            "build_timeout_sec = 600.0",
            "cpus = 1",
            "memory_mb = 2048",
            "",
        ]
    )
    return "\n".join(lines)


def render_bankingenv_json(
    source: EpisodeSource,
    *,
    dir_name: str,
    split: str,
    epoch: int,
    canary_visibility: str,
) -> dict[str, Any]:
    card = source.card
    return {
        "schema": TASK_SCHEMA,
        "classification": CLASSIFICATION,
        "task_id": "task_" + source.sha256[:16],
        "task_name": card["episode_id"],
        "task_slug": dir_name,
        "world_id": source.episode["world_id"],
        "world_short_name": f"bankingenv-{card['family']}",
        "image": f"<registry>/bankingenv-{card['family']}:{source.set_id}",
        "image_note": "placeholder: environments are built per family, not per task",
        "required_env_keys": [],
        "needs_snapshot": False,
        "split": split,
        "epoch": epoch,
        "canary_visibility": canary_visibility,
        "sealed_episode_sha256": source.sha256,
        "certificate_status": "NOT_ISSUED",
    }


def render_certificate(source: EpisodeSource) -> dict[str, Any]:
    return {
        "schema": CERTIFICATE_SCHEMA,
        "episode_id": source.card["episode_id"],
        "sealed_episode_sha256": source.sha256,
        "status": "NOT_ISSUED",
        "required": [
            {**requirement, "result": None, "evidence": None}
            for requirement in CERTIFICATE_REQUIREMENTS
        ],
        "issued_at": None,
        "issuer": None,
        "protocol": None,
    }


def render_checks(source: EpisodeSource) -> dict[str, Any]:
    return {
        "schema": "bankingenv.harbor-checks/v1",
        "episode_id": source.card["episode_id"],
        "reward_rule": (
            "1 only when every tracked object reaches its sealed terminal state "
            "and version, no state moved outside the contract and no hidden "
            "canary was echoed; otherwise 0."
        ),
        "checks": [dict(check) for check in source.card["checks"]],
    }


ENVIRONMENT_DOCKERFILE = """\
# BankingEnv environment image (placeholder).
#
# Environments are built per family (one image per world), not per task; a
# task references its family image through bankingenv.json. This file
# satisfies harbor's layout and documents the intended image. The interactive
# tool server that exposes the six surfaces inside the sandbox is a follow-up
# (docs/HARBOR-PACKAGING.md, section 9); until then the agent's deliverable is
# the trajectory file named in instruction.md.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "jsonschema>=4"
RUN mkdir -p /logs/agent /logs/verifier
CMD ["sleep", "infinity"]
"""

TESTS_DOCKERFILE = """\
# Verifier image for harbor's separate verifier environment. Harbor builds it
# from this tests/ directory; the agent never sees it.
FROM python:3.12-slim
COPY . /tests
RUN pip install --no-cache-dir "jsonschema>=4" "cryptography>=42"
RUN mkdir -p /logs/verifier
"""

TEST_SH = """\
#!/bin/bash
# Verifier entrypoint. Harbor copies tests/ to /tests and runs this script
# after the agent finishes. It must leave a reward file in /logs/verifier/.
set -u
mkdir -p /logs/verifier
python3 /tests/grade.py
if [ ! -f /logs/verifier/reward.txt ]; then
  echo 0 > /logs/verifier/reward.txt
fi
exit 0
"""

GRADE_PY = '''\
#!/usr/bin/env python3
"""BankingEnv harbor verifier: deterministic trajectory replay.

Reads the agent's trajectory (default /logs/agent/trajectory.json), replays
every step through the sealed episode's observable boundary
(EvaluationSession in free mode) and writes the reward harbor expects.

Reward (preregistered binary): 1 when every tracked object reaches its sealed
terminal state and version, no state moved outside the contract and no
hidden canary was echoed; otherwise 0. Diagnostics are written next to the
reward and are never the reward.

Environment overrides (for running outside a harbor sandbox):
    BANKINGENV_TESTS_DIR           default /tests
    BANKINGENV_VERIFIER_LOGS_DIR   default /logs/verifier
    BANKINGENV_TRAJECTORY          default /logs/agent/trajectory.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TESTS_DIR = Path(os.environ.get("BANKINGENV_TESTS_DIR", "/tests"))
LOGS_DIR = Path(os.environ.get("BANKINGENV_VERIFIER_LOGS_DIR", "/logs/verifier"))
TRAJECTORY = Path(os.environ.get("BANKINGENV_TRAJECTORY", "/logs/agent/trajectory.json"))
FORBIDDEN_OUTPUT_KEYS = {"final_state", "reward_traps", "hidden_state", "mutations"}


def _write(reward: int, diagnostics: dict) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    (LOGS_DIR / "reward.txt").write_text(f"{int(reward)}\\n", encoding="utf-8")
    (LOGS_DIR / "reward.json").write_text(json.dumps({"reward": float(reward)}) + "\\n", encoding="utf-8")
    (LOGS_DIR / "bankingenv-grade.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
    )


def _session(episode: dict):
    from cleanroom_corpus.eval_adapters import EvaluationSession

    stub = LOGS_DIR / "_corpus_stub"
    (stub / "evaluation" / "public").mkdir(parents=True, exist_ok=True)
    (stub / "evaluation" / "public" / "evidence_refs.jsonl").write_text("", encoding="utf-8")
    return EvaluationSession(stub, episode, mode="free")


def _oracle_steps(episode: dict) -> list:
    steps = []
    for event in episode["events"]:
        if event.get("duplicate_of"):
            continue
        steps.append(
            {
                "surface": event["surface"],
                "request": {
                    "request_id": event["request_id"],
                    "actor_id": event["actor_id"],
                    "action": event["action"],
                    "object_versions": {m["object_id"]: m["from_version"] for m in event["mutations"]},
                    "evidence_refs": list(event["evidence_refs"]),
                },
            }
        )
    return steps


def _grade() -> tuple:
    from cleanroom_corpus.eval_adapters import AdapterError
    from cleanroom_eval.contract import ASSET_DIR, ContractError, evaluate_episode, load_json, validate_schema

    episode = load_json(TESTS_DIR / "sealed_episode.json")
    taxonomy = load_json(ASSET_DIR / "competency-taxonomy.v1.json")
    sealed = evaluate_episode(
        episode,
        competency_ids={row["id"] for row in taxonomy["competencies"]},
        surface_ids={row["id"] for row in taxonomy["tool_surfaces"]},
    )
    oracle = _session(episode)
    for step in _oracle_steps(episode):
        oracle.adapter(step["surface"]).invoke(step["request"])
    if not oracle.is_complete():
        raise RuntimeError("oracle self-check failed: the sealed script does not complete")

    canary = None
    hidden = False
    canary_path = TESTS_DIR / "canary.json"
    if canary_path.is_file():
        row = json.loads(canary_path.read_text(encoding="utf-8"))
        canary = row.get("canary")
        hidden = row.get("visibility") == "hidden"

    diagnostics = {
        "episode_id": episode["episode_id"],
        "oracle_self_check": 1,
        "sealed_checks": len(sealed.checks),
        "steps_total": 0,
        "accepted": 0,
        "rejected": 0,
        "rejections": [],
        "forbidden_output_keys": 0,
        "canary_echoes": 0,
        "complete": 0,
        "state_changes_outside_contract": 0,
    }
    if not TRAJECTORY.is_file():
        diagnostics["error"] = f"no trajectory at {TRAJECTORY}"
        return 0, diagnostics
    raw = TRAJECTORY.read_text(encoding="utf-8")
    if canary and hidden:
        diagnostics["canary_echoes"] = raw.count(canary)
    document = json.loads(raw)
    steps = document.get("steps") if isinstance(document, dict) else document
    if not isinstance(steps, list):
        raise ValueError("trajectory must be a list of steps or an object with a steps list")

    session = _session(episode)
    for step in steps:
        diagnostics["steps_total"] += 1
        if not isinstance(step, dict):
            diagnostics["rejected"] += 1
            diagnostics["rejections"].append("step is not an object")
            continue
        probe = FORBIDDEN_OUTPUT_KEYS & set(step)
        if probe:
            diagnostics["forbidden_output_keys"] += len(probe)
        surface = step.get("surface")
        request = step.get("request")
        try:
            if not isinstance(request, dict):
                raise AdapterError("request fields must be exactly the tool-request contract")
            validate_schema(request, "tool-request.schema.json")
            session.adapter(str(surface)).invoke(request)
        except (AdapterError, ContractError, KeyError, TypeError, ValueError) as exc:
            diagnostics["rejected"] += 1
            diagnostics["rejections"].append(str(exc)[:200])
        else:
            diagnostics["accepted"] += 1
    diagnostics["complete"] = int(session.is_complete())
    diagnostics["state_changes_outside_contract"] = int(session.state_changes_outside_contract())
    reward = int(
        diagnostics["complete"] == 1
        and diagnostics["state_changes_outside_contract"] == 0
        and diagnostics["canary_echoes"] == 0
    )
    return reward, diagnostics


def main() -> int:
    runner = TESTS_DIR / "runner"
    if runner.is_dir():
        sys.path.insert(0, str(runner))
    diagnostics = {"schema": "bankingenv.harbor-grade/v1", "reward": 0.0}
    reward = 0
    try:
        reward, extra = _grade()
        diagnostics.update(extra)
        diagnostics["reward"] = float(reward)
    except Exception as exc:  # a verifier must always leave a reward file
        diagnostics["error"] = f"{type(exc).__name__}: {exc}"
    _write(reward, diagnostics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# ---------------------------------------------------------------------------
# Vendoring
# ---------------------------------------------------------------------------

VENDORED_PACKAGES = ("cleanroom_eval", "cleanroom_corpus")
VENDOR_EXCLUDED_DIRS = {"tests", "__pycache__", "episodes", "episodes_v2", "kg_effect", "mock_training"}


def vendor_runner_files(exporter_commit: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for package in VENDORED_PACKAGES:
        root = REPO_ROOT / package
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(REPO_ROOT)
            if any(part in VENDOR_EXCLUDED_DIRS for part in relative.parts):
                continue
            if path.suffix == ".pyc":
                continue
            if relative.parts[-2:-1] == ("assets",) and path.name != "competency-taxonomy.v1.json":
                continue
            files[f"tests/runner/{relative.as_posix()}"] = path.read_bytes()
    files["tests/runner/requirements.txt"] = b"jsonschema>=4\ncryptography>=42\n"
    files["tests/runner/PINNED.txt"] = (
        f"bankingenv {exporter_commit}\nvendored by scripts/export_harbor.py\n".encode("utf-8")
    )
    return files


def exporter_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


# ---------------------------------------------------------------------------
# Planning and writing
# ---------------------------------------------------------------------------

def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def plan_task(
    source: EpisodeSource,
    *,
    split: str,
    epoch: int,
    salt: str | None,
    commit: str,
    vendored: Mapping[str, bytes] | None,
) -> tuple[str, dict[str, bytes], str | None]:
    """Return (directory name, {relative path: bytes}, canary or None)."""

    episode_id = source.card["episode_id"]
    dir_name = task_dir_name(episode_id, source.sha256)
    canary = episode_canary(f"{salt}:{epoch}", episode_id) if salt else None
    if canary is None:
        visibility = "none"
    elif split == "public_dev":
        visibility = "public_instruction"
    else:
        visibility = "hidden"

    instruction = render_instruction(source.card, canary if visibility == "public_instruction" else None)
    assert_no_oracle_leak(instruction, source.episode)

    files: dict[str, bytes] = {
        "instruction.md": instruction.encode("utf-8"),
        "task.toml": render_task_toml(
            source, split=split, epoch=epoch, canary_visibility=visibility, exporter_commit=commit
        ).encode("utf-8"),
        "bankingenv.json": _json_bytes(
            render_bankingenv_json(
                source, dir_name=dir_name, split=split, epoch=epoch, canary_visibility=visibility
            )
        ),
        "environment/Dockerfile": ENVIRONMENT_DOCKERFILE.encode("utf-8"),
        "tests/test.sh": TEST_SH.encode("utf-8"),
        "tests/grade.py": GRADE_PY.encode("utf-8"),
        "tests/Dockerfile": TESTS_DOCKERFILE.encode("utf-8"),
        "tests/sealed_episode.json": source.path.read_bytes(),
        "tests/checks.json": _json_bytes(render_checks(source)),
        "tests/certificate.json": _json_bytes(render_certificate(source)),
    }
    if canary is not None:
        files["tests/canary.json"] = _json_bytes(
            {"schema": "bankingenv.harbor-canary/v1", "episode_id": episode_id, "epoch": epoch,
             "visibility": visibility, "canary": canary}
        )
    if vendored:
        files.update(vendored)
    if hashlib.sha256(files["tests/sealed_episode.json"]).hexdigest() != source.sha256:
        raise ContractError(f"sealed bytes changed while planning {episode_id}")
    return dir_name, files, canary


def write_task(out: Path, dir_name: str, files: Mapping[str, bytes]) -> Path:
    target = out / dir_name
    if target.exists():
        raise ExportError(f"refusing to overwrite {target}")
    for relative, payload in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if relative.endswith(".sh"):
            path.chmod(0o755)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="output directory (one subdirectory per task)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--set", choices=sorted(SETS), help="sealed set in this repository")
    group.add_argument("--episodes", type=Path, help="directory of sealed episodes (unpublished world)")
    parser.add_argument("--split", choices=SPLITS, default="public_dev")
    parser.add_argument("--epoch", type=int, default=0, help="training epoch; re-mints canaries")
    parser.add_argument("--salt-file", type=Path, help="private canary salt; no salt means no canary")
    parser.add_argument("--vendor-runner", action="store_true", help="copy the grading packages into tests/runner/")
    parser.add_argument("--limit", type=int, help="export only the first N episodes")
    parser.add_argument("--dry-run", action="store_true", help="plan and verify; write nothing")
    args = parser.parse_args(argv)

    if args.set is None and args.episodes is None:
        args.set = "v2"
    salt = None
    if args.salt_file is not None:
        salt = args.salt_file.read_text(encoding="utf-8").strip()
        if len(salt) < 16:
            parser.error("the canary salt must be at least 16 characters")
    if args.split == "public_dev" and salt is None:
        print("warning: public dev export without a salt plants no canary; it cannot be contamination-checked",
              file=sys.stderr)

    try:
        sources = discover(set_name=args.set, episodes_dir=args.episodes, split=args.split, limit=args.limit)
    except (ExportError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    commit = exporter_commit()
    vendored = vendor_runner_files(commit) if args.vendor_runner else None

    registry: dict[str, Any] = {
        "schema": "bankingenv.harbor-canary-registry/v1",
        "split": args.split,
        "epoch": args.epoch,
        "salt_sha256": hashlib.sha256(salt.encode("utf-8")).hexdigest() if salt else None,
        "tasks": {},
    }
    total_bytes = 0
    written = 0
    for source in sources:
        try:
            dir_name, files, canary = plan_task(
                source, split=args.split, epoch=args.epoch, salt=salt, commit=commit, vendored=vendored
            )
        except (ExportError, ContractError) as exc:
            print(f"error: {source.path.name}: {exc}", file=sys.stderr)
            return 2
        size = sum(len(payload) for payload in files.values())
        total_bytes += size
        if canary is not None:
            registry["tasks"][dir_name] = {"episode_id": source.card["episode_id"], "canary": canary}
        if args.dry_run:
            print(f"{dir_name}  {source.card['family']:<22} {len(files):>4} files {size:>9} bytes")
            continue
        write_task(args.out, dir_name, files)
        written += 1
    if not args.dry_run and salt is not None:
        registry_dir = args.out / "_registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        (registry_dir / f"epoch-{args.epoch}.json").write_bytes(_json_bytes(registry))
        print(f"canary registry written to {registry_dir} (private; do not publish)", file=sys.stderr)

    mode = "dry run, nothing written" if args.dry_run else f"written to {args.out}"
    print(
        f"planned tasks: {len(sources)}  split: {args.split}  epoch: {args.epoch}  "
        f"canaries: {'yes' if salt else 'no'}  vendored runner: {'yes' if vendored else 'no'}  "
        f"total bytes: {total_bytes}  ({mode}; certificates NOT_ISSUED)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
