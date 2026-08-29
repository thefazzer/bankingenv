"""Durable headshot identities for the institution-scale Ficta Cast."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = "ficta.cast-headshot-jobs/v1"
CLASSIFIER_REVISION = "282016c123c81de48f4524aacd5a1728ecc330c4"
STYLE_REVISION = "ficta-passport-business-cool-wash/v3"
AGE_GROUP_BY_SENIORITY = {
    "Managing Director": "50s",
    "Director": "40s",
    "Vice President": "30s",
    "Associate": "late 20s",
    "Analyst": "20s",
}
FEMALE_GIVEN_NAMES = {
    "Aveline", "Cerys", "Elara", "Ginevra", "Isolde", "Kerensa",
    "Maris", "Petra", "Rhea", "Tamsin",
}
MALE_GIVEN_NAMES = {
    "Bram", "Dorian", "Florian", "Hadrian", "Jasper", "Leander",
    "Nerys", "Orson", "Quentin", "Soren",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_cast(world_path: Path, classifier_registry: Path) -> list[dict[str, Any]]:
    """Read the authoritative Cast roster, never a parallel sample fixture."""

    world = json.loads(world_path.read_text(encoding="utf-8"))
    people = [
        entity for entity in world.get("entities", [])
        if entity.get("kind") == "person" and entity.get("synthetic") is True
    ]
    people.sort(key=lambda row: str((row.get("attributes") or {}).get("employee_code")))
    if len(people) != 200:
        raise ValueError(f"expected 200 authoritative Cast people, found {len(people)}")
    with sqlite3.connect(classifier_registry) as connection:
        pins = {
            str(row[0]): {
                "label": str(row[1]), "confidence": float(row[2]),
                "provider_revision": str(row[3]), "model": str(row[4]),
            }
            for row in connection.execute(
                "SELECT surname_key,label,confidence,provider_revision,model FROM surname_pins"
            )
        }
    jobs: list[dict[str, Any]] = []
    for person in people:
        attributes = person["attributes"]
        parts = str(person["canonical_label"]).removeprefix("Ficta ").split()
        if len(parts) != 2:
            raise ValueError(f"Cast name is not Given Surname: {person['canonical_label']}")
        given_name, surname = parts
        if given_name in FEMALE_GIVEN_NAMES:
            sex = "female"
        elif given_name in MALE_GIVEN_NAMES:
            sex = "male"
        else:
            raise ValueError(f"Cast sex mapping is missing for {given_name}")
        pin = pins.get(surname.casefold())
        if not pin or pin["provider_revision"] != CLASSIFIER_REVISION:
            raise ValueError(f"missing pinned surname classification for {surname}")
        seniority = str(attributes["seniority"])
        profile = {
            "key": str(person["entity_id"]),
            "employee_code": str(attributes["employee_code"]),
            "display_name": str(person["canonical_label"]),
            "given_name": given_name,
            "surname": surname,
            "sex": sex,
            "ethnicity": pin["label"],
            "ethnicity_classifier": pin,
            "title": str(attributes["title"]),
            "team": str(attributes["team"]),
            "seniority": seniority,
            "seniority_band": int(attributes["seniority_band"]),
            "age_group": AGE_GROUP_BY_SENIORITY[seniority],
            "age_group_source": "synthetic_seniority_proxy/v1",
            "style_revision": STYLE_REVISION,
        }
        profile["profile_signature"] = hashlib.sha256(_canonical(profile).encode()).hexdigest()
        jobs.append(profile)
    if len({job["key"] for job in jobs}) != len(jobs):
        raise ValueError("Cast contains duplicate person entity IDs")
    return jobs


def publish(jobs: list[dict[str, Any]], images: Path, store: Path) -> dict[str, Any]:
    """Publish one verified immutable asset and current binding per Cast person."""

    signatures = json.loads((images / ".headshot-signatures.json").read_text(encoding="utf-8"))
    assets_root = store / "assets" / "sha256"
    bindings: dict[str, dict[str, Any]] = {}
    for job in jobs:
        source = images / f"{job['key']}.png"
        if signatures.get(job["key"]) != job["profile_signature"] or not source.is_file():
            raise ValueError(f"portrait is missing or stale for {job['display_name']}")
        payload = source.read_bytes()
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"portrait is not a PNG for {job['display_name']}")
        digest = hashlib.sha256(payload).hexdigest()
        relative = Path("assets") / "sha256" / digest[:2] / f"{digest}.png"
        destination = store / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"published portrait digest mismatch for {job['display_name']}")
        binding = {
            **job,
            "asset_id": f"sha256:{digest}",
            "sha256": digest,
            "relative_path": relative.as_posix(),
            "media_type": "image/png",
        }
        bindings[job["key"]] = binding
    manifest = {
        "schema": "ficta.cast-headshot-registry/v1",
        "release_build": "bankingenv-v1",
        "people": len(bindings),
        "bindings": bindings,
        "employee_code_index": {
            row["employee_code"]: key for key, row in bindings.items()
        },
    }
    store.mkdir(parents=True, exist_ok=True)
    candidate = store / ".manifest.tmp"
    candidate.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    candidate.replace(store / "manifest.json")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("world", type=Path)
    parser.add_argument("classifier_registry", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    jobs = load_cast(args.world.resolve(), args.classifier_registry.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"schema": SCHEMA, "people": jobs}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result: dict[str, Any] = {"output": str(args.output.resolve()), "people": len(jobs)}
    if bool(args.images) != bool(args.store):
        raise ValueError("--images and --store must be supplied together")
    if args.images and args.store:
        manifest = publish(jobs, args.images.resolve(), args.store.resolve())
        result.update({"published": manifest["people"], "release_build": manifest["release_build"]})
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
