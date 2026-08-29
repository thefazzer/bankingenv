"""Fail-closed verification for generated clean-room corpus bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from email import policy
from email.message import Message
from email.parser import Parser
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from .generator import (
    ARTIFACT_SCHEMA,
    CLASSIFICATION,
    COMMUNICATION_CONTRACT_SCHEMA,
    COMMUNICATION_SURFACES,
    EVIDENCE_ROLE_PREDICATES,
    _canonical_json,
    _communication_message_id,
    _communication_thread_id,
    materialize_state,
)
from .eval_export import verify_evaluation_export
from .workbench import inspect_text_bundle


class VerificationError(ValueError):
    """Raised when a corpus no longer matches its sealed ledger."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _timestamp(event: dict[str, Any], field: str) -> datetime:
    event_id = event.get("event_id", "<unknown>")
    value = event.get(field)
    if not isinstance(value, str):
        raise VerificationError(f"{event_id} is missing {field}")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{event_id} has invalid {field}: {value!r}") from exc
    if moment.tzinfo is None:
        raise VerificationError(f"{event_id} has timezone-naive {field}")
    return moment.astimezone(timezone.utc)


def _employment_bounds(person: dict[str, Any]) -> tuple[date, date | None]:
    attributes = person.get("attributes") or {}
    try:
        start = date.fromisoformat(str(attributes["start_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(
            f"person {person.get('entity_id')} has invalid employment start"
        ) from exc
    end_value = attributes.get("end_date")
    try:
        end = date.fromisoformat(str(end_value)) if end_value else None
    except ValueError as exc:
        raise VerificationError(
            f"person {person.get('entity_id')} has invalid employment end"
        ) from exc
    if end is not None and end < start:
        raise VerificationError(
            f"person {person.get('entity_id')} employment ends before it starts"
        )
    return start, end


def _assert_active(person: dict[str, Any], when: datetime, context: str) -> None:
    start, end = _employment_bounds(person)
    day = when.date()
    if day < start or (end is not None and day > end):
        raise VerificationError(
            f"{context} falls outside employment tenure for "
            f"{person.get('entity_id')}: {day} not in [{start}, {end}]"
        )


def verify_world_temporal_integrity(
    world: dict[str, Any],
    truth_atoms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify actor, authorization, timing, causality and temporal atoms."""

    entities = world.get("entities") or []
    entity_by_id = {
        str(entity.get("entity_id")): entity
        for entity in entities
        if entity.get("entity_id")
    }
    if len(entity_by_id) != len(entities):
        raise VerificationError("world contains duplicate or missing entity IDs")

    events = world.get("lifecycle_events") or []
    event_ids = [event.get("event_id") for event in events]
    if None in event_ids or len(set(event_ids)) != len(event_ids):
        raise VerificationError("world contains duplicate or missing lifecycle event IDs")
    event_order = [
        (_timestamp(event, "event_time"), str(event["event_id"]))
        for event in events
    ]
    if event_order != sorted(event_order):
        raise VerificationError("lifecycle events are not globally ordered")

    atom_by_id: dict[str, dict[str, Any]] = {}
    if truth_atoms is not None:
        atom_by_id = {
            str(atom.get("truth_atom_id")): atom
            for atom in truth_atoms
            if atom.get("truth_atom_id")
        }
        if len(atom_by_id) != len(truth_atoms):
            raise VerificationError("truth atoms contain duplicate or missing IDs")

    effective_lags: set[int] = set()
    observation_lags: set[int] = set()
    recording_lags: set[int] = set()
    role_changes_checked = 0
    role_atoms_checked = 0
    replay_state: dict[str, str] = {}
    for event in events:
        event_id = str(event["event_id"])
        event_time = _timestamp(event, "event_time")
        observed_at = _timestamp(event, "observed_at")
        recorded_at = _timestamp(event, "recorded_at")
        effective_at = _timestamp(event, "effective_at")
        occurred_at = _timestamp(event, "occurred_at")
        if occurred_at != event_time:
            raise VerificationError(
                f"{event_id} occurred_at must be an exact alias of event_time"
            )
        if effective_at > event_time:
            raise VerificationError(
                f"{event_id} effective time occurs after business event"
            )
        if event_time > observed_at:
            raise VerificationError(
                f"{event_id} event time occurs after observation"
            )
        if observed_at > recorded_at:
            raise VerificationError(
                f"{event_id} observation occurs after recording"
            )
        effective_lags.add(int((event_time - effective_at).total_seconds()))
        observation_lags.add(int((observed_at - event_time).total_seconds()))
        recording_lags.add(int((recorded_at - observed_at).total_seconds()))

        subject_id = str(event.get("subject_id") or "")
        if subject_id not in entity_by_id:
            raise VerificationError(f"{event_id} references unknown subject")
        unknown_objects = set(event.get("object_ids") or []) - set(entity_by_id)
        if unknown_objects:
            raise VerificationError(
                f"{event_id} references unknown objects: {sorted(unknown_objects)}"
            )

        actor_id = str(event.get("actor_id") or "")
        actor = entity_by_id.get(actor_id)
        if actor is None or actor.get("kind") != "person":
            raise VerificationError(f"{event_id} has no valid Person actor")
        _assert_active(actor, event_time, f"actor action {event_id}")
        authorized = set(
            (actor.get("attributes") or {}).get("authorized_event_types") or []
        )
        if event.get("event_type") not in authorized:
            raise VerificationError(
                f"{event_id} actor {actor_id} is not authorized for "
                f"{event.get('event_type')}"
            )

        state_before = event.get("state_before")
        state_after = event.get("state_after")
        if not isinstance(state_after, str) or not state_after:
            raise VerificationError(f"{event_id} has invalid state_after")
        if subject_id not in replay_state and state_before is not None:
            replay_state[subject_id] = str(state_before)
        if state_before is not None and replay_state.get(subject_id) != state_before:
            raise VerificationError(
                f"{event_id} state_before does not match prior lifecycle state"
            )
        replay_state[subject_id] = state_after

        if event.get("event_type") == "employee_role_changed":
            subject = entity_by_id[subject_id]
            if subject.get("kind") != "person":
                raise VerificationError(f"{event_id} role-change subject is not a Person")
            _assert_active(subject, effective_at, f"role change {event_id}")
            if actor_id == subject_id:
                raise VerificationError(
                    f"{event_id} role change requires a distinct authorized actor"
                )
            if not isinstance(state_before, str) or not state_before:
                raise VerificationError(f"{event_id} role change has no old role")
            if state_before == state_after:
                raise VerificationError(f"{event_id} role change does not change role")
            attributes = subject.get("attributes") or {}
            if attributes.get("role") != state_after:
                raise VerificationError(
                    f"{event_id} current structured role does not match new role"
                )

            if truth_atoms is not None:
                referenced_atom_ids = {
                    str(atom_id) for atom_id in event.get("truth_atom_ids") or []
                }
                unknown_atom_ids = referenced_atom_ids - set(atom_by_id)
                if unknown_atom_ids:
                    raise VerificationError(
                        f"{event_id} references unknown truth atoms: "
                        f"{sorted(unknown_atom_ids)}"
                    )
                referenced_atoms = [
                    atom_by_id[atom_id] for atom_id in referenced_atom_ids
                ]
                change_atoms = [
                    atom
                    for atom in referenced_atoms
                    if atom.get("subject_id") == subject_id
                    and atom.get("predicate") == "role_change"
                ]
                if len(change_atoms) != 1:
                    raise VerificationError(
                        f"{event_id} must reference exactly one role_change atom"
                    )
                change_atom = change_atoms[0]
                if change_atom.get("valid_from") != event.get("effective_at"):
                    raise VerificationError(
                        f"{event_id} role_change atom effective time is misaligned"
                    )
                change_value = change_atom.get("value")
                if not isinstance(change_value, dict):
                    raise VerificationError(
                        f"{event_id} role_change atom has no structured value"
                    )
                if (
                    change_value.get("from") != state_before
                    or change_value.get("to") != state_after
                ):
                    raise VerificationError(
                        f"{event_id} role_change atom disagrees with lifecycle state"
                    )
                structured_values = {
                    "role": (
                        change_value.get("from"),
                        change_value.get("to"),
                    ),
                    "title": (
                        change_value.get("title_from"),
                        change_value.get("title_to"),
                    ),
                    "seniority": (
                        change_value.get("seniority_from"),
                        change_value.get("seniority_to"),
                    ),
                    "seniority_band": (
                        change_value.get("seniority_band_from"),
                        change_value.get("seniority_band_to"),
                    ),
                }
                for predicate, (old_value, new_value) in structured_values.items():
                    if old_value is None or new_value is None:
                        raise VerificationError(
                            f"{event_id} role_change omits {predicate} values"
                        )
                    old_atoms = [
                        atom
                        for atom in referenced_atoms
                        if atom.get("subject_id") == subject_id
                        and atom.get("predicate") == predicate
                        and atom.get("value") == old_value
                        and atom.get("valid_to") == event.get("effective_at")
                    ]
                    new_atoms = [
                        atom
                        for atom in referenced_atoms
                        if atom.get("subject_id") == subject_id
                        and atom.get("predicate") == predicate
                        and atom.get("value") == new_value
                        and atom.get("valid_from") == event.get("effective_at")
                        and atom.get("valid_to") is None
                    ]
                    if len(old_atoms) != 1 or old_atoms[0].get("valid_from") is None:
                        raise VerificationError(
                            f"{event_id} old {predicate} atom is not time-bounded"
                        )
                    if len(new_atoms) != 1:
                        raise VerificationError(
                            f"{event_id} new {predicate} atom effective time is misaligned"
                        )
                    if attributes.get(predicate) != new_value:
                        raise VerificationError(
                            f"{event_id} current {predicate} does not match new atom"
                        )
                    role_atoms_checked += 2

                title_from = change_value["title_from"]
                title_to = change_value["title_to"]
                title_relations = [
                    relation
                    for relation in world.get("relations") or []
                    if relation.get("source_id") == subject_id
                    and relation.get("predicate") == "has_title"
                ]

                def _position_title(relation: dict[str, Any]) -> str | None:
                    target = entity_by_id.get(str(relation.get("target_id") or ""))
                    if target is None or target.get("kind") != "position":
                        return None
                    aliases = target.get("aliases") or []
                    return str(aliases[0]) if aliases else None

                old_title_relations = [
                    relation
                    for relation in title_relations
                    if _position_title(relation) == title_from
                    and relation.get("valid_to") == event.get("effective_at")
                ]
                new_title_relations = [
                    relation
                    for relation in title_relations
                    if _position_title(relation) == title_to
                    and relation.get("valid_from") == event.get("effective_at")
                    and relation.get("valid_to") is None
                ]
                if len(old_title_relations) != 1:
                    raise VerificationError(
                        f"{event_id} old has_title relation is not time-bounded"
                    )
                if len(new_title_relations) != 1:
                    raise VerificationError(
                        f"{event_id} new has_title relation effective time is misaligned"
                    )
                for relation in old_title_relations + new_title_relations:
                    relation_atom = atom_by_id.get(
                        str(relation.get("truth_atom_id") or "")
                    )
                    if (
                        relation_atom is None
                        or relation_atom.get("truth_atom_id")
                        not in referenced_atom_ids
                        or relation_atom.get("value") != relation.get("target_id")
                        or relation_atom.get("valid_from")
                        != relation.get("valid_from")
                        or relation_atom.get("valid_to") != relation.get("valid_to")
                    ):
                        raise VerificationError(
                            f"{event_id} has_title relation atom is not conserved"
                        )
                    role_atoms_checked += 1
            role_changes_checked += 1

    if len(events) > 1:
        if len(effective_lags) < 2:
            raise VerificationError("effective timing is degenerate")
        if len(observation_lags) < 2:
            raise VerificationError("observation timing is degenerate")
        if len(recording_lags) < 2:
            raise VerificationError("recording timing is degenerate")
    if len(events) >= 64 and (
        len(effective_lags) < 17
        or len(observation_lags) < 17
        or len(recording_lags) < 17
    ):
        raise VerificationError(
            "lifecycle clock delays do not have broad deterministic variation"
        )

    reporting_lines_checked = 0
    assigned_to: dict[str, list[str]] = {}
    concerns: dict[str, list[str]] = {}
    for relation in world.get("relations") or []:
        source_id = str(relation.get("source_id") or "")
        target_id = str(relation.get("target_id") or "")
        predicate = relation.get("predicate")
        if predicate == "reports_to":
            subordinate = entity_by_id.get(source_id)
            manager = entity_by_id.get(target_id)
            if (
                subordinate is None
                or manager is None
                or subordinate.get("kind") != "person"
                or manager.get("kind") != "person"
            ):
                raise VerificationError(
                    f"reporting line {source_id}->{target_id} is not Person-to-Person"
                )
            subordinate_start, subordinate_end = _employment_bounds(subordinate)
            manager_start, manager_end = _employment_bounds(manager)
            if manager_start > subordinate_start or (
                manager_end is not None
                and (
                    subordinate_end is None
                    or manager_end < subordinate_end
                )
            ):
                raise VerificationError(
                    f"manager tenure does not cover reporting line "
                    f"{source_id}->{target_id}"
                )
            reporting_lines_checked += 1
        elif predicate == "assigned_to":
            assigned_to.setdefault(source_id, []).append(target_id)
        elif predicate == "concerns":
            concerns.setdefault(source_id, []).append(target_id)

    case_assignments_checked = 0
    causal_links_checked = 0
    for entity in entities:
        if entity.get("kind") != "case":
            continue
        case_id = str(entity["entity_id"])
        owners = assigned_to.get(case_id, [])
        if len(owners) != 1 or owners[0] not in entity_by_id:
            raise VerificationError(
                f"case {case_id} must have exactly one valid assigned owner"
            )
        owner = entity_by_id[owners[0]]
        case_events = [
            event for event in events if event.get("subject_id") == case_id
        ]
        if not case_events:
            raise VerificationError(f"case {case_id} has no lifecycle events")
        first_event = min(case_events, key=lambda event: _timestamp(event, "event_time"))
        _assert_active(
            owner,
            _timestamp(first_event, "event_time"),
            f"case assignment {case_id}",
        )
        case_assignments_checked += 1

        trade_ids = concerns.get(case_id, [])
        if len(trade_ids) != 1:
            raise VerificationError(
                f"case {case_id} must concern exactly one trade"
            )
        trade_id = trade_ids[0]
        trade = entity_by_id.get(trade_id)
        if trade is None or trade.get("kind") != "trade":
            raise VerificationError(
                f"case {case_id} concerns an invalid trade"
            )
        exception_events = [
            event
            for event in events
            if event.get("subject_id") == trade_id
            and event.get("event_type") == "trade_exception"
            and case_id in (event.get("object_ids") or [])
        ]
        opening_events = [
            event
            for event in case_events
            if event.get("event_type") == "case_opened"
            and trade_id in (event.get("object_ids") or [])
        ]
        if len(exception_events) != 1 or len(opening_events) != 1:
            raise VerificationError(
                f"case {case_id} must have one linked exception and opening"
            )
        exception_event = exception_events[0]
        opening_event = opening_events[0]
        if (
            _timestamp(exception_event, "event_time")
            >= _timestamp(opening_event, "event_time")
            or _timestamp(exception_event, "recorded_at")
            >= _timestamp(opening_event, "event_time")
        ):
            raise VerificationError(
                f"case {case_id} opened before linked trade exception"
            )
        causal_links_checked += 1

    return {
        "schema": "cleanroom.temporal-integrity-report/v1",
        "status": "PASS",
        "events_checked": len(events),
        "employment_active_actor_events": len(events),
        "authorized_actor_events": len(events),
        "ordered_event_timings": len(events),
        "case_assignments_checked": case_assignments_checked,
        "causal_links_checked": causal_links_checked,
        "reporting_lines_checked": reporting_lines_checked,
        "role_changes_checked": role_changes_checked,
        "role_atoms_checked": role_atoms_checked,
        "effective_lag_variants": len(effective_lags),
        "observation_lag_variants": len(observation_lags),
        "recording_lag_variants": len(recording_lags),
    }


_REQUIRED_EMAIL_HEADERS = (
    "From",
    "To",
    "Message-ID",
    "Thread-ID",
    "Conversation-ID",
    "Subject",
)


def _parse_email_message(text: str, label: str) -> Message:
    """Parse one generated email and reject ambiguous or malformed envelopes."""

    message = Parser(policy=policy.default).parsestr(text)
    defects = list(message.defects)
    for header in message.values():
        defects.extend(getattr(header, "defects", ()))
    if defects:
        detail = ", ".join(type(defect).__name__ for defect in defects)
        raise VerificationError(f"{label} has email parser defects: {detail}")
    for name in _REQUIRED_EMAIL_HEADERS:
        count = len(message.get_all(name, []))
        if count != 1:
            raise VerificationError(
                f"{label} must have exactly one actual {name} header; found {count}"
            )

    date_headers = message.get_all("Date", [])
    omitted_headers = message.get_all("X-Synthetic-Date-Omitted", [])
    if len(date_headers) + len(omitted_headers) != 1:
        raise VerificationError(
            f"{label} must have exactly one Date or X-Synthetic-Date-Omitted header"
        )
    if omitted_headers and str(omitted_headers[0]).strip().casefold() != "true":
        raise VerificationError(f"{label} has an invalid date-omission marker")
    if len(message.get_all("In-Reply-To", [])) > 1:
        raise VerificationError(f"{label} has duplicate In-Reply-To headers")
    return message


def _verify_dated_email_participants(
    root: Path,
    world: dict[str, Any],
) -> dict[str, int]:
    people_by_email = {
        str((entity.get("attributes") or {}).get("email")).casefold(): entity
        for entity in world.get("entities") or []
        if entity.get("kind") == "person"
        and (entity.get("attributes") or {}).get("email")
    }
    dated_messages = 0
    participants_checked = 0
    undated_messages = 0
    for path in sorted((root / "raw" / "email").glob("*.eml")):
        text = path.read_text(encoding="utf-8")
        message = _parse_email_message(text, path.name)
        date_header = message["Date"]
        if date_header is None:
            undated_messages += 1
            continue
        when = getattr(date_header, "datetime", None)
        if not isinstance(when, datetime):
            raise VerificationError(f"{path.name} has invalid Date header")
        if when.tzinfo is None:
            raise VerificationError(f"{path.name} has timezone-naive Date header")
        dated_messages += 1
        for field in ("From", "To"):
            addresses = getaddresses([str(value) for value in message.get_all(field, [])])
            if len(addresses) != 1 or not addresses[0][1]:
                raise VerificationError(
                    f"{path.name} must have exactly one {field} participant"
                )
            participant = people_by_email.get(addresses[0][1].strip().casefold())
            if participant is None:
                raise VerificationError(
                    f"{path.name} references unknown {field} participant"
                )
            _assert_active(
                participant,
                when.astimezone(timezone.utc),
                f"{path.name} {field}",
            )
            participants_checked += 1
    return {
        "dated_email_messages_checked": dated_messages,
        "dated_email_participants_checked": participants_checked,
        "undated_email_messages": undated_messages,
    }


_COMMUNICATION_FIELDS = frozenset({
    "message_id",
    "thread_id",
    "conversation_id",
    "thread_root_id",
    "parent_message_id",
})


def _text_communication_header(text: str, name: str) -> str | None:
    match = re.search(
        rf"^{re.escape(name)}:\s*(.*?)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    return match.group(1).strip().removeprefix("<").removesuffix(">")


def verify_communication_threads(
    root: Path,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify source-assigned communication identity and duplicate lineage.

    Legacy bundles remain verifiable as their original v1 contract. A bundle
    declaring the communication contract must, however, carry deterministic
    IDs on every email/chat artefact and matching IDs in the raw bytes. Nothing
    is reconstructed from subjects, participants or text similarity.
    """

    contract = manifest.get("communication_contract")
    metadata_rows = [
        artifact
        for artifact in artifacts
        if _COMMUNICATION_FIELDS.intersection(artifact)
    ]
    if contract is None:
        if metadata_rows:
            raise VerificationError(
                "communication metadata is present without a manifest contract"
            )
        return {
            "schema": "cleanroom.communication-thread-verification/v1",
            "status": "LEGACY_V1_NOT_APPLICABLE",
            "communication_artifacts_checked": 0,
            "communication_messages_checked": 0,
            "communication_threads_checked": 0,
            "duplicate_lineages_checked": 0,
        }
    if not isinstance(contract, dict):
        raise VerificationError("communication contract must be an object")
    if contract.get("schema") != COMMUNICATION_CONTRACT_SCHEMA:
        raise VerificationError("unsupported communication contract schema")
    if contract.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise VerificationError("communication contract artifact schema mismatch")
    if contract.get("assignment_phase") != "hidden-world-render-before-artifact-bytes":
        raise VerificationError("communication IDs are not declared source-assigned")
    if contract.get("thread_scope") != "focal-business-root":
        raise VerificationError("communication thread scope is not focal-business-root")
    if contract.get("conversation_id_rule") != "exact-alias-of-thread-id":
        raise VerificationError("communication conversation/thread alias rule changed")
    if set(contract.get("surfaces") or []) != set(COMMUNICATION_SURFACES):
        raise VerificationError("communication surface contract mismatch")
    if any(artifact.get("schema") != ARTIFACT_SCHEMA for artifact in artifacts):
        raise VerificationError("v2 communication bundle contains a legacy artefact record")

    artifact_by_id = {
        str(artifact.get("artifact_id") or ""): artifact for artifact in artifacts
    }
    if "" in artifact_by_id or len(artifact_by_id) != len(artifacts):
        raise VerificationError("artefact records contain duplicate or missing IDs")

    communication_rows = [
        artifact
        for artifact in artifacts
        if artifact.get("surface") in COMMUNICATION_SURFACES
    ]
    noncommunication_metadata = [
        str(artifact["artifact_id"])
        for artifact in artifacts
        if artifact.get("surface") not in COMMUNICATION_SURFACES
        and _COMMUNICATION_FIELDS.intersection(artifact)
    ]
    if noncommunication_metadata:
        raise VerificationError(
            "non-communication artefacts carry thread metadata: "
            + ", ".join(noncommunication_metadata[:8])
        )
    if len(communication_rows) != len(metadata_rows):
        raise VerificationError("communication artefact metadata coverage is incomplete")

    seed = manifest.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise VerificationError("manifest seed is invalid for communication verification")

    messages: dict[str, list[dict[str, Any]]] = {}
    roots_by_thread: dict[str, set[str]] = {}
    threads_by_root: dict[str, set[str]] = {}
    for artifact in communication_rows:
        artifact_id = str(artifact["artifact_id"])
        values = {
            field: artifact.get(field) for field in _COMMUNICATION_FIELDS
        }
        for field in ("message_id", "thread_id", "conversation_id", "thread_root_id"):
            if not isinstance(values[field], str) or not values[field]:
                raise VerificationError(
                    f"communication artefact {artifact_id} is missing {field}"
                )
        parent_message_id = values["parent_message_id"]
        if parent_message_id is not None and (
            not isinstance(parent_message_id, str) or not parent_message_id
        ):
            raise VerificationError(
                f"communication artefact {artifact_id} has invalid parent_message_id"
            )
        expected_thread_id = _communication_thread_id(
            seed,
            str(values["thread_root_id"]),
        )
        if values["thread_id"] != expected_thread_id:
            raise VerificationError(
                f"communication artefact {artifact_id} thread ID is not deterministic"
            )
        if values["conversation_id"] != values["thread_id"]:
            raise VerificationError(
                f"communication artefact {artifact_id} conversation/thread IDs diverge"
            )

        duplicate_kind = artifact.get("duplicate_kind")
        duplicate_of = artifact.get("duplicate_of")
        if duplicate_kind == "exact":
            expected_message_id = None
        else:
            expected_message_id = _communication_message_id(seed, artifact_id)
        if expected_message_id is not None and values["message_id"] != expected_message_id:
            raise VerificationError(
                f"communication artefact {artifact_id} message ID is not deterministic"
            )

        path = (root / str(artifact["relative_path"])).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise VerificationError(
                f"communication artefact {artifact_id} escapes corpus root"
            ) from exc
        text = path.read_text(encoding="utf-8")
        if artifact["surface"] == "email":
            message = _parse_email_message(text, artifact_id)

            def header_value(name: str) -> str | None:
                value = message[name]
                if value is None:
                    return None
                return str(value).strip().removeprefix("<").removesuffix(">")

            identity_header = "Message-ID"
        else:
            header_value = lambda name: _text_communication_header(text, name)
            identity_header = "Transcript-ID"
        if header_value(identity_header) != values["message_id"]:
            raise VerificationError(
                f"communication artefact {artifact_id} raw {identity_header} mismatch"
            )
        if header_value("Thread-ID") != values["thread_id"]:
            raise VerificationError(
                f"communication artefact {artifact_id} raw Thread-ID mismatch"
            )
        if header_value("Conversation-ID") != values["conversation_id"]:
            raise VerificationError(
                f"communication artefact {artifact_id} raw Conversation-ID mismatch"
            )
        raw_parent = header_value("In-Reply-To")
        if raw_parent != parent_message_id:
            raise VerificationError(
                f"communication artefact {artifact_id} raw reply lineage mismatch"
            )

        message_id = str(values["message_id"])
        thread_id = str(values["thread_id"])
        thread_root_id = str(values["thread_root_id"])
        messages.setdefault(message_id, []).append(artifact)
        roots_by_thread.setdefault(thread_id, set()).add(thread_root_id)
        threads_by_root.setdefault(thread_root_id, set()).add(thread_id)

    if any(len(roots) != 1 for roots in roots_by_thread.values()):
        raise VerificationError("one communication thread maps to multiple business roots")
    if any(len(threads) != 1 for threads in threads_by_root.values()):
        raise VerificationError("one communication root maps to multiple thread IDs")

    duplicate_lineages_checked = 0
    for artifact in communication_rows:
        artifact_id = str(artifact["artifact_id"])
        duplicate_of = artifact.get("duplicate_of")
        duplicate_kind = artifact.get("duplicate_kind")
        if bool(duplicate_of) != bool(duplicate_kind):
            raise VerificationError(
                f"communication artefact {artifact_id} has partial duplicate lineage"
            )
        if not duplicate_of:
            continue
        parent = artifact_by_id.get(str(duplicate_of))
        if parent is None or parent.get("surface") not in COMMUNICATION_SURFACES:
            raise VerificationError(
                f"communication artefact {artifact_id} has no communication parent"
            )
        if str(duplicate_of) == artifact_id:
            raise VerificationError(
                f"communication artefact {artifact_id} duplicates itself"
            )
        for field in ("surface", "thread_id", "conversation_id", "thread_root_id"):
            if artifact.get(field) != parent.get(field):
                raise VerificationError(
                    f"communication duplicate {artifact_id} changed {field}"
                )
        if duplicate_kind == "exact":
            if artifact.get("message_id") != parent.get("message_id"):
                raise VerificationError(
                    f"exact communication duplicate {artifact_id} changed message ID"
                )
            if artifact.get("parent_message_id") != parent.get("parent_message_id"):
                raise VerificationError(
                    f"exact communication duplicate {artifact_id} changed reply lineage"
                )
            if artifact.get("sha256") != parent.get("sha256"):
                raise VerificationError(
                    f"exact communication duplicate {artifact_id} changed bytes"
                )
        elif duplicate_kind == "near":
            if artifact.get("message_id") == parent.get("message_id"):
                raise VerificationError(
                    f"near communication duplicate {artifact_id} reused message ID"
                )
            if artifact.get("parent_message_id") != parent.get("message_id"):
                raise VerificationError(
                    f"near communication duplicate {artifact_id} is not a source reply"
                )
            if artifact.get("sha256") == parent.get("sha256"):
                raise VerificationError(
                    f"near communication duplicate {artifact_id} has exact source bytes"
                )
        else:
            raise VerificationError(
                f"communication duplicate {artifact_id} has invalid duplicate kind"
            )
        duplicate_lineages_checked += 1

    for artifact in communication_rows:
        parent_message_id = artifact.get("parent_message_id")
        if not parent_message_id:
            continue
        parents = messages.get(str(parent_message_id)) or []
        if not parents:
            raise VerificationError(
                f"communication artefact {artifact['artifact_id']} replies to an unknown message"
            )
        if any(parent.get("thread_id") != artifact.get("thread_id") for parent in parents):
            raise VerificationError(
                f"communication artefact {artifact['artifact_id']} crosses thread in reply lineage"
            )

    for message_id, rows in messages.items():
        if len(rows) <= 1:
            continue
        primaries = [row for row in rows if row.get("duplicate_kind") != "exact"]
        if len(primaries) != 1 or any(
            row.get("duplicate_kind") not in (None, "exact") for row in rows
        ):
            raise VerificationError(
                f"message ID {message_id} is reused outside exact duplicate lineage"
            )

    return {
        "schema": "cleanroom.communication-thread-verification/v1",
        "status": "PASS",
        "communication_artifacts_checked": len(communication_rows),
        "communication_messages_checked": len(messages),
        "communication_threads_checked": len(roots_by_thread),
        "duplicate_lineages_checked": duplicate_lineages_checked,
    }


def verify_corpus(root: Path) -> dict[str, Any]:
    """Rehash and replay a bundle without trusting caller-authored counts."""

    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("classification") != CLASSIFICATION:
        raise VerificationError("manifest is not classified SYNTHETIC_CLEAN_ROOM")

    derived_bundle = root / "synthetic-corpus.txt"
    derived_bundle_report = None
    if derived_bundle.is_file():
        try:
            derived_bundle_report = inspect_text_bundle(root, derived_bundle)
        except ValueError as exc:
            raise VerificationError(f"invalid derived workbench bundle: {exc}") from exc

    expected_files = {record["path"]: record for record in manifest["files"]}
    observed_files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        if path == derived_bundle:
            continue
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        observed_files[relative] = {
            "path": relative,
            "sha256": _sha256(payload),
            "bytes": len(payload),
        }
    if observed_files != expected_files:
        missing = sorted(set(expected_files) - set(observed_files))
        extra = sorted(set(observed_files) - set(expected_files))
        changed = sorted(
            path
            for path in set(expected_files) & set(observed_files)
            if expected_files[path] != observed_files[path]
        )
        raise VerificationError(
            f"file commitment mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    ordered_records = [observed_files[path] for path in sorted(observed_files)]
    if _sha256(_canonical_json(ordered_records).encode("utf-8")) != manifest["corpus_sha256"]:
        raise VerificationError("corpus digest mismatch")

    atoms = _load_jsonl(root / "hidden" / "truth_atoms.jsonl")
    atom_ids = {atom["truth_atom_id"] for atom in atoms}
    atom_by_id = {atom["truth_atom_id"]: atom for atom in atoms}
    if len(atom_ids) != len(atoms):
        raise VerificationError("duplicate truth atom ID")
    if any(atom["classification"] != CLASSIFICATION for atom in atoms):
        raise VerificationError("truth atom classification mismatch")

    world = json.loads((root / "hidden" / "world.json").read_text(encoding="utf-8"))
    lifecycle_ledger = _load_jsonl(root / "hidden" / "lifecycle_events.jsonl")
    if lifecycle_ledger != world["lifecycle_events"]:
        raise VerificationError("world lifecycle events differ from lifecycle ledger")
    if materialize_state(world["lifecycle_events"]) != world["materialized_state"]:
        raise VerificationError("materialized lifecycle state does not replay")
    temporal_integrity = verify_world_temporal_integrity(world, atoms)
    temporal_integrity.update(_verify_dated_email_participants(root, world))

    artifacts = _load_jsonl(root / "provenance" / "artifacts.jsonl")
    spans = _load_jsonl(root / "provenance" / "spans.jsonl")
    spans_by_artifact: dict[str, list[dict[str, Any]]] = {}
    supported_atom_ids: set[str] = set()
    for span in spans:
        spans_by_artifact.setdefault(span["artifact_id"], []).append(span)
        unknown = set(span["truth_atom_ids"]) - atom_ids
        if unknown:
            raise VerificationError(f"span references unknown truth atoms: {sorted(unknown)}")
        evidence_role = span.get("evidence_role")
        allowed_predicates = EVIDENCE_ROLE_PREDICATES.get(evidence_role)
        if allowed_predicates is None:
            raise VerificationError(
                f"span has unknown evidence role: {evidence_role!r}"
            )
        claimed_predicates = {
            str(atom_by_id[atom_id]["predicate"])
            for atom_id in span["truth_atom_ids"]
        }
        unsupported = claimed_predicates - allowed_predicates
        if unsupported:
            raise VerificationError(
                f"span {span.get('span_id')} role {evidence_role!r} "
                f"cannot support predicates: {sorted(unsupported)}"
            )
        if span.get("assertion") == "supports":
            supported_atom_ids.update(span["truth_atom_ids"])
    unsupported_atoms = atom_ids - supported_atom_ids
    if unsupported_atoms:
        missing_predicates = sorted({
            str(atom_by_id[atom_id]["predicate"])
            for atom_id in unsupported_atoms
        })
        raise VerificationError(
            f"truth atoms lack supporting source spans: "
            f"count={len(unsupported_atoms)}, predicates={missing_predicates}"
        )

    artifact_ids = {artifact["artifact_id"] for artifact in artifacts}
    if set(spans_by_artifact) != artifact_ids:
        raise VerificationError("artefact/span index mismatch")
    for artifact in artifacts:
        path = (root / artifact["relative_path"]).resolve()
        if root not in path.parents:
            raise VerificationError("artefact path escapes corpus root")
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        if _sha256(payload) != artifact["sha256"]:
            raise VerificationError(f"artefact hash mismatch: {artifact['artifact_id']}")
        byte_cursor = 0
        char_cursor = 0
        for span in sorted(
            spans_by_artifact[artifact["artifact_id"]],
            key=lambda item: item["byte_start"],
        ):
            if span["byte_start"] != byte_cursor or span["char_start"] != char_cursor:
                raise VerificationError(f"non-contiguous span partition: {artifact['artifact_id']}")
            fragment = payload[span["byte_start"] : span["byte_end"]]
            if _sha256(fragment) != span["text_sha256"]:
                raise VerificationError(f"span hash mismatch: {span['span_id']}")
            decoded = fragment.decode("utf-8")
            if text[span["char_start"] : span["char_end"]] != decoded:
                raise VerificationError(f"character offsets mismatch: {span['span_id']}")
            byte_cursor = span["byte_end"]
            char_cursor = span["char_end"]
        if byte_cursor != len(payload) or char_cursor != len(text):
            raise VerificationError(f"incomplete span coverage: {artifact['artifact_id']}")

    communication_threads = verify_communication_threads(root, manifest, artifacts)

    kind_counts: dict[str, int] = {}
    for entity in world["entities"]:
        kind = str(entity.get("kind"))
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    observed_counts = {
        "entities": len(world["entities"]),
        "people": kind_counts.get("person", 0),
        "clients": kind_counts.get("client", 0),
        "accounts": kind_counts.get("account", 0),
        "trades": kind_counts.get("trade", 0),
        "tickets": kind_counts.get("case", 0),
        "relations": len(world["relations"]),
        "truth_atoms": len(atoms),
        "lifecycle_events": len(world["lifecycle_events"]),
        "artifacts": len(artifacts),
        "email_messages": len(list((root / "raw" / "email").glob("*.eml")))
        - sum(bool(row.get("duplicate_of")) for row in artifacts if row.get("surface") == "email"),
        "fix_messages": sum(
            path.read_text(encoding="utf-8").count("8=FIX.")
            for path in (root / "raw" / "fix").glob("*.fix")
        ),
        **(
            {
                "communication_artifacts": communication_threads[
                    "communication_artifacts_checked"
                ],
                "communication_messages": communication_threads[
                    "communication_messages_checked"
                ],
                "communication_threads": communication_threads[
                    "communication_threads_checked"
                ],
            }
            if communication_threads["status"] == "PASS"
            else {}
        ),
        "provenance_spans": len(spans),
        "evaluation_episodes": len(
            list((root / "evaluation" / "episodes").glob("*/*.json"))
        ),
        "evaluation_requests": len(
            _load_jsonl(root / "evaluation" / "lineage" / "request_receipt_index.jsonl")
        ),
        "evaluation_receipts": len(
            _load_jsonl(root / "evaluation" / "lineage" / "request_receipt_index.jsonl")
        ),
        "evaluation_evidence_refs": len(
            _load_jsonl(root / "evaluation" / "public" / "evidence_refs.jsonl")
        ),
    }
    if observed_counts != manifest["counts"]:
        raise VerificationError(
            f"manifest count mismatch: expected={manifest['counts']}, observed={observed_counts}"
        )
    evaluation = verify_evaluation_export(root)
    return {
        "status": "PASS",
        "classification": CLASSIFICATION,
        "corpus_sha256": manifest["corpus_sha256"],
        "counts": observed_counts,
        "evaluation": evaluation,
        "temporal_integrity": temporal_integrity,
        "communication_threads": communication_threads,
        "derived_workbench_bundle": derived_bundle_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a generated clean-room corpus")
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(verify_corpus(args.corpus), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
