"""The harbor exporter writes the documented layout, leaks no oracle field,
keeps sealed bytes byte-identical, and its verifier grades by replay."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "export_harbor.py"
ASSET_DIR = REPO_ROOT / "cleanroom_eval" / "assets"
EXPECTED_FILES = {
    "instruction.md",
    "task.toml",
    "bankingenv.json",
    "environment/Dockerfile",
    "tests/test.sh",
    "tests/grade.py",
    "tests/Dockerfile",
    "tests/sealed_episode.json",
    "tests/checks.json",
    "tests/certificate.json",
}


def _run(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == expect, result.stdout + result.stderr
    return result


def _salt(tmp_path: Path) -> Path:
    path = tmp_path / "canary.salt"
    path.write_text("test-salt-0123456789abcdef", encoding="utf-8")
    return path


def _task_dirs(out: Path) -> list[Path]:
    return sorted(p for p in out.iterdir() if p.is_dir() and p.name.startswith("bankingenv-"))


def test_dry_run_plans_every_sealed_episode_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _run("--dry-run", "--set", "v2", "--out", str(out))
    assert "planned tasks: 40" in result.stdout
    assert "nothing written" in result.stdout
    assert not out.exists()


def test_export_layout_sealed_bytes_and_no_oracle_leak(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run("--set", "v2", "--limit", "3", "--epoch", "1", "--salt-file", str(_salt(tmp_path)), "--out", str(out))
    dirs = _task_dirs(out)
    assert len(dirs) == 3
    manifest = json.loads((ASSET_DIR / "sealed-set.manifest.v2.json").read_text(encoding="utf-8"))
    sha_by_path = {row["path"]: row["sha256"] for row in manifest["assets"]}
    registry = json.loads((out / "_registry" / "epoch-1.json").read_text(encoding="utf-8"))
    assert registry["salt_sha256"] is not None and "salt" not in json.dumps(registry["tasks"])

    for task_dir in dirs:
        present = {str(p.relative_to(task_dir)) for p in task_dir.rglob("*") if p.is_file()}
        assert EXPECTED_FILES <= present, present
        assert "solution/solve.sh" not in present

        sealed = json.loads((task_dir / "tests" / "sealed_episode.json").read_text(encoding="utf-8"))
        episode_name = sealed["episode_id"].removeprefix("episode_").removesuffix("_v1")
        asset_path = f"episodes_v2/{episode_name}.v1.json"
        sealed_sha = hashlib.sha256((task_dir / "tests" / "sealed_episode.json").read_bytes()).hexdigest()
        assert sealed_sha == sha_by_path[asset_path]

        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
        assert "\u2014" not in instruction
        for event in sealed["events"]:
            assert event["expected_receipt"] not in instruction
        for field in ("final_state", "reward_traps", "adversarial_mutations", "evidence_challenges"):
            assert f'"{field}": ' not in instruction
        initial = {(r["object_id"], r["state"], r["version"]) for r in sealed["initial_state"]}
        for object_id, state, version in {
            (r["object_id"], r["state"], r["version"]) for r in sealed["final_state"]
        } - initial:
            assert not (state in instruction and object_id in instruction and f"version {version}" in instruction)
        canary = registry["tasks"][task_dir.name]["canary"]
        assert canary.startswith("CANARY-") and canary in instruction

        config = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        for table in ("task", "metadata", "verifier", "agent", "environment"):
            assert table in config
        assert config["artifacts"] == ["/logs/agent/trajectory.json"]
        assert config["metadata"]["sealed_episode_sha256"] == sealed_sha
        assert config["metadata"]["certificate_status"] == "NOT_ISSUED"
        assert config["metadata"]["canary_visibility"] == "public_instruction"
        assert config["metadata"]["epoch"] == 1

        certificate = json.loads((task_dir / "tests" / "certificate.json").read_text(encoding="utf-8"))
        assert certificate["status"] == "NOT_ISSUED"
        assert {row["id"] for row in certificate["required"]} == {
            "unaided_fails", "naive_retrieval_fails", "oracle_passes"
        }
        assert all(row["result"] is None for row in certificate["required"])

        recipe = json.loads((task_dir / "bankingenv.json").read_text(encoding="utf-8"))
        assert recipe["needs_snapshot"] is False and recipe["required_env_keys"] == []
        assert recipe["world_id"] == sealed["world_id"]


def test_epoch_re_mint_changes_every_canary(tmp_path: Path) -> None:
    salt = _salt(tmp_path)
    first, second = tmp_path / "e1", tmp_path / "e2"
    _run("--set", "v2", "--limit", "2", "--epoch", "1", "--salt-file", str(salt), "--out", str(first))
    _run("--set", "v2", "--limit", "2", "--epoch", "2", "--salt-file", str(salt), "--out", str(second))
    one = json.loads((first / "_registry" / "epoch-1.json").read_text(encoding="utf-8"))["tasks"]
    two = json.loads((second / "_registry" / "epoch-2.json").read_text(encoding="utf-8"))["tasks"]
    assert set(one) == set(two) and len(one) == 2
    for name in one:
        assert one[name]["canary"] != two[name]["canary"]


def test_private_test_split_refuses_the_public_asset_tree(tmp_path: Path) -> None:
    result = _run("--set", "v2", "--split", "private_test", "--out", str(tmp_path / "out"), expect=2)
    assert "unpublished world" in result.stderr


def test_private_test_split_keeps_its_canary_hidden(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    for name in ("lifecycle_alpha_r2.v1.json", "lifecycle_alpha_r2.task.v1.json"):
        shutil.copy(ASSET_DIR / "episodes_v2" / name, world / name)
    out = tmp_path / "out"
    _run("--episodes", str(world), "--split", "private_test", "--salt-file", str(_salt(tmp_path)), "--out", str(out))
    (task_dir,) = _task_dirs(out)
    canary = json.loads((task_dir / "tests" / "canary.json").read_text(encoding="utf-8"))
    assert canary["visibility"] == "hidden"
    assert canary["canary"] not in (task_dir / "instruction.md").read_text(encoding="utf-8")
    config = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    assert config["metadata"]["split"] == "private_test"
    assert config["metadata"]["set_id"] == "external"


def _grade(task_dir: Path, logs: Path, trajectory: Path | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        {
            "BANKINGENV_TESTS_DIR": str(task_dir / "tests"),
            "BANKINGENV_VERIFIER_LOGS_DIR": str(logs),
            "BANKINGENV_TRAJECTORY": str(trajectory) if trajectory else str(logs / "missing.json"),
        }
    )
    result = subprocess.run(
        [sys.executable, str(task_dir / "tests" / "grade.py")],
        capture_output=True, text=True, cwd=logs, env=env, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    diagnostics = json.loads((logs / "bankingenv-grade.json").read_text(encoding="utf-8"))
    diagnostics["_reward_txt"] = (logs / "reward.txt").read_text(encoding="utf-8").strip()
    diagnostics["_reward_json"] = json.loads((logs / "reward.json").read_text(encoding="utf-8"))
    return diagnostics


def test_vendored_verifier_replays_the_sealed_script_to_one_and_nothing_to_zero(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run("--set", "v2", "--limit", "1", "--vendor-runner", "--out", str(out))
    (task_dir,) = _task_dirs(out)
    assert (task_dir / "tests" / "runner" / "PINNED.txt").is_file()
    assert (task_dir / "tests" / "runner" / "cleanroom_eval" / "assets" / "competency-taxonomy.v1.json").is_file()
    assert not (task_dir / "tests" / "runner" / "cleanroom_eval" / "assets" / "episodes_v2").exists()

    sealed = json.loads((task_dir / "tests" / "sealed_episode.json").read_text(encoding="utf-8"))
    steps = [
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
        for event in sealed["events"]
        if not event.get("duplicate_of")
    ]
    trajectory = tmp_path / "trajectory.json"
    trajectory.write_text(
        json.dumps({"schema": "bankingenv.trajectory/v1", "episode_id": sealed["episode_id"], "steps": steps}),
        encoding="utf-8",
    )

    logs_one = tmp_path / "logs-one"
    logs_one.mkdir()
    graded = _grade(task_dir, logs_one, trajectory)
    assert "error" not in graded, graded
    assert graded["_reward_txt"] == "1" and graded["_reward_json"] == {"reward": 1.0}
    assert graded["complete"] == 1 and graded["accepted"] == len(steps) and graded["rejected"] == 0

    stale = json.loads(trajectory.read_text(encoding="utf-8"))
    stale["steps"] = stale["steps"][:1]
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps(stale), encoding="utf-8")
    logs_partial = tmp_path / "logs-partial"
    logs_partial.mkdir()
    partial = _grade(task_dir, logs_partial, stale_path)
    assert partial["_reward_txt"] == "0" and partial["complete"] == 0

    logs_zero = tmp_path / "logs-zero"
    logs_zero.mkdir()
    empty = _grade(task_dir, logs_zero, None)
    assert empty["_reward_txt"] == "0" and empty["oracle_self_check"] == 1
