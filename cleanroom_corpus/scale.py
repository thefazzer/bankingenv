"""Fail-closed institution-scale acceptance checks for the synthetic corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


INSTITUTION_SCALE_MINIMUMS = {
    # The five reference profiles contain calibration-profile person counts (143
    # distinct IDs).  The clean-room world deliberately clears the larger
    # count without copying any names or source-derived values.
    "people": 200,
    "clients": 60,
    "accounts": 180,
    "trades": 1_200,
    "tickets": 300,
    "email_messages": 2_000,
    "fix_messages": 3_600,
    "operating_functions": 15,
}

PROJECTED_GRAPH_BINDING_SCHEMA = "cleanroom.projected-graph-binding/v1"
TEMPORAL_CLOCK_FIELDS = (
    "event_time",
    "occurred_at",
    "observed_at",
    "recorded_at",
    "effective_at",
)
IDENTITY_PREDICATES = frozenset({"entity_kind", "canonical_label", "alias"})
EVENT_CONTROL_PREDICATES = frozenset({"lifecycle_transition", "role_change"})


class InstitutionScaleError(ValueError):
    """Raised when a generated corpus is structurally too small for the workbench."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: object required")
            rows.append(row)
    return rows


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def projected_graph_binding(graph: dict[str, Any]) -> dict[str, Any]:
    """Bind the exact node/edge projection without self-referential metadata.

    Top-level release/catalog fields are deliberately excluded: the binding is
    for the projected graph objects, while the profile source manifest binds
    the complete serialized graph file.
    """

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("projected graph requires node and edge arrays")
    canonical_nodes = sorted(nodes, key=_canonical_bytes)
    canonical_edges = sorted(edges, key=_canonical_bytes)
    node_ids = sorted(str(node.get("id") or "") for node in canonical_nodes)
    edge_identities = sorted(
        (
            str(edge.get("from") or ""),
            str(edge.get("type") or ""),
            str(edge.get("to") or ""),
            tuple(sorted(map(
                str,
                (edge.get("properties") or {}).get("truth_atom_ids") or (),
            ))),
            tuple(sorted(map(
                str,
                (edge.get("properties") or {}).get("truth_relation_ids") or (),
            ))),
        )
        for edge in canonical_edges
    )
    return {
        "schema": PROJECTED_GRAPH_BINDING_SCHEMA,
        "sha256": _sha256_value({
            "nodes": canonical_nodes,
            "edges": canonical_edges,
        }),
        "node_count": len(canonical_nodes),
        "edge_count": len(canonical_edges),
        "node_ids_sha256": _sha256_value(node_ids),
        "edge_identities_sha256": _sha256_value(edge_identities),
    }


def _receipt_integer(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _temporal_projection_failures(
    graph: dict[str, Any],
    events: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Verify every lifecycle Event and EVENT_* edge preserves all clocks."""

    failures: list[str] = []
    expected = {
        str(event.get("event_id") or ""): event
        for event in events
        if event.get("event_id")
    }
    if len(expected) != len(events):
        failures.append("KG lifecycle clock projection: duplicate or missing event IDs")

    event_nodes: dict[str, list[dict[str, Any]]] = {}
    for node in graph.get("nodes") or []:
        properties = node.get("properties") or {}
        event_id = str(properties.get("event_id") or "")
        is_projected = (
            properties.get("synthetic_truth_projected") is True
            and str(node.get("kind") or node.get("group")).casefold() == "event"
        )
        if is_projected:
            event_nodes.setdefault(event_id, []).append(node)

    # Index the event topology once.  The prior audit searched the complete
    # graph edge array independently for every lifecycle event, which made the
    # fail-closed scale gate O(events * edges) on institution-scale profiles.
    # Grouping by source node preserves the exact comparison below while making
    # the audit linear in the projected topology.
    event_edges_by_source: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges") or []:
        if str(edge.get("type") or "").upper().startswith("EVENT_"):
            event_edges_by_source.setdefault(str(edge.get("from") or ""), []).append(edge)

    unexpected = sorted(set(event_nodes) - set(expected))
    if unexpected:
        failures.append(
            "KG lifecycle clock projection: unexpected projected event IDs "
            + ", ".join(unexpected[:8])
        )

    nodes_checked = 0
    edges_checked = 0
    for event_id, event in sorted(expected.items()):
        candidates = event_nodes.get(event_id) or []
        if len(candidates) != 1:
            failures.append(
                f"KG lifecycle clock projection {event_id}: "
                f"observed {len(candidates)} Event nodes, required 1"
            )
            continue
        node = candidates[0]
        nodes_checked += 1
        clocks = {field: event.get(field) for field in TEMPORAL_CLOCK_FIELDS}
        node_properties = node.get("properties") or {}
        if any(node_properties.get(field) != value for field, value in clocks.items()):
            failures.append(
                f"KG lifecycle clock projection {event_id}: Event clock mismatch"
            )
        if node_properties.get("native_temporal") != clocks:
            failures.append(
                f"KG lifecycle clock projection {event_id}: "
                "Event native_temporal mismatch"
            )

        event_edges = event_edges_by_source.get(str(node.get("id") or ""), [])
        observed_types = Counter(
            str(edge.get("type") or "").upper() for edge in event_edges
        )
        expected_types = Counter({
            "EVENT_SUBJECT": 1,
            "EVENT_OBJECT": len(event.get("object_ids") or []),
            "EVENT_ACTOR": 1,
        })
        if observed_types != expected_types:
            failures.append(
                f"KG lifecycle clock projection {event_id}: "
                f"EVENT_* edges {dict(observed_types)}, required {dict(expected_types)}"
            )
        for edge in event_edges:
            edges_checked += 1
            properties = edge.get("properties") or {}
            if any(properties.get(field) != value for field, value in clocks.items()):
                failures.append(
                    f"KG lifecycle clock projection {event_id}: "
                    f"{edge.get('type')} clock mismatch"
                )
            if properties.get("native_temporal") != clocks:
                failures.append(
                    f"KG lifecycle clock projection {event_id}: "
                    f"{edge.get('type')} native_temporal mismatch"
                )

    return failures, {
        "schema": "cleanroom.lifecycle-clock-projection/v1",
        "status": "PASS" if not failures else "FAIL",
        "clock_fields": list(TEMPORAL_CLOCK_FIELDS),
        "events_expected": len(expected),
        "event_nodes_checked": nodes_checked,
        "event_edges_checked": edges_checked,
    }


def verify_institution_scale(
    corpus_root: Path,
    *,
    graph_profile: Path | None = None,
) -> dict[str, Any]:
    """Verify source-world scale and, optionally, resulting KG recognition."""

    root = corpus_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest = _load_json(manifest_path)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    bindings: dict[str, Any] = {
        "corpus_manifest_sha256": manifest_sha256,
    }
    world = _load_json(root / "hidden" / "world.json")
    entities = world.get("entities") or []
    relations = world.get("relations") or []
    kinds = Counter(str(row.get("kind")) for row in entities)
    people = [row for row in entities if row.get("kind") == "person"]
    managers = {
        row["source_id"]
        for row in relations
        if row.get("predicate") == "reports_to"
    }
    required_person_fields = (
        "email",
        "employee_status",
        "role",
        "title",
        "team",
        "seniority",
        "start_date",
    )
    missing_person_fields = {
        field: sum(not person.get("attributes", {}).get(field) for person in people)
        for field in required_person_fields
    }
    email_artifacts = list((root / "raw" / "email").glob("*.eml"))
    primary_emails = int(
        (manifest.get("counts") or {}).get("email_messages", len(email_artifacts))
    )
    fix_messages = sum(
        path.read_text(encoding="utf-8").count("8=FIX.")
        for path in (root / "raw" / "fix").glob("*.fix")
    )
    functions = {
        person.get("attributes", {}).get("team")
        for person in people
        if person.get("attributes", {}).get("team")
    }
    observed = {
        "people": kinds["person"],
        "clients": kinds["client"],
        "accounts": kinds["account"],
        "trades": kinds["trade"],
        "tickets": kinds["case"],
        "email_messages": primary_emails,
        "fix_messages": fix_messages,
        "operating_functions": len(functions),
    }
    failures = [
        f"{name}: observed {observed[name]}, required {minimum}"
        for name, minimum in INSTITUTION_SCALE_MINIMUMS.items()
        if observed[name] < minimum
    ]
    if any(missing_person_fields.values()):
        failures.append(f"incomplete person fields: {missing_person_fields}")
    expected_managers = max(0, len(people) - 1)
    if len(managers) < expected_managers:
        failures.append(
            f"reporting lines: observed {len(managers)}, required {expected_managers}"
        )

    graph_result = None
    if graph_profile is not None:
        profile = graph_profile.expanduser().resolve()
        graph = _load_json(profile / "knowledge_graph.json")
        graph_nodes = graph.get("nodes", [])
        graph_kinds = Counter(
            str(node.get("kind") or node.get("group")).casefold()
            for node in graph_nodes
        )
        graph_people = [
            node for node in graph_nodes
            if str(node.get("kind") or node.get("group")).casefold() == "person"
        ]
        employment_path = profile / "employment_records.jsonl"
        employment = [
            json.loads(line)
            for line in employment_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        expected_names = set()
        for person in people:
            aliases = person.get("aliases") or []
            expected_names.add(str(
                aliases[2] if len(aliases) > 2 else person.get("canonical_label")
            ))
        expected_graph_people = {
            str(node.get("label")): node
            for node in graph_people
            if str(node.get("label")) in expected_names
        }
        graph_person_fields = (
            "employee_status",
            "employer",
            "title",
            "team",
            "seniority",
            "employment_start_date",
        )
        missing_graph_fields = {
            field: sum(
                (node.get("properties") or {}).get(field) in (None, "", "Unknown")
                for node in expected_graph_people.values()
            )
            for field in graph_person_fields
        }
        graph_type_minimums = {
            "person": INSTITUTION_SCALE_MINIMUMS["people"],
            "organization": INSTITUTION_SCALE_MINIMUMS["clients"],
            "account": INSTITUTION_SCALE_MINIMUMS["accounts"],
            "email": 200,
            "ticket": INSTITUTION_SCALE_MINIMUMS["tickets"],
            "team": INSTITUTION_SCALE_MINIMUMS["operating_functions"],
            "system": 6,
        }
        declared_counts = manifest.get("counts") or {}
        world_events = world.get("lifecycle_events")
        if not isinstance(world_events, list):
            failures.append("bundle lifecycle events: hidden world requires an array")
            world_events = []
        declared_truth_atoms = declared_counts.get("truth_atoms")
        truth_atoms_path = root / "hidden" / "truth_atoms.jsonl"
        truth_atom_rows: list[dict[str, Any]] | None = None
        if truth_atoms_path.is_file():
            try:
                truth_atom_rows = _load_jsonl(truth_atoms_path)
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                failures.append(f"bundle truth atoms: ledger is invalid: {exc}")
        actual_truth_atoms = (
            len(truth_atom_rows) if truth_atom_rows is not None else None
        )
        if actual_truth_atoms is None:
            failures.append("bundle truth atoms: hidden/truth_atoms.jsonl is missing")
        if (
            not isinstance(declared_truth_atoms, int)
            or isinstance(declared_truth_atoms, bool)
            or declared_truth_atoms < 0
        ):
            failures.append("bundle truth atoms: manifest count is missing or invalid")
        elif actual_truth_atoms is not None and declared_truth_atoms != actual_truth_atoms:
            failures.append(
                "bundle truth atoms: "
                f"manifest declares {declared_truth_atoms}, ledger contains {actual_truth_atoms}"
            )

        declared_lifecycle = declared_counts.get("lifecycle_events", 0)
        if (
            not isinstance(declared_lifecycle, int)
            or isinstance(declared_lifecycle, bool)
            or declared_lifecycle < 0
        ):
            failures.append("bundle lifecycle events: manifest count is invalid")
            declared_lifecycle = 0
        elif declared_lifecycle != len(world_events):
            failures.append(
                "bundle lifecycle events: "
                f"manifest declares {declared_lifecycle}, world contains {len(world_events)}"
            )

        def declared_nonnegative(name: str) -> int:
            value = declared_counts.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                failures.append(f"bundle {name}: manifest count is missing or invalid")
                return 0
            return value

        graph_projection_minimums = {
            "trade": max(
                INSTITUTION_SCALE_MINIMUMS["trades"],
                observed["trades"],
                declared_nonnegative("trades"),
            ),
            "fixmessage": max(
                INSTITUTION_SCALE_MINIMUMS["fix_messages"],
                observed["fix_messages"],
                declared_nonnegative("fix_messages"),
            ),
            "event": max(1, len(world_events), declared_lifecycle),
        }
        for kind, minimum in graph_projection_minimums.items():
            if graph_kinds[kind] < minimum:
                failures.append(
                    f"KG {kind} projection: observed {graph_kinds[kind]}, "
                    f"required {minimum}"
                )

        receipt_path = profile / "synthetic_reconciliation_report.json"
        receipt: dict[str, Any] | None = None
        if not receipt_path.is_file():
            failures.append("KG synthetic reconciliation receipt is missing")
        else:
            try:
                receipt = _load_json(receipt_path)
                bindings["reconciliation_report_sha256"] = hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest()
            except (json.JSONDecodeError, OSError) as exc:
                failures.append(f"KG synthetic reconciliation receipt is unreadable: {exc}")

        reconciliation_result = None
        graph_binding = projected_graph_binding(graph)
        bindings["graph_projection"] = graph_binding
        if receipt is not None:
            receipt_atoms = receipt.get("truth_atoms")
            receipt_bundle = receipt.get("bundle")
            receipt_entities = receipt.get("entities")
            receipt_properties = receipt.get("properties")
            receipt_relations = receipt.get("relations")
            receipt_events = receipt.get("events")
            receipt_exceptions = receipt.get("exceptions")
            if receipt.get("schema") != "cleanroom.truth-kg-reconciliation/v1":
                failures.append("KG synthetic reconciliation receipt schema is invalid")
            if receipt.get("profile_id") != graph.get("profile_id"):
                failures.append("KG synthetic reconciliation profile does not match graph")
            if receipt.get("status") != "PASS":
                failures.append(
                    f"KG synthetic reconciliation status: {receipt.get('status')!r}, required 'PASS'"
                )
            if receipt.get("classification") != manifest.get("classification"):
                failures.append("KG synthetic reconciliation classification does not match bundle")
            if not isinstance(receipt_bundle, dict):
                failures.append("KG synthetic reconciliation bundle binding is missing")
                receipt_bundle = {}
            if receipt_bundle.get("manifest_sha256") != manifest_sha256:
                failures.append("KG synthetic reconciliation manifest hash does not match bundle")
            if receipt_bundle.get("corpus_sha256") != manifest.get("corpus_sha256"):
                failures.append("KG synthetic reconciliation corpus hash does not match bundle")
            if not isinstance(receipt_exceptions, list):
                failures.append("KG synthetic reconciliation exceptions must be an array")
                receipt_exceptions = []
            elif receipt_exceptions:
                failures.append(
                    "KG synthetic reconciliation exceptions: "
                    f"observed {len(receipt_exceptions)}, required 0"
                )

            if not isinstance(receipt_atoms, dict):
                failures.append("KG synthetic reconciliation truth-atom totals are missing")
                receipt_atoms = {}
            total_atoms = _receipt_integer(receipt_atoms, "total")
            mapped_atoms = _receipt_integer(receipt_atoms, "mapped")
            exception_atoms = _receipt_integer(receipt_atoms, "exceptions")
            expected_atoms = actual_truth_atoms
            if (
                expected_atoms is None
                or total_atoms != expected_atoms
                or mapped_atoms != expected_atoms
                or exception_atoms != 0
            ):
                failures.append(
                    "KG synthetic truth-atom reconciliation: "
                    f"total={total_atoms}, mapped={mapped_atoms}, exceptions={exception_atoms}, "
                    f"required total=mapped={expected_atoms}, exceptions=0"
                )

            expected_entities = len(entities)
            mapped_entities = (
                (_receipt_integer(receipt_entities, "mapped_existing") or 0)
                + (_receipt_integer(receipt_entities, "created") or 0)
                if isinstance(receipt_entities, dict)
                else None
            )
            if (
                not isinstance(receipt_entities, dict)
                or _receipt_integer(receipt_entities, "truth") != expected_entities
                or mapped_entities != expected_entities
                or _receipt_integer(receipt_entities, "exceptions") != 0
            ):
                failures.append(
                    "KG synthetic entity reconciliation does not cover the complete world"
                )
            if (
                not isinstance(receipt_relations, dict)
                or _receipt_integer(receipt_relations, "truth") != len(relations)
                or _receipt_integer(receipt_relations, "mapped") != len(relations)
                or _receipt_integer(receipt_relations, "exceptions") != 0
            ):
                failures.append(
                    "KG synthetic relation reconciliation does not cover the complete world"
                )
            if (
                not isinstance(receipt_properties, dict)
                or _receipt_integer(receipt_properties, "truth")
                != _receipt_integer(receipt_properties, "mapped")
                or _receipt_integer(receipt_properties, "exceptions") != 0
            ):
                failures.append(
                    "KG synthetic property reconciliation is incomplete"
                )
            relation_atom_ids = {
                str(row.get("truth_atom_id"))
                for row in relations
                if row.get("truth_atom_id")
            }
            truth_atoms_by_id = {
                str(atom.get("truth_atom_id") or ""): atom
                for atom in truth_atom_rows or ()
                if atom.get("truth_atom_id")
            }
            event_control_atom_ids = {
                str(atom_id)
                for event in world_events
                for atom_id in event.get("truth_atom_ids") or []
                if str(
                    truth_atoms_by_id.get(str(atom_id), {}).get("predicate") or ""
                )
                in EVENT_CONTROL_PREDICATES
            }
            entity_ids = {
                str(entity.get("entity_id"))
                for entity in entities
                if entity.get("entity_id")
            }
            expected_property_atoms = (
                sum(
                    str(atom.get("subject_id") or "") in entity_ids
                    and str(atom.get("truth_atom_id") or "")
                    not in relation_atom_ids | event_control_atom_ids
                    and str(atom.get("predicate") or "") not in IDENTITY_PREDICATES
                    for atom in truth_atom_rows
                )
                if truth_atom_rows is not None
                else None
            )
            if (
                expected_property_atoms is None
                or not isinstance(receipt_properties, dict)
                or _receipt_integer(receipt_properties, "truth")
                != expected_property_atoms
                or _receipt_integer(receipt_properties, "mapped")
                != expected_property_atoms
            ):
                failures.append(
                    "KG synthetic property reconciliation: "
                    f"truth={_receipt_integer(receipt_properties, 'truth') if isinstance(receipt_properties, dict) else None}, "
                    f"mapped={_receipt_integer(receipt_properties, 'mapped') if isinstance(receipt_properties, dict) else None}, "
                    f"required truth=mapped={expected_property_atoms}"
                )
            if (
                not isinstance(receipt_events, dict)
                or _receipt_integer(receipt_events, "lifecycle_truth") != len(world_events)
                or _receipt_integer(receipt_events, "lifecycle_projected") != len(world_events)
                or _receipt_integer(receipt_events, "fix_messages_projected")
                != observed["fix_messages"]
                or _receipt_integer(receipt_events, "exceptions") != 0
            ):
                failures.append(
                    "KG synthetic event reconciliation does not cover lifecycle and FIX evidence"
                )

            graph_reconciliation = graph.get("synthetic_reconciliation")
            if not isinstance(graph_reconciliation, dict):
                failures.append("KG embedded synthetic reconciliation summary is missing")
            else:
                if (
                    graph_reconciliation.get("schema")
                    != "cleanroom.truth-kg-reconciliation/v1"
                ):
                    failures.append("KG embedded synthetic reconciliation schema is invalid")
                if graph_reconciliation.get("status") != "PASS":
                    failures.append("KG embedded synthetic reconciliation status is not PASS")
                if graph_reconciliation.get("manifest_sha256") != manifest_sha256:
                    failures.append(
                        "KG embedded synthetic reconciliation manifest hash does not match bundle"
                    )
                if graph_reconciliation.get("truth_atoms") != receipt_atoms:
                    failures.append(
                        "KG embedded synthetic reconciliation truth totals differ from receipt"
                    )
                if graph_reconciliation.get("graph_binding") != graph_binding:
                    failures.append(
                        "KG embedded synthetic reconciliation graph binding "
                        "does not match projected graph"
                    )
            if receipt.get("graph_binding") != graph_binding:
                failures.append(
                    "KG synthetic reconciliation graph binding does not match projected graph"
                )
            reconciliation_result = {
                "receipt": str(receipt_path),
                "status": receipt.get("status"),
                "truth_atoms": receipt_atoms,
                "exceptions": len(receipt_exceptions),
                "manifest_sha256": receipt_bundle.get("manifest_sha256"),
                "graph_binding": graph_binding,
            }

        temporal_failures, temporal_projection = _temporal_projection_failures(
            graph,
            world_events,
        )
        failures.extend(temporal_failures)
        graph_result = {
            "type_counts": dict(sorted(graph_kinds.items())),
            "projection_minimums": graph_projection_minimums,
            "expected_people_recognized": len(expected_graph_people),
            "employment_records": len(employment),
            "person_field_missing": missing_graph_fields,
            "reconciliation": reconciliation_result,
            "temporal_projection": temporal_projection,
        }
        for kind, minimum in graph_type_minimums.items():
            if graph_kinds[kind] < minimum:
                failures.append(
                    f"KG {kind} recognition: observed {graph_kinds[kind]}, "
                    f"required {minimum}"
                )
        if len(expected_graph_people) < len(expected_names):
            failures.append(
                "KG intended Person recognition: "
                f"observed {len(expected_graph_people)}, required {len(expected_names)}"
            )
        if any(missing_graph_fields.values()):
            failures.append(
                f"KG incomplete Person properties: {missing_graph_fields}"
            )
        if len(employment) < INSTITUTION_SCALE_MINIMUMS["people"]:
            failures.append(
                "KG employment hydration: "
                f"observed {len(employment)}, "
                f"required {INSTITUTION_SCALE_MINIMUMS['people']}"
            )

    if failures:
        raise InstitutionScaleError("; ".join(failures))
    return {
        "schema": "cleanroom.institution-scale-report/v1",
        "status": "PASS",
        "classification": manifest.get("classification"),
        "corpus_sha256": manifest.get("corpus_sha256"),
        "minimums": INSTITUTION_SCALE_MINIMUMS,
        "observed": observed,
        "email_artifacts_including_control_duplicates": len(email_artifacts),
        "person_field_missing": missing_person_fields,
        "reporting_lines": len(managers),
        "bindings": bindings,
        "graph": graph_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail-closed scale and KG-visibility gate for a synthetic institution"
    )
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("--graph-profile", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify_institution_scale(
                args.corpus_root,
                graph_profile=args.graph_profile,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
