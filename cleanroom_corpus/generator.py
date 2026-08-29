"""Generate a losslessly traced, wholly synthetic operations corpus.

The hidden world is created before any documents are rendered.  Surface
artefacts may be incomplete, duplicated, noisy or contradictory, but the
truth ledger remains deterministic and immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.parser import Parser
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "cleanroom.capital-markets-corpus/v1"
CLASSIFICATION = "SYNTHETIC_CLEAN_ROOM"
GENERATOR_NAMESPACE = uuid.UUID("392779fa-4334-5f4d-85fd-696aa77a9418")
ARTIFACT_SCHEMA = "cleanroom.artifact/v2"
COMMUNICATION_CONTRACT_SCHEMA = "cleanroom.communication-thread-contract/v1"
COMMUNICATION_SURFACES = frozenset({"email", "chat"})

PRODUCTS = (
    ("interest-rate-swap", "Interest Rate Swap"),
    ("total-return-swap", "Total Return Swap"),
    ("repo", "Repurchase Agreement"),
    ("fx-forward", "Foreign Exchange Forward"),
    ("convertible-bond", "Convertible Bond"),
    ("cash-equity", "Cash Equity"),
)
SYSTEM_CAPABILITIES = (
    "Trade Capture",
    "Confirmations",
    "Settlements",
    "Collateral",
    "Reference Data",
    "Client Service",
)
SENIORITY = (
    ("Managing Director", 5),
    ("Director", 4),
    ("Vice President", 3),
    ("Associate", 2),
    ("Analyst", 1),
)
GIVEN_NAMES = (
    "Aveline", "Bram", "Cerys", "Dorian", "Elara", "Florian", "Ginevra",
    "Hadrian", "Isolde", "Jasper", "Kerensa", "Leander", "Maris", "Nerys",
    "Orson", "Petra", "Quentin", "Rhea", "Soren", "Tamsin",
)
FAMILY_NAMES = (
    "Alder", "Birch", "Cedar", "Dahlia", "Elm", "Fern", "Grove", "Hazel",
    "Iris", "Juniper", "Kestrel", "Linden", "Mercer", "North", "Orchard",
    "Pryce", "Quill", "Rowan", "Sable", "Vale",
)
OPERATING_FUNCTIONS = (
    "Trade Capture Operations",
    "Allocations and Give-Ups",
    "Confirmations",
    "Settlements",
    "Collateral and Margin",
    "Cash and Position Reconciliation",
    "Client Service",
    "Reference Data",
    "Middle Office Control",
    "Product Control",
    "Market and Credit Risk",
    "Compliance Surveillance",
    "Legal Operations",
    "Production Support",
    "Application Development",
    "Site Reliability Engineering",
    "Database Engineering",
    "Quality Assurance",
    "Release and Change Management",
    "Operations Leadership",
)
CASE_CATEGORIES = (
    "allocation-break",
    "booking-error",
    "confirmation-mismatch",
    "collateral-dispute",
    "margin-call-break",
    "settlement-fail",
    "cash-reconciliation",
    "position-reconciliation",
    "reference-data",
    "permission-release",
    "valuation-dispute",
    "fix-session",
)
CASE_FUNCTIONS = {
    "allocation-break": "Allocations and Give-Ups",
    "booking-error": "Trade Capture Operations",
    "confirmation-mismatch": "Confirmations",
    "collateral-dispute": "Collateral and Margin",
    "margin-call-break": "Collateral and Margin",
    "settlement-fail": "Settlements",
    "cash-reconciliation": "Cash and Position Reconciliation",
    "position-reconciliation": "Cash and Position Reconciliation",
    "reference-data": "Reference Data",
    "permission-release": "Release and Change Management",
    "valuation-dispute": "Product Control",
    "fix-session": "Production Support",
}
EVENT_FUNCTIONS = {
    "client_onboarded": {"Client Service"},
    "account_proposed": {"Client Service"},
    "account_activated": {"Reference Data"},
    "trade_booked": {"Trade Capture Operations"},
    "trade_confirmed": {"Confirmations"},
    "trade_settled": {"Settlements"},
    "employee_role_changed": {"Operations Leadership"},
}
CASE_EVENT_TYPES = {
    "case_opened",
    "case_investigating",
    "case_resolved",
    "trade_exception",
}
ALL_EVENT_TYPES = set(EVENT_FUNCTIONS) | CASE_EVENT_TYPES
SURFACE_DIRS = {
    "email": "raw/email",
    "chat": "raw/chat",
    "ticket": "raw/ticket",
    "ops_log": "raw/ops-log",
    "trade_csv": "raw/trade",
    "fix": "raw/fix",
    "meeting_note": "raw/meeting-note",
    "directory": "raw/directory",
    "reference_data": "raw/reference-data",
}

REFERENCE_DATA_PREDICATES = frozenset({
    "alias",
    "asset_class",
    "assigned_to",
    "authorized_event_types",
    "book",
    "booked_to",
    "canonical_label",
    "capability",
    "category",
    "client_of",
    "client_segment",
    "component_role",
    "concerns",
    "currency",
    "email",
    "employed_by",
    "employee_code",
    "employee_status",
    "end_date",
    "entity_kind",
    "environment",
    "for_client",
    "function",
    "has_title",
    "jurisdiction",
    "lifecycle_transition",
    "notional",
    "offers",
    "operated_by",
    "operating_model",
    "owned_by",
    "part_of",
    "part_of_team",
    "product_code",
    "region",
    "reports_to",
    "risk_tier",
    "role",
    "role_change",
    "seniority",
    "seniority_band",
    "serviced_by",
    "severity",
    "start_date",
    "supports",
    "team",
    "title",
    "trade_date",
    "traded_at",
    "uses_product",
    "venue_type",
})

# A span may support only predicates that its evidence role is designed to
# render literally. Exact values and relation targets are filtered separately.
EVIDENCE_ROLE_PREDICATES = {
    "chat.contradiction": frozenset({"lifecycle_transition"}),
    "chat.event": frozenset({"lifecycle_transition"}),
    "chat.format": frozenset(),
    "chat.noise": frozenset(),
    "directory.employee": frozenset({
        "alias", "canonical_label", "email", "employed_by", "employee_status",
        "has_title", "part_of_team", "reports_to", "seniority", "start_date",
        "team", "title",
    }),
    "directory.heading": frozenset(),
    "email.address_header": frozenset({"alias", "email"}),
    "email.date": frozenset(),
    "email.duplicate": frozenset({
        "alias", "email", "lifecycle_transition", "team", "title",
    }),
    "email.event": frozenset({
        "alias", "email", "lifecycle_transition", "team", "title",
    }),
    "email.forward_header": frozenset(),
    "email.missing_date": frozenset(),
    "email.noise": frozenset(),
    "email.subject": frozenset({"alias"}),
    "fix.execution_report": frozenset({"alias", "booked_to", "trade_date"}),
    "fix.new_order": frozenset({
        "alias", "booked_to", "currency", "notional", "trade_date",
    }),
    "meeting.catalog_heading": frozenset(),
    "meeting.catalog_product": frozenset({
        "alias", "canonical_label", "entity_kind", "product_code",
    }),
    "meeting.catalog_system": frozenset({
        "alias", "canonical_label", "capability", "entity_kind",
    }),
    "meeting.catalog_team": frozenset({"canonical_label", "entity_kind"}),
    "meeting.case": frozenset({"alias", "lifecycle_transition"}),
    "meeting.coverage_employment": frozenset({
        "alias", "canonical_label", "employed_by", "employee_status",
        "has_title", "part_of_team", "reports_to", "seniority", "start_date",
        "team", "title",
    }),
    "meeting.coverage_header": frozenset({"alias", "email"}),
    "meeting.coverage_inventory": frozenset({
        "alias", "canonical_label", "entity_kind",
    }),
    "meeting.coverage_prose": frozenset({"alias"}),
    "meeting.heading": frozenset(),
    "meeting.missing_date": frozenset(),
    "ops.event": frozenset({"lifecycle_transition"}),
    "reference_data.atom": REFERENCE_DATA_PREDICATES,
    "ticket.empty": frozenset(),
    "ticket.event": frozenset({"lifecycle_transition"}),
    "ticket.heading": frozenset({"canonical_label"}),
    "ticket.metadata": frozenset({
        "alias", "assigned_to", "category", "email", "title",
    }),
    "trade.header": frozenset(),
    "trade.row": frozenset({
        "alias", "booked_to", "currency", "for_client", "notional",
        "product_code", "trade_date", "uses_product",
    }),
}


@dataclass(frozen=True)
class GeneratorConfig:
    """Generation controls; all defaults are safe, deterministic and synthetic."""

    seed: int = 1729
    start_date: str = "2024-01-02"
    horizon_days: int = 120
    employee_count: int = 12
    client_count: int = 8
    accounts_per_client: int = 2
    trade_count: int = 36
    email_count: int = 24
    fix_message_count: int = 48
    exception_rate: float = 0.25
    duplicate_rate: float = 0.08
    contradiction_rate: float = 0.05
    missing_date_rate: float = 0.10
    noise_rate: float = 0.10

    def validate(self) -> None:
        date.fromisoformat(self.start_date)
        if self.horizon_days < 30:
            raise ValueError("horizon_days must be at least 30")
        if self.horizon_days < self.trade_count + 25:
            raise ValueError("horizon_days must cover trade_count plus 25 lifecycle days")
        if self.employee_count < 6:
            raise ValueError("employee_count must be at least 6")
        if self.client_count < 4:
            raise ValueError("client_count must be at least 4 for disjoint evaluation worlds")
        if self.trade_count < self.client_count:
            raise ValueError("trade_count must cover every client for evaluation partitioning")
        if min(
            self.accounts_per_client,
            self.trade_count,
            self.email_count,
            self.fix_message_count,
        ) < 1:
            raise ValueError(
                "accounts_per_client, trade_count, email_count and "
                "fix_message_count must be positive"
            )
        for field in (
            "exception_rate",
            "duplicate_rate",
            "contradiction_rate",
            "missing_date_rate",
            "noise_rate",
        ):
            value = getattr(self, field)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field} must be between 0 and 1")


def institution_scale_config(seed: int = 4181) -> GeneratorConfig:
    """Return the clean-room organisation scale used by the workbench.

    The 200-person floor comfortably exceeds the person-entity counts measured across the calibration profiles.  Only aggregate scale is borrowed: all names,
    values, scenarios and rendered bytes remain generated in the Ficta
    namespace.
    """

    return GeneratorConfig(
        seed=seed,
        start_date="2013-01-02",
        horizon_days=4_380,
        employee_count=200,
        client_count=75,
        accounts_per_client=3,
        trade_count=1_500,
        email_count=2_500,
        fix_message_count=4_500,
        exception_rate=0.30,
        duplicate_rate=0.08,
        contradiction_rate=0.05,
        missing_date_rate=0.10,
        noise_rate=0.10,
    )


class ArtifactBuilder:
    """Build an artefact and a complete, contiguous provenance partition."""

    def __init__(
        self,
        artifact_id: str,
        relative_path: str,
        surface: str,
        *,
        communication: dict[str, str | None] | None = None,
    ) -> None:
        self.artifact_id = artifact_id
        self.relative_path = relative_path
        self.surface = surface
        self.communication = dict(communication or {})
        self._chunks: list[str] = []
        self._span_specs: list[dict[str, Any]] = []

    def add(
        self,
        text: str,
        *,
        evidence_role: str,
        truth_atom_ids: Iterable[str] = (),
        kind: str = "format",
        transforms: Iterable[str] = (),
        assertion: str = "neutral",
    ) -> None:
        if not text:
            return
        if evidence_role not in EVIDENCE_ROLE_PREDICATES:
            raise ValueError(f"unknown evidence role: {evidence_role}")
        self._chunks.append(text)
        self._span_specs.append(
            {
                "text": text,
                "evidence_role": evidence_role,
                "truth_atom_ids": sorted(set(truth_atom_ids)),
                "kind": kind,
                "transforms": list(transforms),
                "assertion": assertion,
            }
        )

    def finish(
        self,
        *,
        duplicate_of: str | None = None,
        duplicate_kind: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        content = "".join(self._chunks)
        char_cursor = 0
        byte_cursor = 0
        spans: list[dict[str, Any]] = []
        for index, spec in enumerate(self._span_specs, start=1):
            text = spec.pop("text")
            encoded = text.encode("utf-8")
            span_id = f"{self.artifact_id}:span:{index:04d}"
            spans.append(
                {
                    "schema": "cleanroom.provenance-span/v1",
                    "span_id": span_id,
                    "artifact_id": self.artifact_id,
                    "relative_path": self.relative_path,
                    "char_start": char_cursor,
                    "char_end": char_cursor + len(text),
                    "byte_start": byte_cursor,
                    "byte_end": byte_cursor + len(encoded),
                    "text_sha256": _sha256(encoded),
                    **spec,
                }
            )
            char_cursor += len(text)
            byte_cursor += len(encoded)
        record = {
            "schema": ARTIFACT_SCHEMA,
            "artifact_id": self.artifact_id,
            "relative_path": self.relative_path,
            "surface": self.surface,
            "sha256": _sha256(content.encode("utf-8")),
            "bytes": len(content.encode("utf-8")),
            "characters": len(content),
            "span_count": len(spans),
            "duplicate_of": duplicate_of,
            "duplicate_kind": duplicate_kind,
        }
        if self.communication:
            record.update(self.communication)
        return content, spans, record


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_id(seed: int, kind: str, index: int | str) -> str:
    return str(uuid.uuid5(GENERATOR_NAMESPACE, f"{seed}:{kind}:{index}"))


def _communication_thread_id(seed: int, thread_root_id: str) -> str:
    """Return the source-assigned thread key for a business root.

    This is called while the hidden world is rendered, before artefact bytes or
    provenance records exist.  It is therefore a generation fact rather than a
    subject-line or post-hoc clustering inference.
    """

    return "urn:ficta:thread:" + _stable_id(seed, "communication-thread", thread_root_id)


def _communication_message_id(seed: int, artifact_id: str) -> str:
    """Return the source-assigned communication-envelope identifier."""

    stable_id = _stable_id(seed, "communication-message", artifact_id)
    return f"urn.ficta.message.{stable_id}@messages.ficta.invalid"


def _render_near_duplicate_email(
    source_text: str,
    *,
    message_id: str,
    thread_id: str,
    parent_message_id: str,
) -> str:
    """Transform one generated email into one valid forwarded-message envelope.

    A near duplicate is a new message in the source message's thread, not a
    preamble followed by a second email envelope.  Parse the generated source
    before transforming it, retain every unrelated header, replace the source
    identity fields in place, and add forwarding detail to the body.
    """

    message = Parser(policy=policy.default).parsestr(source_text)
    defects = list(message.defects)
    for header in message.values():
        defects.extend(getattr(header, "defects", ()))
    if defects:
        raise ValueError(
            "cannot derive a near duplicate from a malformed email: "
            + ", ".join(type(defect).__name__ for defect in defects)
        )
    for name in (
        "From",
        "To",
        "Message-ID",
        "Thread-ID",
        "Conversation-ID",
        "Subject",
    ):
        if len(message.get_all(name, [])) != 1:
            raise ValueError(
                f"cannot derive a near duplicate without exactly one {name} header"
            )

    _header_text, separator, body = source_text.partition("\n\n")
    if not separator:
        raise ValueError("cannot derive a near duplicate without a header/body boundary")

    replacements = {
        "message-id": f"<{message_id}>",
        "thread-id": thread_id,
        "conversation-id": thread_id,
    }
    transformed_headers: list[str] = []
    reply_inserted = False
    for name, raw_value in message.raw_items():
        key = name.casefold()
        if key == "in-reply-to":
            continue
        if key == "subject":
            raw_value = f"Fwd: {raw_value}"
        elif key in replacements:
            raw_value = replacements[key]
        transformed_headers.append(f"{name}: {raw_value}")
        if key == "conversation-id":
            transformed_headers.append(f"In-Reply-To: <{parent_message_id}>")
            reply_inserted = True
    if not reply_inserted:
        transformed_headers.append(f"In-Reply-To: <{parent_message_id}>")
    transformed_headers.append(
        "X-Synthetic-Transform: forwarded copy; punctuation normalized"
    )
    transformed_body = (
        "Forwarded synthetic copy — punctuation normalized.\n\n"
        + body.replace("Operations recorded", "Ops recorded")
    )
    return "\n".join(transformed_headers) + "\n\n" + transformed_body


def _iso_day(start: date, offset: int, hour: int = 9, minute: int = 0) -> str:
    moment = datetime.combine(start + timedelta(days=offset), datetime.min.time())
    moment = moment.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _shift_timestamp(value: str, *, minutes: int) -> str:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (moment + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _deterministic_delay_minutes(
    seed: int,
    event_id: str,
    clock: str,
    minimum: int,
    maximum: int,
) -> int:
    """Return a stable, non-periodic delay without consuming generator RNG."""

    payload = f"{seed}:{event_id}:{clock}".encode("utf-8")
    integer = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return minimum + integer % (maximum - minimum + 1)


def _event_time(event: dict[str, Any]) -> str:
    """Return the business-event timestamp, accepting legacy replay input."""

    return str(event.get("event_time") or event["occurred_at"])


def _authorized_event_types(function: str) -> list[str]:
    allowed = {
        event_type
        for event_type, functions in EVENT_FUNCTIONS.items()
        if function in functions
    }
    if function in CASE_FUNCTIONS.values():
        allowed.update(CASE_EVENT_TYPES)
    if function == "Operations Leadership":
        allowed.update(ALL_EVENT_TYPES)
    return sorted(allowed)


def materialize_state(
    lifecycle_events: Iterable[dict[str, Any]], as_of: str | None = None
) -> dict[str, str]:
    """Replay lifecycle transitions and return entity state at a point in time."""

    cutoff = datetime.max.replace(tzinfo=timezone.utc)
    if as_of:
        cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    state: dict[str, str] = {}
    ordered = sorted(lifecycle_events, key=lambda item: (_event_time(item), item["event_id"]))
    for event in ordered:
        when = datetime.fromisoformat(_event_time(event).replace("Z", "+00:00"))
        if when > cutoff:
            continue
        subject = event["subject_id"]
        expected = event["state_before"]
        if subject not in state and expected is not None:
            # Some subjects, such as employees, enter the event ledger with a
            # state established before the observation window.
            state[subject] = expected
        actual = state.get(subject)
        if expected is not None and actual != expected:
            raise ValueError(
                f"invalid transition for {subject}: expected {expected!r}, got {actual!r}"
            )
        state[subject] = event["state_after"]
    return state


class SyntheticCorpusGenerator:
    """Create hidden truth, lifecycle state, raw surfaces and provenance."""

    def __init__(self, config: GeneratorConfig) -> None:
        config.validate()
        self.config = config
        self.rng = random.Random(config.seed)
        self.start = date.fromisoformat(config.start_date)
        self.entities: list[dict[str, Any]] = []
        self.relations: list[dict[str, Any]] = []
        self.atoms: list[dict[str, Any]] = []
        self.lifecycle: list[dict[str, Any]] = []
        self._entity_by_id: dict[str, dict[str, Any]] = {}
        self._atom_by_id: dict[str, dict[str, Any]] = {}
        self._atoms_by_subject: dict[str, list[str]] = {}
        self._events_by_subject: dict[str, list[dict[str, Any]]] = {}

    def generate(self, output_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
        self._reset()
        output_dir = output_dir.resolve()
        if output_dir.exists():
            if not overwrite:
                raise FileExistsError(f"output exists: {output_dir}")
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)

        self._build_world()
        self.lifecycle.sort(
            key=lambda item: (_event_time(item), item["event_id"])
        )
        for events in self._events_by_subject.values():
            events.sort(key=lambda item: (_event_time(item), item["event_id"]))
        materialized = materialize_state(self.lifecycle)
        world = {
            "schema": SCHEMA_VERSION,
            "classification": CLASSIFICATION,
            "seed": self.config.seed,
            "config": asdict(self.config),
            "institution": self._find_kind("institution")[0]["entity_id"],
            "entities": self.entities,
            "relations": self.relations,
            "lifecycle_events": self.lifecycle,
            "materialized_state": materialized,
        }
        self._write_text(output_dir / "hidden" / "world.json", _canonical_json(world, pretty=True))
        self._write_jsonl(output_dir / "hidden" / "truth_atoms.jsonl", self.atoms)
        self._write_jsonl(output_dir / "hidden" / "lifecycle_events.jsonl", self.lifecycle)

        artifacts, spans = self._render_surfaces(output_dir)
        self._write_jsonl(output_dir / "provenance" / "artifacts.jsonl", artifacts)
        self._write_jsonl(output_dir / "provenance" / "spans.jsonl", spans)
        communication_artifacts = [
            artifact
            for artifact in artifacts
            if artifact["surface"] in COMMUNICATION_SURFACES
        ]

        ontology = self._ontology_contract()
        self._write_text(
            output_dir / "contracts" / "ontology_contract.json",
            _canonical_json(ontology, pretty=True),
        )
        controls = self._controls(artifacts, spans)
        self._write_text(
            output_dir / "controls" / "injections.json",
            _canonical_json(controls, pretty=True),
        )
        from .eval_export import export_evaluation_bridge

        evaluation_counts = export_evaluation_bridge(output_dir)

        file_records = []
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                payload = path.read_bytes()
                file_records.append(
                    {
                        "path": path.relative_to(output_dir).as_posix(),
                        "sha256": _sha256(payload),
                        "bytes": len(payload),
                    }
                )
        corpus_digest = _sha256(_canonical_json(file_records).encode("utf-8"))
        manifest = {
            "schema": "cleanroom.corpus-manifest/v1",
            "classification": CLASSIFICATION,
            "license_posture": "wholly-synthetic-no-source-derived-content",
            "external_context": {
                "classification": "PUBLIC_EXTERNAL_CONTEXT",
                "included_in_synthetic_corpus": False,
                "synthetic_market_events": 0,
                "join_policy": "date-overlay-at-query-and-render-time",
                "requirement": (
                    "External market incidents must resolve to an independently "
                    "provenanced public timeline and must never be generated."
                ),
            },
            "generator": "cleanroom_corpus.SyntheticCorpusGenerator",
            "seed": self.config.seed,
            "deterministic_generated_at": _iso_day(self.start, 0, 0, 0),
            "corpus_sha256": corpus_digest,
            "communication_contract": {
                "schema": COMMUNICATION_CONTRACT_SCHEMA,
                "artifact_schema": ARTIFACT_SCHEMA,
                "assignment_phase": "hidden-world-render-before-artifact-bytes",
                "thread_scope": "focal-business-root",
                "thread_id_algorithm": (
                    "urn:ficta:thread:uuid5(generator-namespace,"
                    " seed:communication-thread:thread-root-id)"
                ),
                "conversation_id_rule": "exact-alias-of-thread-id",
                "message_id_algorithm": (
                    "urn.ficta.message.uuid5(generator-namespace,"
                    " seed:communication-message:artifact-id)@messages.ficta.invalid"
                ),
                "duplicate_lineage": {
                    "exact": "same-message-id-and-thread-as-source",
                    "near": "new-message-id-replying-to-source-in-same-thread",
                },
                "surfaces": sorted(COMMUNICATION_SURFACES),
            },
            "counts": {
                "entities": len(self.entities),
                "people": len(self._find_kind("person")),
                "clients": len(self._find_kind("client")),
                "accounts": len(self._find_kind("account")),
                "trades": len(self._find_kind("trade")),
                "tickets": len(self._find_kind("case")),
                "relations": len(self.relations),
                "truth_atoms": len(self.atoms),
                "lifecycle_events": len(self.lifecycle),
                "artifacts": len(artifacts),
                "email_messages": self.config.email_count,
                "fix_messages": self.config.fix_message_count,
                "communication_artifacts": len(communication_artifacts),
                "communication_messages": len({
                    artifact["message_id"] for artifact in communication_artifacts
                }),
                "communication_threads": len({
                    artifact["thread_id"] for artifact in communication_artifacts
                }),
                "provenance_spans": len(spans),
                **evaluation_counts,
            },
            "surfaces": sorted({record["surface"] for record in artifacts}),
            "controls": controls["counts"],
            "files": file_records,
        }
        self._write_text(
            output_dir / "manifest.json",
            _canonical_json(manifest, pretty=True),
        )
        return manifest

    def _reset(self) -> None:
        """Make a generator instance safely reusable without accumulating state."""

        self.rng = random.Random(self.config.seed)
        self.entities.clear()
        self.relations.clear()
        self.atoms.clear()
        self.lifecycle.clear()
        self._entity_by_id.clear()
        self._atom_by_id.clear()
        self._atoms_by_subject.clear()
        self._events_by_subject.clear()

    def _employee_is_active(self, employee: dict[str, Any], day_offset: int) -> bool:
        attributes = employee["attributes"]
        event_day = self.start + timedelta(days=day_offset)
        start_day = date.fromisoformat(attributes["start_date"])
        end_value = attributes.get("end_date")
        end_day = date.fromisoformat(end_value) if end_value else None
        return start_day <= event_day and (end_day is None or event_day <= end_day)

    def _select_actor(
        self,
        event_type: str,
        day_offset: int,
        *,
        preferred_function: str,
        salt: int,
        exclude_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        excluded = set(exclude_ids)
        candidates = [
            employee
            for employee in self._find_kind("person")
            if employee["entity_id"] not in excluded
            if employee["attributes"]["team"]
            == f"Ficta {preferred_function} Team"
            and event_type in employee["attributes"]["authorized_event_types"]
            and self._employee_is_active(employee, day_offset)
        ]
        if not candidates:
            # Compact fixture worlds cannot populate all twenty operating
            # functions. Their COO is deliberately cross-authorized so the
            # same guarded event path remains available without fabricating an
            # inactive specialist.
            candidates = [
                employee
                for employee in self._find_kind("person")
                if employee["entity_id"] not in excluded
                if event_type in employee["attributes"]["authorized_event_types"]
                and self._employee_is_active(employee, day_offset)
            ]
        if not candidates:
            raise ValueError(
                f"no active actor authorized for {event_type} in "
                f"{preferred_function!r} on day {day_offset}"
            )
        return candidates[salt % len(candidates)]

    def _build_world(self) -> None:
        institution = self._entity(
            "institution",
            1,
            "Ficta Meridian Bank 001",
            aliases=["FMB001", "the synthetic bank"],
            attributes={"jurisdiction": "XZ", "operating_model": "capital-markets-operations"},
        )

        teams = [
            self._entity(
                "team",
                index,
                f"Ficta {function} Team",
                aliases=[f"FTEAM{index:02d}", function],
                attributes={"function": function.casefold().replace(" ", "-")},
            )
            for index, function in enumerate(OPERATING_FUNCTIONS, start=1)
        ]
        positions: dict[tuple[str, str], dict[str, Any]] = {}
        employees = []
        for index in range(1, self.config.employee_count + 1):
            function_index = (index - 1) % len(OPERATING_FUNCTIONS)
            function = OPERATING_FUNCTIONS[function_index]
            team = teams[function_index]
            cohort = (index - 1) // len(OPERATING_FUNCTIONS)
            seniority_label, seniority_band = SENIORITY[min(cohort, len(SENIORITY) - 1)]
            if index == 1:
                title = "Chief Operations Officer"
            elif cohort == 0:
                title = f"Director, {function}"
                seniority_label, seniority_band = "Director", 4
            else:
                title = f"{seniority_label}, {function}"
            given = GIVEN_NAMES[(index - 1) % len(GIVEN_NAMES)]
            family = FAMILY_NAMES[((index - 1) // len(GIVEN_NAMES)) % len(FAMILY_NAMES)]
            canonical_name = f"Ficta {given} {family}"
            email = f"{given}.{family}{index:03d}@ficta.example".casefold()
            # Every operating function has one incumbent at the start of the
            # generated observation window. Later cohorts join during the
            # world, allowing temporal employment checks without leaving early
            # work ownerless or inventing pre-employment activity.
            if cohort == 0:
                # The COO must be employed before every direct report. Later
                # cohorts report to the same function's initial incumbent.
                start_offset = -(
                    365 + (len(OPERATING_FUNCTIONS) - function_index) * 17
                )
            else:
                start_window = max(
                    1,
                    min(self.config.horizon_days // 2, 1_825),
                )
                start_offset = 1 + ((index * 37) % start_window)
            position_key = (title, seniority_label)
            position = positions.get(position_key)
            if position is None:
                position = self._entity(
                    "position",
                    len(positions) + 1,
                    f"Ficta {title}",
                    aliases=[title],
                    attributes={
                        "seniority": seniority_label,
                        "seniority_band": seniority_band,
                        "function": function,
                    },
                )
                positions[position_key] = position
            employee = self._entity(
                "person",
                index,
                canonical_name,
                aliases=[
                    f"fp{index:03d}",
                    f"person-{index:03d}",
                    f"{given} {family}",
                ],
                attributes={
                    "employee_code": f"FEMP{index:04d}",
                    "email": email,
                    "employee_status": "Current",
                    "role": title,
                    "title": title,
                    "team": team["canonical_label"],
                    "seniority": seniority_label,
                    "seniority_band": seniority_band,
                    "start_date": (
                        self.start + timedelta(days=start_offset)
                    ).isoformat(),
                    "end_date": None,
                    "region": ("EMEA", "AMER", "APAC")[(index - 1) % 3],
                    "authorized_event_types": (
                        sorted(ALL_EVENT_TYPES)
                        if index == 1
                        else _authorized_event_types(function)
                    ),
                },
            )
            employment_valid_from = _iso_day(
                self.start, start_offset, 0, 0
            )
            for atom_id in self._atoms_by_subject[employee["entity_id"]]:
                atom = self._atom_by_id[atom_id]
                if atom["predicate"] in {
                    "role", "title", "seniority", "seniority_band"
                }:
                    atom["valid_from"] = employment_valid_from
            employees.append(employee)
            self._relation(employee, "employed_by", institution, confidence=1.0)
            self._relation(employee, "part_of_team", team, confidence=1.0)
            self._relation(
                employee,
                "has_title",
                position,
                confidence=1.0,
                valid_from=employment_valid_from,
            )
            if index > 1:
                manager = employees[0] if cohort == 0 else employees[function_index]
                self._relation(employee, "reports_to", manager, confidence=1.0)

        products = []
        for index, (code, label) in enumerate(PRODUCTS, start=1):
            product = self._entity(
                "product",
                index,
                f"Ficta Product {index:02d}: {label}",
                aliases=[code, f"FPD{index:02d}"],
                attributes={"product_code": code, "asset_class": "capital-markets"},
            )
            products.append(product)
            self._relation(institution, "offers", product, confidence=1.0)

        systems = []
        for index, capability in enumerate(SYSTEM_CAPABILITIES, start=1):
            system = self._entity(
                "system",
                index,
                f"Ficta System {index:02d}: {capability}",
                aliases=[f"FSYS{index:02d}", capability.lower().replace(" ", "-")],
                attributes={"capability": capability, "environment": "synthetic-production"},
            )
            systems.append(system)
            self._relation(system, "operated_by", institution, confidence=1.0)
            self._relation(system, "supports", products[(index - 1) % len(products)], confidence=1.0)

        clients = []
        accounts = []
        for client_index in range(1, self.config.client_count + 1):
            client = self._entity(
                "client",
                client_index,
                f"Ficta Client {client_index:03d}",
                aliases=[f"FC{client_index:03d}", f"client-{client_index:03d}"],
                attributes={
                    "client_segment": ("fund", "asset-manager", "corporate")[
                        (client_index - 1) % 3
                    ],
                    "risk_tier": 1 + ((client_index - 1) % 3),
                },
            )
            clients.append(client)
            self._relation(client, "client_of", institution, confidence=1.0)
            onboarding_day = 1 + client_index
            self._lifecycle_event(
                client,
                "client_onboarded",
                None,
                "active",
                onboarding_day,
                actor=self._select_actor(
                    "client_onboarded",
                    onboarding_day,
                    preferred_function="Client Service",
                    salt=client_index,
                ),
                object_ids=[institution["entity_id"]],
            )
            for account_offset in range(self.config.accounts_per_client):
                account_index = (client_index - 1) * self.config.accounts_per_client + account_offset + 1
                account = self._entity(
                    "account",
                    account_index,
                    f"Ficta Account {account_index:04d}",
                    aliases=[f"FACC{account_index:04d}"],
                    attributes={
                        "currency": ("USD", "EUR", "GBP")[(account_index - 1) % 3],
                        "book": f"FBK{1000 + account_index}",
                    },
                )
                accounts.append(account)
                self._relation(account, "owned_by", client, confidence=1.0)
                self._relation(account, "serviced_by", institution, confidence=1.0)
                proposed_day = 2 + client_index
                activated_day = 4 + client_index
                self._lifecycle_event(
                    account,
                    "account_proposed",
                    None,
                    "proposed",
                    proposed_day,
                    actor=self._select_actor(
                        "account_proposed",
                        proposed_day,
                        preferred_function="Client Service",
                        salt=account_index,
                    ),
                    object_ids=[client["entity_id"]],
                )
                self._lifecycle_event(
                    account,
                    "account_activated",
                    "proposed",
                    "active",
                    activated_day,
                    actor=self._select_actor(
                        "account_activated",
                        activated_day,
                        preferred_function="Reference Data",
                        salt=account_index,
                    ),
                    object_ids=[client["entity_id"]],
                )

        tickets: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        for index in range(1, self.config.trade_count + 1):
            trade_day = 10 + round(
                (index - 1)
                * max(1, self.config.horizon_days - 40)
                / max(1, self.config.trade_count - 1)
            )
            client_index = (index - 1) % len(clients)
            account_offset = (
                (index - 1) // len(clients)
            ) % self.config.accounts_per_client
            account = accounts[
                client_index * self.config.accounts_per_client + account_offset
            ]
            client_id = self._relation_target(account["entity_id"], "owned_by")
            client = self._entity_by_id[client_id]
            product = products[(index - 1) % len(products)]
            trade = self._entity(
                "trade",
                index,
                f"Ficta Trade {index:05d}",
                aliases=[f"FTRD{index:05d}"],
                attributes={
                    "notional": 1_000_000 + index * 125_000,
                    "currency": account["attributes"]["currency"],
                    "trade_date": (self.start + timedelta(days=trade_day)).isoformat(),
                },
            )
            trades.append(trade)
            self._relation(trade, "for_client", client, confidence=1.0)
            self._relation(trade, "booked_to", account, confidence=1.0)
            self._relation(trade, "uses_product", product, confidence=1.0)
            self._lifecycle_event(
                trade,
                "trade_booked",
                None,
                "booked",
                trade_day,
                actor=self._select_actor(
                    "trade_booked",
                    trade_day,
                    preferred_function="Trade Capture Operations",
                    salt=index,
                ),
            )
            self._lifecycle_event(
                trade,
                "trade_confirmed",
                "booked",
                "confirmed",
                trade_day + 1,
                actor=self._select_actor(
                    "trade_confirmed",
                    trade_day + 1,
                    preferred_function="Confirmations",
                    salt=index,
                ),
            )
            has_exception = self.rng.random() < self.config.exception_rate
            if has_exception:
                category = CASE_CATEGORIES[(index - 1) % len(CASE_CATEGORIES)]
                ticket = self._entity(
                    "case",
                    len(tickets) + 1,
                    f"Ficta Case {len(tickets) + 1:04d}",
                    aliases=[f"FCASE{len(tickets) + 1:04d}"],
                    attributes={
                        "severity": 1 + (index % 3),
                        "category": category,
                    },
                )
                tickets.append(ticket)
                self._relation(ticket, "concerns", trade, confidence=1.0)
                owner = self._select_actor(
                    "case_opened",
                    trade_day + 2,
                    preferred_function=CASE_FUNCTIONS[category],
                    salt=index,
                )
                self._relation(ticket, "assigned_to", owner, confidence=1.0)
                exception_event = self._lifecycle_event(
                    trade,
                    "trade_exception",
                    "confirmed",
                    "exception",
                    trade_day + 2,
                    actor=owner,
                    object_ids=[ticket["entity_id"]],
                )
                self._lifecycle_event(
                    ticket,
                    "case_opened",
                    None,
                    "open",
                    trade_day + 2,
                    actor=owner,
                    object_ids=[trade["entity_id"]],
                    not_before=exception_event["recorded_at"],
                )
                self._lifecycle_event(
                    ticket,
                    "case_investigating",
                    "open",
                    "investigating",
                    trade_day + 4,
                    actor=owner,
                    object_ids=[trade["entity_id"]],
                )
                self._lifecycle_event(
                    ticket,
                    "case_resolved",
                    "investigating",
                    "resolved",
                    trade_day + 8,
                    actor=owner,
                    object_ids=[trade["entity_id"]],
                )
                self._lifecycle_event(
                    trade,
                    "trade_settled",
                    "exception",
                    "settled",
                    trade_day + 9,
                    actor=self._select_actor(
                        "trade_settled",
                        trade_day + 9,
                        preferred_function="Settlements",
                        salt=index,
                    ),
                )
            else:
                self._lifecycle_event(
                    trade,
                    "trade_settled",
                    "confirmed",
                    "settled",
                    trade_day + 3,
                    actor=self._select_actor(
                        "trade_settled",
                        trade_day + 3,
                        preferred_function="Settlements",
                        salt=index,
                    ),
                )

        transfer_employee = next(
            employee
            for employee in reversed(employees)
            if int(employee["attributes"]["seniority_band"]) < 5
        )
        transfer_start_offset = (
            date.fromisoformat(transfer_employee["attributes"]["start_date"])
            - self.start
        ).days
        role_change_day = min(
            self.config.horizon_days - 1,
            max(75, transfer_start_offset + 30),
        )
        transfer_attributes = transfer_employee["attributes"]
        old_role = str(transfer_attributes["role"])
        old_title = str(transfer_attributes["title"])
        old_seniority = str(transfer_attributes["seniority"])
        old_band = int(transfer_attributes["seniority_band"])
        function = (
            str(transfer_attributes["team"])
            .removeprefix("Ficta ")
            .removesuffix(" Team")
        )
        new_seniority, new_band = (
            ("Director", 4)
            if old_band < 4
            else ("Managing Director", 5)
        )
        new_title = f"{new_seniority}, {function}"
        new_role = new_title
        role_event = self._lifecycle_event(
            transfer_employee,
            "employee_role_changed",
            old_role,
            new_role,
            role_change_day,
            actor=self._select_actor(
                "employee_role_changed",
                role_change_day,
                preferred_function="Operations Leadership",
                salt=len(employees),
                exclude_ids=[transfer_employee["entity_id"]],
            ),
            object_ids=[institution["entity_id"]],
        )
        effective_at = role_event["effective_at"]
        old_values = {
            "role": old_role,
            "title": old_title,
            "seniority": old_seniority,
            "seniority_band": old_band,
        }
        new_values = {
            "role": new_role,
            "title": new_title,
            "seniority": new_seniority,
            "seniority_band": new_band,
        }
        role_atom_ids: list[str] = []
        for predicate, old_value in old_values.items():
            matching_old_atoms = [
                self._atom_by_id[atom_id]
                for atom_id in self._atoms_by_subject[transfer_employee["entity_id"]]
                if self._atom_by_id[atom_id]["predicate"] == predicate
                and self._atom_by_id[atom_id]["value"] == old_value
                and self._atom_by_id[atom_id]["valid_to"] is None
            ]
            if len(matching_old_atoms) != 1:
                raise ValueError(
                    f"expected one current {predicate} atom for "
                    f"{transfer_employee['entity_id']}, got {len(matching_old_atoms)}"
                )
            matching_old_atoms[0]["valid_to"] = effective_at
            role_atom_ids.append(matching_old_atoms[0]["truth_atom_id"])
            role_atom_ids.append(
                self._atom(
                    transfer_employee["entity_id"],
                    predicate,
                    new_values[predicate],
                    confidence=1.0,
                    valid_from=effective_at,
                )
            )
        role_atom_ids.append(
            self._atom(
                transfer_employee["entity_id"],
                "role_change",
                {
                    "from": old_role,
                    "to": new_role,
                    "title_from": old_title,
                    "title_to": new_title,
                    "seniority_from": old_seniority,
                    "seniority_to": new_seniority,
                    "seniority_band_from": old_band,
                    "seniority_band_to": new_band,
                },
                confidence=1.0,
                valid_from=effective_at,
            )
        )
        role_event["truth_atom_ids"] = sorted(
            set(role_event["truth_atom_ids"] + role_atom_ids)
        )
        transfer_attributes.update(new_values)

        new_position_key = (new_title, new_seniority)
        new_position = positions.get(new_position_key)
        if new_position is None:
            new_position = self._entity(
                "position",
                len(positions) + 1,
                f"Ficta {new_title}",
                aliases=[new_title],
                attributes={
                    "seniority": new_seniority,
                    "seniority_band": new_band,
                    "function": function,
                },
            )
            positions[new_position_key] = new_position
        current_title_relations = [
            relation
            for relation in self.relations
            if relation["source_id"] == transfer_employee["entity_id"]
            and relation["predicate"] == "has_title"
        ]
        if len(current_title_relations) != 1:
            raise ValueError(
                f"expected one current title relation for "
                f"{transfer_employee['entity_id']}"
            )
        current_title_relation = current_title_relations[0]
        current_title_relation["valid_to"] = effective_at
        current_title_atom = self._atom_by_id[
            current_title_relation["truth_atom_id"]
        ]
        current_title_atom["valid_to"] = effective_at
        new_title_relation = self._relation(
            transfer_employee,
            "has_title",
            new_position,
            confidence=1.0,
            valid_from=effective_at,
        )
        role_event["truth_atom_ids"] = sorted(
            set(
                role_event["truth_atom_ids"]
                + [
                    current_title_relation["truth_atom_id"],
                    new_title_relation["truth_atom_id"],
                ]
            )
        )

        # These are ordinary operational concepts, not synthetic-only graph
        # shortcuts. They exist in hidden truth and are rendered as explicit
        # source observations for the same ontology-driven extractor used on
        # unfamiliar corpora.
        team = teams[0]
        position = next(iter(positions.values()))
        component = self._entity(
            "component", 1, "Ficta Reconciliation Adapter",
            aliases=["FictaReconAdapter"],
            attributes={"component_role": "reconciliation"},
        )
        venue = self._entity(
            "venue", 1, "Ficta Execution Venue",
            aliases=["FictaVenue"],
            attributes={"venue_type": "electronic"},
        )
        self._relation(component, "part_of", systems[0], confidence=1.0)
        self._relation(products[0], "traded_at", venue, confidence=1.0)

    def _entity(
        self,
        kind: str,
        index: int,
        label: str,
        *,
        aliases: list[str],
        attributes: dict[str, Any],
    ) -> dict[str, Any]:
        entity_id = _stable_id(self.config.seed, kind, index)
        entity = {
            "entity_id": entity_id,
            "kind": kind,
            "canonical_label": label,
            "aliases": aliases,
            "attributes": attributes,
            "synthetic": True,
        }
        self.entities.append(entity)
        self._entity_by_id[entity_id] = entity
        self._atom(entity_id, "entity_kind", kind, confidence=1.0)
        self._atom(entity_id, "canonical_label", label, confidence=1.0)
        for key, value in sorted(attributes.items()):
            self._atom(entity_id, key, value, confidence=1.0)
        for alias in aliases:
            self._atom(entity_id, "alias", alias, confidence=1.0)
        return entity

    def _relation(
        self,
        source: dict[str, Any],
        predicate: str,
        target: dict[str, Any],
        *,
        confidence: float,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> dict[str, Any]:
        relation_index = len(self.relations) + 1
        relation_id = _stable_id(self.config.seed, "relation", relation_index)
        atom_id = self._atom(
            source["entity_id"],
            predicate,
            target["entity_id"],
            confidence=confidence,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        relation = {
            "relation_id": relation_id,
            "source_id": source["entity_id"],
            "predicate": predicate,
            "target_id": target["entity_id"],
            "confidence": confidence,
            "truth_atom_id": atom_id,
            "valid_from": valid_from,
            "valid_to": valid_to,
        }
        self.relations.append(relation)
        return relation

    def _atom(
        self,
        subject_id: str,
        predicate: str,
        value: Any,
        *,
        confidence: float,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> str:
        atom_index = len(self.atoms) + 1
        atom_id = _stable_id(self.config.seed, "atom", atom_index)
        atom = {
            "schema": "cleanroom.truth-atom/v1",
            "truth_atom_id": atom_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "value": value,
            "confidence": confidence,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "classification": CLASSIFICATION,
        }
        self.atoms.append(atom)
        self._atom_by_id[atom_id] = atom
        self._atoms_by_subject.setdefault(subject_id, []).append(atom_id)
        return atom_id

    def _select_atom_ids(
        self,
        subject_id: str,
        predicates: Iterable[str],
        *,
        exact_values: dict[str, Iterable[Any]] | None = None,
    ) -> list[str]:
        """Select stable subject atoms by predicate and, where needed, value.

        Exact-value constraints are mandatory at call sites for repeated
        aliases and relations so a visible value cannot support unseen values
        that happen to share its predicate.
        """
        allowed = frozenset(str(predicate) for predicate in predicates)
        values = {
            str(predicate): tuple(expected)
            for predicate, expected in (exact_values or {}).items()
        }
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError(
                f"exact-value constraints are outside predicate selection: "
                f"{sorted(unexpected)}"
            )
        selected: list[str] = []
        for atom_id in self._atoms_by_subject.get(subject_id, ()):
            atom = self._atom_by_id[atom_id]
            predicate = str(atom["predicate"])
            if predicate not in allowed:
                continue
            if predicate in values and not any(
                atom["value"] == expected for expected in values[predicate]
            ):
                continue
            selected.append(atom_id)
        return selected

    def _evidence_atoms(
        self,
        evidence_role: str,
        subject_id: str,
        predicates: Iterable[str],
        *,
        exact_values: dict[str, Iterable[Any]] | None = None,
    ) -> list[str]:
        """Apply a role contract before selecting text-supported subject atoms."""
        role_predicates = EVIDENCE_ROLE_PREDICATES.get(evidence_role)
        if role_predicates is None:
            raise ValueError(f"unknown evidence role: {evidence_role}")
        requested = frozenset(str(predicate) for predicate in predicates)
        unsupported = requested - role_predicates
        if unsupported:
            raise ValueError(
                f"{evidence_role} cannot support predicates: {sorted(unsupported)}"
            )
        return self._select_atom_ids(
            subject_id,
            requested,
            exact_values=exact_values,
        )

    def _evidence_atom_ids(
        self,
        evidence_role: str,
        atom_ids: Iterable[str],
        predicates: Iterable[str],
    ) -> list[str]:
        """Filter explicit atom IDs through the same evidence-role contract."""
        role_predicates = EVIDENCE_ROLE_PREDICATES.get(evidence_role)
        if role_predicates is None:
            raise ValueError(f"unknown evidence role: {evidence_role}")
        requested = frozenset(str(predicate) for predicate in predicates)
        unsupported = requested - role_predicates
        if unsupported:
            raise ValueError(
                f"{evidence_role} cannot support predicates: {sorted(unsupported)}"
            )
        return [
            atom_id
            for atom_id in atom_ids
            if self._atom_by_id[atom_id]["predicate"] in requested
        ]

    def _lifecycle_event(
        self,
        subject: dict[str, Any],
        event_type: str,
        state_before: str | None,
        state_after: str,
        day_offset: int,
        *,
        actor: dict[str, Any],
        object_ids: list[str] | None = None,
        truth_atom_ids: list[str] | None = None,
        enforce_state: bool = True,
        not_before: str | None = None,
    ) -> dict[str, Any]:
        event_index = len(self.lifecycle) + 1
        event_id = _stable_id(self.config.seed, "event", event_index)
        event_time = _iso_day(
            self.start,
            day_offset,
            9 + event_index % 8,
            event_index % 60,
        )
        if not_before is not None:
            floor = _shift_timestamp(not_before, minutes=1)
            if datetime.fromisoformat(event_time.replace("Z", "+00:00")) < (
                datetime.fromisoformat(floor.replace("Z", "+00:00"))
            ):
                event_time = floor
        effective_at = _shift_timestamp(
            event_time,
            minutes=-_deterministic_delay_minutes(
                self.config.seed,
                event_id,
                "effective",
                0,
                60,
            ),
        )
        observed_at = _shift_timestamp(
            event_time,
            minutes=_deterministic_delay_minutes(
                self.config.seed,
                event_id,
                "observed",
                1,
                720,
            ),
        )
        recorded_at = _shift_timestamp(
            observed_at,
            minutes=_deterministic_delay_minutes(
                self.config.seed,
                event_id,
                "recorded",
                1,
                240,
            ),
        )
        atom_id = self._atom(
            subject["entity_id"],
            "lifecycle_transition",
            {
                "event_type": event_type,
                "state_before": state_before,
                "state_after": state_after,
            },
            confidence=1.0,
            valid_from=effective_at,
        )
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "actor_id": actor["entity_id"],
            "event_time": event_time,
            "observed_at": observed_at,
            "recorded_at": recorded_at,
            "effective_at": effective_at,
            # Retained as a strict alias for consumers of lifecycle-event/v1.
            "occurred_at": event_time,
            "subject_id": subject["entity_id"],
            "object_ids": object_ids or [],
            "state_before": state_before if enforce_state else None,
            "state_after": state_after,
            "truth_atom_ids": sorted(set((truth_atom_ids or []) + [atom_id])),
        }
        self.lifecycle.append(event)
        self._events_by_subject.setdefault(subject["entity_id"], []).append(event)
        return event

    def _render_surfaces(
        self, output_dir: Path
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        artifacts: list[dict[str, Any]] = []
        spans: list[dict[str, Any]] = []
        builders: list[ArtifactBuilder] = []

        people = self._find_kind("person")
        institution = self._find_kind("institution")[0]
        directory_page_size = 50
        for page_index in range(math.ceil(len(people) / directory_page_size)):
            directory = self._builder("directory", page_index + 1, "txt")
            directory.add(
                "# Ficta Meridian Bank employee directory\n\n",
                evidence_role="directory.heading",
                kind="format",
            )
            for person in people[
                page_index * directory_page_size : (page_index + 1) * directory_page_size
            ]:
                display_name = person["aliases"][2]
                manager_ids = [
                    relation["target_id"]
                    for relation in self.relations
                    if relation["source_id"] == person["entity_id"]
                    and relation["predicate"] == "reports_to"
                ]
                manager = self._entity_by_id[manager_ids[0]] if manager_ids else None
                team_id = self._relation_target(person["entity_id"], "part_of_team")
                position_id = self._relation_target(person["entity_id"], "has_title")
                team = self._entity_by_id[team_id]
                position = self._entity_by_id[position_id]
                attributes = person["attributes"]
                person_predicates = {
                    "alias", "email", "employee_status", "employed_by",
                    "has_title", "part_of_team", "seniority", "start_date",
                    "team", "title",
                }
                person_values: dict[str, Iterable[Any]] = {
                    "alias": [display_name],
                    "email": [attributes["email"]],
                    "employee_status": [attributes["employee_status"]],
                    "employed_by": [institution["entity_id"]],
                    "has_title": [position_id],
                    "part_of_team": [team_id],
                    "seniority": [attributes["seniority"]],
                    "start_date": [attributes["start_date"]],
                    "team": [team["canonical_label"]],
                    "title": [attributes["title"]],
                }
                if manager is not None:
                    person_predicates.add("reports_to")
                    person_values["reports_to"] = [manager["entity_id"]]
                directory.add(
                    f"Employee name: {display_name}\n"
                    f"Email: {display_name} <{attributes['email']}>\n"
                    f"Employee status: {attributes['employee_status']}\n"
                    f"Employer: {institution['canonical_label']}\n"
                    f"Job title: {attributes['title']}\n"
                    f"Team: {team['canonical_label']}\n"
                    f"Seniority: {attributes['seniority']}\n"
                    + (
                        f"Reports to: {manager['aliases'][2]} "
                        f"<{manager['attributes']['email']}>\n"
                        if manager
                        else ""
                    )
                    + f"Start date: {attributes['start_date']}\n\n",
                    evidence_role="directory.employee",
                    truth_atom_ids=(
                        self._evidence_atoms(
                            "directory.employee",
                            person["entity_id"],
                            person_predicates,
                            exact_values=person_values,
                        )
                        + self._evidence_atoms(
                            "directory.employee",
                            institution["entity_id"],
                            {"canonical_label"},
                            exact_values={
                                "canonical_label": [institution["canonical_label"]],
                            },
                        )
                        + self._evidence_atoms(
                            "directory.employee",
                            team["entity_id"],
                            {"canonical_label"},
                            exact_values={"canonical_label": [team["canonical_label"]]},
                        )
                        + self._evidence_atoms(
                            "directory.employee",
                            position["entity_id"],
                            {"alias"},
                            exact_values={"alias": [attributes["title"]]},
                        )
                        + (
                            self._evidence_atoms(
                                "directory.employee",
                                manager["entity_id"],
                                {"alias", "email"},
                                exact_values={
                                    "alias": [manager["aliases"][2]],
                                    "email": [manager["attributes"]["email"]],
                                },
                            )
                            if manager
                            else []
                        )
                    ),
                    kind="semantic",
                    assertion="supports",
                )
            builders.append(directory)

        ordered_events = sorted(
            self.lifecycle, key=lambda item: (item["occurred_at"], item["event_id"])
        )
        representative_events = [
            ordered_events[index % len(ordered_events)]
            for index in range(self.config.email_count)
        ]
        last_message_by_thread: dict[str, str] = {}
        for index, event in enumerate(representative_events, start=1):
            subject = self._entity_by_id[event["subject_id"]]
            sender = self._entity_by_id[event["actor_id"]]
            event_day_offset = (
                date.fromisoformat(_event_time(event)[:10]) - self.start
            ).days
            active_recipients = [
                person
                for person in people
                if person["entity_id"] != sender["entity_id"]
                and self._employee_is_active(person, event_day_offset)
            ]
            if not active_recipients:
                raise ValueError(
                    f"no active recipient available for {event['event_id']}"
                )
            recipient = active_recipients[index % len(active_recipients)]
            sender_name = sender["aliases"][2]
            recipient_name = recipient["aliases"][2]
            thread_root_id = str(event["subject_id"])
            thread_id = _communication_thread_id(
                self.config.seed,
                thread_root_id,
            )
            builder = self._builder(
                "email",
                index,
                "eml",
                thread_root_id=thread_root_id,
                parent_message_id=last_message_by_thread.get(thread_id),
            )
            message_id = str(builder.communication["message_id"])
            parent_message_id = builder.communication.get("parent_message_id")
            builder.add(
                f"From: {sender_name} <{sender['attributes']['email']}>\n"
                f"To: {recipient_name} <{recipient['attributes']['email']}>\n"
                f"Message-ID: <{message_id}>\n"
                f"Thread-ID: {thread_id}\n"
                f"Conversation-ID: {thread_id}\n"
                + (
                    f"In-Reply-To: <{parent_message_id}>\n"
                    if parent_message_id
                    else ""
                ),
                evidence_role="email.address_header",
                truth_atom_ids=(
                    self._evidence_atoms(
                        "email.address_header",
                        sender["entity_id"],
                        {"alias", "email"},
                        exact_values={
                            "alias": [sender_name],
                            "email": [sender["attributes"]["email"]],
                        },
                    )
                    + self._evidence_atoms(
                        "email.address_header",
                        recipient["entity_id"],
                        {"alias", "email"},
                        exact_values={
                            "alias": [recipient_name],
                            "email": [recipient["attributes"]["email"]],
                        },
                    )
                ),
                kind="header",
            )
            if self.rng.random() < self.config.missing_date_rate:
                builder.add(
                    "X-Synthetic-Date-Omitted: true\n",
                    evidence_role="email.missing_date",
                    kind="missing-date",
                    transforms=["date-omission"],
                )
            else:
                message_date = datetime.fromisoformat(
                    str(event["occurred_at"]).replace("Z", "+00:00")
                )
                builder.add(
                    f"Date: {format_datetime(message_date)}\n",
                    evidence_role="email.date",
                    kind="temporal",
                )
            builder.add(
                f"Subject: {event['event_type'].replace('_', ' ').title()} — {subject['aliases'][0]}\n\n",
                evidence_role="email.subject",
                truth_atom_ids=self._evidence_atoms(
                    "email.subject",
                    subject["entity_id"],
                    {"alias"},
                    exact_values={"alias": [subject["aliases"][0]]},
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
            before = (
                "[none]"
                if event["state_before"] is None
                else str(event["state_before"])
            )
            builder.add(
                f"Operations recorded {subject['aliases'][0]}: "
                f"{event['event_type']} transitioned {before} -> "
                f"{event['state_after']} at {event['event_time']}; "
                f"observed {event['observed_at']}; recorded {event['recorded_at']}; "
                f"effective {event['effective_at']}. "
                f"Reference {event['event_id'][:8]}. "
                f"{sender_name} owns the follow-up from the "
                f"{sender['attributes']['team']}.\n\n"
                f"{sender_name}\n"
                f"{sender['attributes']['title']}\n"
                f"{sender['attributes']['email']}\n",
                evidence_role="email.event",
                truth_atom_ids=(
                    self._evidence_atom_ids(
                        "email.event",
                        event["truth_atom_ids"],
                        {"lifecycle_transition"},
                    )
                    + self._evidence_atoms(
                        "email.event",
                        sender["entity_id"],
                        {"alias", "email", "team", "title"},
                        exact_values={
                            "alias": [sender_name],
                            "email": [sender["attributes"]["email"]],
                            "team": [sender["attributes"]["team"]],
                            "title": [sender["attributes"]["title"]],
                        },
                    )
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
            if self.rng.random() < self.config.noise_rate:
                builder.add(
                    "\nSynthetic facilities reminder: test-room access closes at 18:00.\n",
                    evidence_role="email.noise",
                    kind="noise",
                    transforms=["irrelevant-insertion"],
                )
            builders.append(builder)
            last_message_by_thread[thread_id] = message_id

        cases = self._find_kind("case")
        if not cases:
            empty_ticket = self._builder("ticket", 1, "md")
            empty_ticket.add(
                "# Synthetic case queue\n\n",
                evidence_role="ticket.empty",
                kind="format",
            )
            empty_ticket.add(
                "No operational cases were generated for this seeded world.\n",
                evidence_role="ticket.empty",
                kind="noise",
                transforms=["empty-surface-observation"],
            )
            builders.append(empty_ticket)
        for index, case in enumerate(cases, start=1):
            events = self._events_by_subject[case["entity_id"]]
            assigned_id = self._relation_target(case["entity_id"], "assigned_to")
            assigned = self._entity_by_id[assigned_id]
            builder = self._builder("ticket", index, "md")
            builder.add(
                f"# {case['canonical_label']}\n\n",
                evidence_role="ticket.heading",
                truth_atom_ids=self._evidence_atoms(
                    "ticket.heading",
                    case["entity_id"],
                    {"canonical_label"},
                    exact_values={
                        "canonical_label": [case["canonical_label"]],
                    },
                ),
                kind="semantic",
            )
            builder.add(
                f"Ticket: {case['aliases'][0]}\n"
                f"Owner: {assigned['aliases'][2]} <{assigned['attributes']['email']}>\n"
                f"Role: {assigned['attributes']['title']}\n"
                f"Category: {case['attributes']['category']}\n\n",
                evidence_role="ticket.metadata",
                truth_atom_ids=(
                    self._evidence_atoms(
                        "ticket.metadata",
                        case["entity_id"],
                        {"alias", "assigned_to", "category"},
                        exact_values={
                            "alias": [case["aliases"][0]],
                            "assigned_to": [assigned_id],
                            "category": [case["attributes"]["category"]],
                        },
                    )
                    + self._evidence_atoms(
                        "ticket.metadata",
                        assigned_id,
                        {"alias", "email", "title"},
                        exact_values={
                            "alias": [assigned["aliases"][2]],
                            "email": [assigned["attributes"]["email"]],
                            "title": [assigned["attributes"]["title"]],
                        },
                    )
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
            for event in events:
                before = (
                    "[none]"
                    if event["state_before"] is None
                    else str(event["state_before"])
                )
                builder.add(
                    f"- event={event['event_type']} subject={case['aliases'][0]} "
                    f"transition={before}->{event['state_after']} "
                    f"event_time={event['event_time']} "
                    f"observed_at={event['observed_at']} "
                    f"recorded_at={event['recorded_at']} "
                    f"effective_at={event['effective_at']}\n",
                    evidence_role="ticket.event",
                    truth_atom_ids=self._evidence_atom_ids(
                        "ticket.event",
                        event["truth_atom_ids"],
                        {"lifecycle_transition"},
                    ),
                    kind="semantic",
                    assertion="supports",
                )
            builders.append(builder)

        chat = self._builder(
            "chat",
            1,
            "txt",
            thread_root_id="channel:synthetic-operations",
        )
        chat_message_id = str(chat.communication["message_id"])
        chat_thread_id = str(chat.communication["thread_id"])
        chat.add(
            "# synthetic-operations\n"
            f"Transcript-ID: <{chat_message_id}>\n"
            f"Thread-ID: {chat_thread_id}\n"
            f"Conversation-ID: {chat_thread_id}\n",
            evidence_role="chat.format",
            kind="format",
        )
        for index, case in enumerate(cases[:8], start=1):
            events = self._events_by_subject[case["entity_id"]]
            event = events[min(1, len(events) - 1)]
            before = (
                "[none]"
                if event["state_before"] is None
                else str(event["state_before"])
            )
            chat.add(
                f"[{event['event_time']}] fp{index:03d}: "
                f"{event['event_type']} {case['aliases'][0]} "
                f"{before}->{event['state_after']}; "
                f"observed={event['observed_at']} recorded={event['recorded_at']} "
                f"effective={event['effective_at']}.\n",
                evidence_role="chat.event",
                truth_atom_ids=self._evidence_atom_ids(
                    "chat.event",
                    event["truth_atom_ids"],
                    {"lifecycle_transition"},
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
        contradiction_count = (
            max(1, round(len(cases) * self.config.contradiction_rate))
            if cases and self.config.contradiction_rate > 0
            else 0
        )
        for index, case in enumerate(cases[:contradiction_count], start=1):
            contradicted_event = self._events_by_subject[case["entity_id"]][1]
            chat.add(
                f"[date omitted] fp{index:03d}: {case['aliases'][0]} is resolved already.\n",
                evidence_role="chat.contradiction",
                truth_atom_ids=self._evidence_atom_ids(
                    "chat.contradiction",
                    contradicted_event["truth_atom_ids"],
                    {"lifecycle_transition"},
                ),
                kind="contradiction",
                transforms=["false-state", "date-omission"],
                assertion="contradicts",
            )
        chat.add(
            "[undated] fp002: reminder — the following line is deliberate non-domain noise.\n",
            evidence_role="chat.noise",
            kind="noise",
            transforms=["irrelevant-insertion", "date-omission"],
        )
        builders.append(chat)

        ops = self._builder("ops_log", 1, "log")
        for event in sorted(self.lifecycle, key=lambda item: (item["occurred_at"], item["event_id"])):
            subject = self._entity_by_id[event["subject_id"]]
            actor = self._entity_by_id[event["actor_id"]]
            before = (
                "[none]"
                if event["state_before"] is None
                else str(event["state_before"])
            )
            ops.add(
                f"{event['event_time']} INFO event={event['event_type']} "
                f"subject={subject['aliases'][0]} actor={actor['aliases'][0]} "
                f"transition={before}->{event['state_after']} "
                f"observed_at={event['observed_at']} "
                f"recorded_at={event['recorded_at']} "
                f"effective_at={event['effective_at']}\n",
                evidence_role="ops.event",
                truth_atom_ids=self._evidence_atom_ids(
                    "ops.event",
                    event["truth_atom_ids"],
                    {"lifecycle_transition"},
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
        builders.append(ops)

        trade_csv_builders: dict[int, ArtifactBuilder] = {}
        for index, trade in enumerate(self._find_kind("trade"), start=1):
            page_index = (index - 1) // 100 + 1
            trade_csv = trade_csv_builders.get(page_index)
            if trade_csv is None:
                trade_csv = self._builder("trade_csv", page_index, "csv")
                trade_csv.add(
                    "trade_id,client,account,product,trade_date,notional,currency\n",
                    evidence_role="trade.header",
                    kind="format",
                )
                trade_csv_builders[page_index] = trade_csv
            client = self._entity_by_id[self._relation_target(trade["entity_id"], "for_client")]
            account = self._entity_by_id[self._relation_target(trade["entity_id"], "booked_to")]
            product = self._entity_by_id[self._relation_target(trade["entity_id"], "uses_product")]
            trade_csv.add(
                f"{trade['aliases'][0]},{client['aliases'][0]},{account['aliases'][0]},"
                f"{product['aliases'][0]},{trade['attributes']['trade_date']},"
                f"{trade['attributes']['notional']},{trade['attributes']['currency']}\n",
                evidence_role="trade.row",
                truth_atom_ids=(
                    self._evidence_atoms(
                        "trade.row",
                        trade["entity_id"],
                        {
                            "alias", "booked_to", "currency", "for_client",
                            "notional", "trade_date", "uses_product",
                        },
                        exact_values={
                            "alias": [trade["aliases"][0]],
                            "booked_to": [account["entity_id"]],
                            "currency": [trade["attributes"]["currency"]],
                            "for_client": [client["entity_id"]],
                            "notional": [trade["attributes"]["notional"]],
                            "trade_date": [trade["attributes"]["trade_date"]],
                            "uses_product": [product["entity_id"]],
                        },
                    )
                    + self._evidence_atoms(
                        "trade.row",
                        client["entity_id"],
                        {"alias"},
                        exact_values={"alias": [client["aliases"][0]]},
                    )
                    + self._evidence_atoms(
                        "trade.row",
                        account["entity_id"],
                        {"alias"},
                        exact_values={"alias": [account["aliases"][0]]},
                    )
                    + self._evidence_atoms(
                        "trade.row",
                        product["entity_id"],
                        {"alias", "product_code"},
                        exact_values={
                            "alias": [product["aliases"][0]],
                            "product_code": [product["attributes"]["product_code"]],
                        },
                    )
                ),
                kind="semantic",
                transforms=["alias-substitution"],
                assertion="supports",
            )
        builders.extend(trade_csv_builders.values())

        fix_builders: dict[int, ArtifactBuilder] = {}
        trades = self._find_kind("trade")
        for sequence in range(1, self.config.fix_message_count + 1):
            trade = trades[((sequence - 1) // 3) % len(trades)]
            account = self._entity_by_id[self._relation_target(trade["entity_id"], "booked_to")]
            session_index = (sequence - 1) // 500 + 1
            fix = fix_builders.setdefault(
                session_index, self._builder("fix", session_index, "fix")
            )
            phase = (sequence - 1) % 3
            if phase == 0:
                message = (
                    f"8=FIX.4.4|34={sequence}|35=D|11={trade['aliases'][0]}|"
                    f"1={account['aliases'][0]}|15={trade['attributes']['currency']}|"
                    f"38={trade['attributes']['notional']}|40=2|"
                    f"60={trade['attributes']['trade_date']}T09:00:00Z|"
                )
            elif phase == 1:
                message = (
                    f"8=FIX.4.4|34={sequence}|35=8|17=FEXEC{sequence:07d}|"
                    f"11={trade['aliases'][0]}|1={account['aliases'][0]}|"
                    f"39=0|150=0|151={trade['attributes']['notional']}|"
                    f"60={trade['attributes']['trade_date']}T09:00:01Z|"
                )
            else:
                message = (
                    f"8=FIX.4.4|34={sequence}|35=8|17=FEXEC{sequence:07d}|"
                    f"11={trade['aliases'][0]}|1={account['aliases'][0]}|"
                    f"39=2|150=2|14={trade['attributes']['notional']}|151=0|"
                    f"60={trade['attributes']['trade_date']}T09:00:03Z|"
                )
            evidence_role = (
                "fix.new_order" if phase == 0 else "fix.execution_report"
            )
            trade_predicates = {"alias", "booked_to", "trade_date"}
            trade_values: dict[str, Iterable[Any]] = {
                "alias": [trade["aliases"][0]],
                "booked_to": [account["entity_id"]],
                "trade_date": [trade["attributes"]["trade_date"]],
            }
            if phase == 0:
                trade_predicates.update({"currency", "notional"})
                trade_values.update({
                    "currency": [trade["attributes"]["currency"]],
                    "notional": [trade["attributes"]["notional"]],
                })
            fix.add(
                message + "\n",
                evidence_role=evidence_role,
                truth_atom_ids=(
                    self._evidence_atoms(
                        evidence_role,
                        trade["entity_id"],
                        trade_predicates,
                        exact_values=trade_values,
                    )
                    + self._evidence_atoms(
                        evidence_role,
                        account["entity_id"],
                        {"alias"},
                        exact_values={"alias": [account["aliases"][0]]},
                    )
                ),
                kind="semantic",
                transforms=["fix-like-encoding", "alias-substitution"],
                assertion="supports",
            )
        builders.extend(fix_builders.values())

        meeting = self._builder("meeting_note", 1, "md")
        meeting.add(
            "# Synthetic weekly operations review\n\n",
            evidence_role="meeting.heading",
            kind="format",
        )
        meeting.add(
            "Date: [intentionally omitted]\n\n",
            evidence_role="meeting.missing_date",
            kind="missing-date",
            transforms=["date-omission"],
        )
        meeting.add(
            "## Open and recently resolved cases\n\n",
            evidence_role="meeting.heading",
            kind="format",
        )
        for case in cases[:10]:
            events = self._events_by_subject[case["entity_id"]]
            final_event = events[-1]
            before = (
                "[none]"
                if final_event["state_before"] is None
                else str(final_event["state_before"])
            )
            meeting.add(
                f"- event={final_event['event_type']} "
                f"subject={case['aliases'][0]} "
                f"transition={before}->{final_event['state_after']} "
                f"event_time={final_event['event_time']} "
                f"observed_at={final_event['observed_at']} "
                f"recorded_at={final_event['recorded_at']} "
                f"effective_at={final_event['effective_at']}\n",
                evidence_role="meeting.case",
                truth_atom_ids=(
                    self._evidence_atom_ids(
                        "meeting.case",
                        final_event["truth_atom_ids"],
                        {"lifecycle_transition"},
                    )
                    + self._evidence_atoms(
                        "meeting.case",
                        case["entity_id"],
                        {"alias"},
                        exact_values={"alias": [case["aliases"][0]]},
                    )
                ),
                kind="semantic",
                transforms=["alias-substitution", "date-omission"],
                assertion="supports",
            )
        builders.append(meeting)

        # This compact operational note covers the global type universe through
        # explicit fields and normal prose. Hidden truth is not consumed by the
        # KG; the canonical source pipeline must rediscover every concept.
        person = self._find_kind("person")[1]
        manager = self._find_kind("person")[0]
        institution = self._find_kind("institution")[0]
        account = self._find_kind("account")[0]
        product = self._find_kind("product")[0]
        system = self._find_kind("system")[0]
        team = self._entity_by_id[
            self._relation_target(person["entity_id"], "part_of_team")
        ]
        position = self._entity_by_id[
            self._relation_target(person["entity_id"], "has_title")
        ]
        component = self._find_kind("component")[0]
        venue = self._find_kind("venue")[0]
        coverage = self._builder("meeting_note", 2, "md")
        synthetic_email = person["attributes"]["email"]
        coverage.add(
            "# Canonical operations inventory\n\n"
            f"Date: {_iso_day(self.start, 45)}\n"
            f"From: {person['aliases'][2]} <{synthetic_email}>\n\n",
            evidence_role="meeting.coverage_header",
            truth_atom_ids=self._evidence_atoms(
                "meeting.coverage_header",
                person["entity_id"],
                {"alias", "email"},
                exact_values={
                    "alias": [person["aliases"][2]],
                    "email": [synthetic_email],
                },
            ),
            kind="header",
            assertion="supports",
        )
        coverage.add(
            f"Person: {person['aliases'][2]}\n"
            "Employee status: Current\n"
            f"Employer: {institution['canonical_label']}\n"
            f"Job title: {position['aliases'][0]}\n"
            f"Team: {team['canonical_label']}\n"
            f"Reports to: {manager['aliases'][2]}\n"
            f"Seniority: {person['attributes']['seniority']}\n"
            f"Start date: {person['attributes']['start_date']}\n\n",
            evidence_role="meeting.coverage_employment",
            truth_atom_ids=(
                self._evidence_atoms(
                    "meeting.coverage_employment",
                    person["entity_id"],
                    {
                        "alias", "employed_by", "employee_status", "has_title",
                        "part_of_team", "reports_to", "seniority", "start_date",
                        "team", "title",
                    },
                    exact_values={
                        "alias": [person["aliases"][2]],
                        "employed_by": [institution["entity_id"]],
                        "employee_status": [person["attributes"]["employee_status"]],
                        "has_title": [position["entity_id"]],
                        "part_of_team": [team["entity_id"]],
                        "reports_to": [manager["entity_id"]],
                        "seniority": [person["attributes"]["seniority"]],
                        "start_date": [person["attributes"]["start_date"]],
                        "team": [team["canonical_label"]],
                        "title": [person["attributes"]["title"]],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_employment",
                    manager["entity_id"],
                    {"alias"},
                    exact_values={"alias": [manager["aliases"][2]]},
                )
                + self._evidence_atoms(
                    "meeting.coverage_employment",
                    institution["entity_id"],
                    {"canonical_label"},
                    exact_values={
                        "canonical_label": [institution["canonical_label"]],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_employment",
                    team["entity_id"],
                    {"canonical_label"},
                    exact_values={"canonical_label": [team["canonical_label"]]},
                )
                + self._evidence_atoms(
                    "meeting.coverage_employment",
                    position["entity_id"],
                    {"alias"},
                    exact_values={"alias": [position["aliases"][0]]},
                )
            ),
            kind="semantic",
            assertion="supports",
        )
        coverage.add(
            f"person='{person['aliases'][2]}' component='{component['canonical_label']}' "
            f"system='{system['aliases'][0]}'\n"
            f"product='{product['canonical_label']}' venue='{venue['canonical_label']}'\n"
            f"Account: {account['aliases'][0]}\n"
            f"System: {system['aliases'][0]}\n"
            "Process: Ficta Exception Resolution Cycle\n"
            "server ficta-app-4181\n"
            f"Ticket: INC-{self.config.seed}\n"
            "Topic: Synthetic Control Review\n"
            f"URL: https://ops.ficta.example/cases/INC-{self.config.seed}\n\n",
            evidence_role="meeting.coverage_inventory",
            truth_atom_ids=(
                self._evidence_atoms(
                    "meeting.coverage_inventory",
                    person["entity_id"],
                    {"alias", "entity_kind"},
                    exact_values={
                        "alias": [person["aliases"][2]],
                        "entity_kind": ["person"],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_inventory",
                    component["entity_id"],
                    {"canonical_label", "entity_kind"},
                    exact_values={
                        "canonical_label": [component["canonical_label"]],
                        "entity_kind": ["component"],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_inventory",
                    system["entity_id"],
                    {"alias", "entity_kind"},
                    exact_values={
                        "alias": [system["aliases"][0]],
                        "entity_kind": ["system"],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_inventory",
                    product["entity_id"],
                    {"canonical_label", "entity_kind"},
                    exact_values={
                        "canonical_label": [product["canonical_label"]],
                        "entity_kind": ["product"],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_inventory",
                    venue["entity_id"],
                    {"canonical_label", "entity_kind"},
                    exact_values={
                        "canonical_label": [venue["canonical_label"]],
                        "entity_kind": ["venue"],
                    },
                )
                + self._evidence_atoms(
                    "meeting.coverage_inventory",
                    account["entity_id"],
                    {"alias", "entity_kind"},
                    exact_values={
                        "alias": [account["aliases"][0]],
                        "entity_kind": ["account"],
                    },
                )
            ),
            kind="semantic",
            assertion="supports",
        )
        coverage.add(
            f"{person['aliases'][2]} recorded an issue after a reconciliation variance in PROD. "
            "The position was long and paying. This booking is for financing purposes only "
            "with no client-facing activity. "
            f"{person['aliases'][2]} changed the response window from 2 days to 4 days.\n",
            evidence_role="meeting.coverage_prose",
            truth_atom_ids=self._evidence_atoms(
                "meeting.coverage_prose",
                person["entity_id"],
                {"alias"},
                exact_values={"alias": [person["aliases"][2]]},
            ),
            kind="semantic",
            assertion="supports",
        )
        builders.append(coverage)

        catalog = self._builder("meeting_note", 3, "md")
        catalog.add(
            "# Ficta capital-markets operating catalogue\n\n",
            evidence_role="meeting.catalog_heading",
            kind="format",
        )
        for system in self._find_kind("system"):
            catalog.add(
                f"System: {system['aliases'][0]}\n"
                f"System name: {system['canonical_label']}\n"
                f"Capability: {system['attributes']['capability']}\n\n",
                evidence_role="meeting.catalog_system",
                truth_atom_ids=self._evidence_atoms(
                    "meeting.catalog_system",
                    system["entity_id"],
                    {"alias", "canonical_label", "capability", "entity_kind"},
                    exact_values={
                        "alias": [system["aliases"][0]],
                        "canonical_label": [system["canonical_label"]],
                        "capability": [system["attributes"]["capability"]],
                        "entity_kind": ["system"],
                    },
                ),
                kind="semantic",
                assertion="supports",
            )
        for product in self._find_kind("product"):
            catalog.add(
                f"Product: {product['canonical_label']}\n"
                f"Product code: {product['attributes']['product_code']}\n\n",
                evidence_role="meeting.catalog_product",
                truth_atom_ids=self._evidence_atoms(
                    "meeting.catalog_product",
                    product["entity_id"],
                    {"alias", "canonical_label", "entity_kind", "product_code"},
                    exact_values={
                        "alias": [product["attributes"]["product_code"]],
                        "canonical_label": [product["canonical_label"]],
                        "entity_kind": ["product"],
                        "product_code": [product["attributes"]["product_code"]],
                    },
                ),
                kind="semantic",
                assertion="supports",
            )
        for team in self._find_kind("team"):
            catalog.add(
                f"Team: {team['canonical_label']}\n",
                evidence_role="meeting.catalog_team",
                truth_atom_ids=self._evidence_atoms(
                    "meeting.catalog_team",
                    team["entity_id"],
                    {"canonical_label", "entity_kind"},
                    exact_values={
                        "canonical_label": [team["canonical_label"]],
                        "entity_kind": ["team"],
                    },
                ),
                kind="semantic",
                assertion="supports",
            )
        builders.append(catalog)

        # Preserve complete atom coverage without making human-facing spans
        # claim invisible facts. This is a generic typed reference-data export:
        # every line literally carries one predicate, value and validity bound.
        reference_page_size = 1_000
        reference_builders: dict[int, ArtifactBuilder] = {}
        for atom_index, atom in enumerate(self.atoms, start=1):
            page_index = (atom_index - 1) // reference_page_size + 1
            reference = reference_builders.get(page_index)
            if reference is None:
                reference = self._builder(
                    "reference_data",
                    page_index,
                    "jsonl",
                )
                reference_builders[page_index] = reference
            subject = self._entity_by_id[atom["subject_id"]]
            target = (
                self._entity_by_id.get(atom["value"])
                if isinstance(atom["value"], str)
                else None
            )
            record = {
                "record_type": "typed_observation",
                "subject_id": atom["subject_id"],
                "subject_kind": subject["kind"],
                "subject_label": subject["canonical_label"],
                "predicate": atom["predicate"],
                "value": atom["value"],
                "value_label": (
                    target["canonical_label"] if target is not None else None
                ),
                "confidence": atom["confidence"],
                "valid_from": atom["valid_from"],
                "valid_to": atom["valid_to"],
            }
            reference.add(
                _canonical_json(record) + "\n",
                evidence_role="reference_data.atom",
                truth_atom_ids=self._evidence_atom_ids(
                    "reference_data.atom",
                    [atom["truth_atom_id"]],
                    {atom["predicate"]},
                ),
                kind="semantic",
                assertion="supports",
            )
        builders.extend(reference_builders.values())

        for builder in builders:
            content, artifact_spans, record = builder.finish()
            self._write_text(output_dir / record["relative_path"], content)
            artifacts.append(record)
            spans.extend(artifact_spans)

        email_records = [record for record in artifacts if record["surface"] == "email"]
        duplicate_source_count = (
            max(1, round(len(email_records) * self.config.duplicate_rate))
            if email_records and self.config.duplicate_rate > 0
            else 0
        )
        for source_offset, source in enumerate(email_records[:duplicate_source_count]):
            source_path = output_dir / source["relative_path"]
            duplicate_index = len(email_records) + source_offset * 2 + 1
            duplicate_builder = self._builder(
                "email",
                duplicate_index,
                "eml",
                thread_root_id=str(source["thread_root_id"]),
                parent_message_id=source.get("parent_message_id"),
                message_id=str(source["message_id"]),
            )
            duplicate_builder.add(
                source_path.read_text(encoding="utf-8"),
                evidence_role="email.duplicate",
                truth_atom_ids=sorted(
                    {
                        atom
                        for span in spans
                        if span["artifact_id"] == source["artifact_id"]
                        for atom in span["truth_atom_ids"]
                    }
                ),
                kind="duplicate",
                transforms=["exact-duplicate"],
                assertion="supports",
            )
            content, duplicate_spans, record = duplicate_builder.finish(
                duplicate_of=source["artifact_id"],
                duplicate_kind="exact",
            )
            self._write_text(output_dir / record["relative_path"], content)
            artifacts.append(record)
            spans.extend(duplicate_spans)

            near_builder = self._builder(
                "email",
                duplicate_index + 1,
                "eml",
                thread_root_id=str(source["thread_root_id"]),
                parent_message_id=str(source["message_id"]),
            )
            near_message_id = str(near_builder.communication["message_id"])
            near_thread_id = str(near_builder.communication["thread_id"])
            near_content = _render_near_duplicate_email(
                source_path.read_text(encoding="utf-8"),
                message_id=near_message_id,
                thread_id=near_thread_id,
                parent_message_id=str(source["message_id"]),
            )
            near_builder.add(
                near_content,
                evidence_role="email.duplicate",
                truth_atom_ids=duplicate_spans[0]["truth_atom_ids"],
                kind="duplicate",
                transforms=["near-duplicate", "forwarded-prefix", "abbreviation"],
                assertion="supports",
            )
            content, near_spans, record = near_builder.finish(
                duplicate_of=source["artifact_id"],
                duplicate_kind="near",
            )
            self._write_text(output_dir / record["relative_path"], content)
            artifacts.append(record)
            spans.extend(near_spans)

        artifacts.sort(key=lambda item: item["artifact_id"])
        spans.sort(key=lambda item: (item["artifact_id"], item["byte_start"]))
        return artifacts, spans

    def _builder(
        self,
        surface: str,
        index: int,
        extension: str,
        *,
        thread_root_id: str | None = None,
        parent_message_id: str | None = None,
        message_id: str | None = None,
    ) -> ArtifactBuilder:
        artifact_id = f"artifact:{surface}:{index:04d}"
        relative_path = f"{SURFACE_DIRS[surface]}/{surface}-{index:04d}.{extension}"
        communication: dict[str, str | None] | None = None
        if surface in COMMUNICATION_SURFACES:
            if not thread_root_id:
                raise ValueError(
                    f"{surface} artefact {artifact_id} requires a source thread root"
                )
            thread_id = _communication_thread_id(
                self.config.seed,
                thread_root_id,
            )
            communication = {
                "message_id": message_id
                or _communication_message_id(self.config.seed, artifact_id),
                "thread_id": thread_id,
                "conversation_id": thread_id,
                "thread_root_id": thread_root_id,
                "parent_message_id": parent_message_id,
            }
        elif any((thread_root_id, parent_message_id, message_id)):
            raise ValueError(
                f"non-communication artefact {artifact_id} cannot carry thread metadata"
            )
        return ArtifactBuilder(
            artifact_id,
            relative_path,
            surface,
            communication=communication,
        )

    def _controls(
        self, artifacts: list[dict[str, Any]], spans: list[dict[str, Any]]
    ) -> dict[str, Any]:
        transform_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        for span in spans:
            kind_counts[span["kind"]] = kind_counts.get(span["kind"], 0) + 1
            for transform in span["transforms"]:
                transform_counts[transform] = transform_counts.get(transform, 0) + 1
        duplicates = [record for record in artifacts if record["duplicate_of"]]
        return {
            "schema": "cleanroom.control-injections/v1",
            "seed": self.config.seed,
            "counts": {
                "exact_duplicates": sum(record["duplicate_kind"] == "exact" for record in duplicates),
                "near_duplicates": sum(record["duplicate_kind"] == "near" for record in duplicates),
                "contradictions": kind_counts.get("contradiction", 0),
                "missing_dates": sum(
                    "date-omission" in span["transforms"] or span["kind"] == "missing-date"
                    for span in spans
                ),
                "noise_spans": kind_counts.get("noise", 0),
                "alias_substitutions": transform_counts.get("alias-substitution", 0),
            },
            "transform_counts": dict(sorted(transform_counts.items())),
            "kind_counts": dict(sorted(kind_counts.items())),
            "duplicate_artifacts": [
                {
                    "artifact_id": record["artifact_id"],
                    "duplicate_of": record["duplicate_of"],
                    "duplicate_kind": record["duplicate_kind"],
                }
                for record in duplicates
            ],
        }

    def _ontology_contract(self) -> dict[str, Any]:
        return {
            "schema": "cleanroom.abstract-ontology/v1",
            "classification": CLASSIFICATION,
            "namespace": "urn:ficta:capital-markets:",
            "policy": {
                "source_specific_terms_allowed": False,
                "unmapped_values_preserved": True,
                "raw_value_deletion_allowed": False,
                "mapping_version": "1.0.0",
            },
            "entity_kinds": {
                "institution": {"archetype": "organization"},
                "person": {"archetype": "actor"},
                "client": {"archetype": "organization"},
                "product": {"archetype": "financial-product"},
                "account": {"archetype": "account"},
                "system": {"archetype": "technology-system"},
                "trade": {"archetype": "transaction"},
                "case": {"archetype": "operational-case"},
            },
            "relation_kinds": sorted({relation["predicate"] for relation in self.relations}),
            "surface_kinds": sorted(SURFACE_DIRS),
            "public_generic_alignments": {
                "organization": "https://schema.org/Organization",
                "actor": "https://schema.org/Person",
                "email": "https://schema.org/EmailMessage",
                "technology-system": "https://schema.org/SoftwareApplication",
            },
        }

    def _relation_target(self, source_id: str, predicate: str) -> str:
        matches = [
            relation["target_id"]
            for relation in self.relations
            if relation["source_id"] == source_id and relation["predicate"] == predicate
            and relation.get("valid_to") is None
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one {predicate} relation for {source_id}, got {len(matches)}")
        return matches[0]

    def _find_kind(self, kind: str) -> list[dict[str, Any]]:
        return [entity for entity in self.entities if entity["kind"] == kind]

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")

    @classmethod
    def _write_jsonl(cls, path: Path, rows: Iterable[dict[str, Any]]) -> None:
        cls._write_text(path, "".join(_canonical_json(row) + "\n" for row in rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic, wholly synthetic capital-markets corpus"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--scale",
        choices=("fixture", "institution"),
        default="fixture",
        help="fixture keeps unit tests small; institution emits the workbench-scale bank",
    )
    parser.add_argument("--seed", type=int, default=GeneratorConfig.seed)
    parser.add_argument("--start-date", default=GeneratorConfig.start_date)
    parser.add_argument("--horizon-days", type=int, default=GeneratorConfig.horizon_days)
    parser.add_argument("--employees", type=int, default=GeneratorConfig.employee_count)
    parser.add_argument("--clients", type=int, default=GeneratorConfig.client_count)
    parser.add_argument(
        "--accounts-per-client",
        type=int,
        default=GeneratorConfig.accounts_per_client,
    )
    parser.add_argument("--trades", type=int, default=GeneratorConfig.trade_count)
    parser.add_argument("--emails", type=int, default=GeneratorConfig.email_count)
    parser.add_argument(
        "--fix-messages",
        type=int,
        default=GeneratorConfig.fix_message_count,
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.scale == "institution":
        config = institution_scale_config(seed=args.seed)
    else:
        config = GeneratorConfig(
            seed=args.seed,
            start_date=args.start_date,
            horizon_days=args.horizon_days,
            employee_count=args.employees,
            client_count=args.clients,
            accounts_per_client=args.accounts_per_client,
            trade_count=args.trades,
            email_count=args.emails,
            fix_message_count=args.fix_messages,
        )
    manifest = SyntheticCorpusGenerator(config).generate(args.output, overwrite=args.overwrite)
    print(_canonical_json({"output": str(args.output), **manifest["counts"]}, pretty=True), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
