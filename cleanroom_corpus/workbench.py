"""Prepare the generated raw surfaces for the existing KG ingestion pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


_BUNDLE_SCHEMA = "cleanroom.workbench-text-bundle/v1"
_BUNDLE_DERIVATION = "manifest-committed-raw-byte-flattening/v1"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _committed_raw_bundle(corpus_root: Path) -> tuple[Path, dict[str, Any], bytes, list[str]]:
    """Return the deterministic raw flattening after verifying its source ledger."""

    root = corpus_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read synthetic corpus manifest: {manifest_path}") from exc

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list):
        raise ValueError("synthetic corpus manifest has no file ledger")
    source_corpus_sha256 = manifest.get("corpus_sha256")
    calculated_corpus_sha256 = _sha256(_canonical_json(file_rows).encode("utf-8"))
    if source_corpus_sha256 != calculated_corpus_sha256:
        raise ValueError(
            "synthetic corpus manifest has a stale corpus digest: "
            f"expected {source_corpus_sha256!r}, calculated "
            f"{calculated_corpus_sha256!r}"
        )

    seen_paths: set[str] = set()
    raw_rows: list[dict[str, Any]] = []
    for row in file_rows:
        if not isinstance(row, dict):
            raise ValueError("synthetic corpus manifest contains a non-object file row")
        relative_path = row.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("synthetic corpus manifest contains an invalid file path")
        if relative_path in seen_paths:
            raise ValueError(f"synthetic corpus manifest repeats file: {relative_path}")
        seen_paths.add(relative_path)
        if relative_path.startswith("raw/"):
            raw_rows.append(row)

    if not raw_rows:
        raise ValueError("synthetic corpus manifest contains no raw artefacts")

    committed_raw_paths = {str(row["path"]) for row in raw_rows}
    actual_raw_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "raw").rglob("*")
        if path.is_file()
    }
    if committed_raw_paths != actual_raw_paths:
        missing = sorted(committed_raw_paths - actual_raw_paths)
        extra = sorted(actual_raw_paths - committed_raw_paths)
        raise ValueError(
            f"raw file set no longer matches manifest: missing={missing}, extra={extra}"
        )

    chunks: list[bytes] = []
    surfaces: set[str] = set()
    for row in sorted(raw_rows, key=lambda item: str(item["path"])):
        relative_path = str(row["path"])
        source = (root / relative_path).resolve()
        if root not in source.parents:
            raise ValueError(f"raw source escapes corpus root: {relative_path}")
        try:
            payload = source.read_bytes()
            expected_bytes = int(row["bytes"])
            expected_sha256 = str(row["sha256"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid committed raw source: {relative_path}") from exc
        digest = _sha256(payload)
        if len(payload) != expected_bytes or digest != expected_sha256:
            raise ValueError(f"raw source no longer matches manifest: {relative_path}")
        path_parts = Path(relative_path).parts
        if len(path_parts) < 3 or path_parts[0] != "raw":
            raise ValueError(f"invalid raw source path: {relative_path}")
        surfaces.add(path_parts[1])
        header = (
            f"\n===== SYNTHETIC SOURCE {relative_path} "
            f"BYTES={len(payload)} SHA256={digest} =====\n"
        ).encode("utf-8")
        chunks.extend((header, payload, b"\n===== END SYNTHETIC SOURCE =====\n"))

    return root, manifest, b"".join(chunks), sorted(surfaces)


def _bundle_report(
    *,
    root: Path,
    output: Path,
    manifest: dict[str, Any],
    bundle: bytes,
    surfaces: list[str],
) -> dict[str, Any]:
    return {
        "schema": _BUNDLE_SCHEMA,
        "classification": "SYNTHETIC_CLEAN_ROOM",
        "status": "PASS",
        "derivation": _BUNDLE_DERIVATION,
        "corpus_root": str(root),
        "output_path": str(output),
        "source_corpus_sha256": manifest["corpus_sha256"],
        "bundle_sha256": _sha256(bundle),
        "bytes": len(bundle),
        "artefacts": sum(
            str(row.get("path", "")).startswith("raw/")
            for row in manifest["files"]
        ),
        "surfaces": surfaces,
    }


def inspect_text_bundle(corpus_root: Path, bundle_path: Path) -> dict[str, Any]:
    """Verify a derived workbench bundle without writing or trusting it.

    The source manifest remains non-circular: the derived bundle is not added to
    its file ledger.  Instead, this helper revalidates the manifest's corpus
    digest and committed raw file set, reconstructs the deterministic flattening,
    and requires the supplied bundle to be byte-for-byte identical.
    """

    root, manifest, expected_bundle, surfaces = _committed_raw_bundle(corpus_root)
    output = bundle_path.expanduser().resolve()
    try:
        observed_bundle = output.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read workbench text bundle: {output}") from exc
    if observed_bundle != expected_bundle:
        raise ValueError(
            "workbench text bundle does not match deterministic raw flattening: "
            f"expected bytes={len(expected_bundle)} "
            f"sha256={_sha256(expected_bundle)}, "
            f"observed bytes={len(observed_bundle)} "
            f"sha256={_sha256(observed_bundle)}"
        )
    return _bundle_report(
        root=root,
        output=output,
        manifest=manifest,
        bundle=observed_bundle,
        surfaces=surfaces,
    )


def build_text_bundle(corpus_root: Path, output_path: Path) -> dict[str, Any]:
    """Bundle every raw text artefact byte-for-byte into one ingestible stream.

    Headers carry the original path, byte count and digest.  The payload length
    makes the bundle reversible even if a source contains delimiter-like text.
    Hidden truth, controls and evaluation answers are deliberately excluded.
    """

    root, manifest, bundle, surfaces = _committed_raw_bundle(corpus_root)
    output = output_path.expanduser().resolve()
    raw_root = (root / "raw").resolve()
    if output == root / "manifest.json" or raw_root == output or raw_root in output.parents:
        raise ValueError("workbench text bundle must not overwrite the source corpus ledger")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bundle)
    return _bundle_report(
        root=root,
        output=output,
        manifest=manifest,
        bundle=bundle,
        surfaces=surfaces,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build_text_bundle(args.corpus_root, args.output_path),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
