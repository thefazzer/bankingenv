"""SQLite-backed registry for reusable curated synthetic entities and assets."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .model import SyntheticInstitution, SyntheticPerson
from .providers import Classification, HeadshotProvider, SurnameClassifier


REGISTRY_SCHEMA = "cleanroom.synthetic-store-registry/v1"
HEADSHOT_STYLE_REVISION = "ficta-passport-business-cool-wash/v3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StoreRegistry:
    """Persist canonical identities, classifier pins and generated media.

    Cache misses are serialized with ``BEGIN IMMEDIATE``. A second process
    observes the row committed by the first and never calls the provider.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets = self.root / "assets" / "sha256"
        self.assets.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "registry.sqlite3"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS registry_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO registry_meta VALUES ('schema', 'cleanroom.synthetic-store-registry/v1');
                CREATE TABLE IF NOT EXISTS institutions (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('draft','curated','retired')),
                    revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS surname_pins (
                    surname_key TEXT NOT NULL, provider TEXT NOT NULL, provider_revision TEXT NOT NULL,
                    model TEXT NOT NULL, label TEXT NOT NULL, confidence REAL NOT NULL,
                    distribution TEXT NOT NULL, curated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (surname_key, provider, provider_revision, model)
                );
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relative_path TEXT NOT NULL,
                    media_type TEXT NOT NULL, bytes INTEGER NOT NULL, provider TEXT NOT NULL,
                    provider_revision TEXT NOT NULL, prompt TEXT NOT NULL, attributes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS person_headshots (
                    person_key TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(asset_id),
                    request_hash TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS institution_logos (
                    institution_key TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS institution_logo_aliases (
                    alias TEXT PRIMARY KEY,
                    institution_key TEXT NOT NULL REFERENCES institution_logos(institution_key)
                        ON DELETE CASCADE
                );
            """)

    def get_institution(self, key: str) -> SyntheticInstitution | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM institutions WHERE key=?", (key,)).fetchone()
        return SyntheticInstitution.from_dict(json.loads(row["payload"])) if row else None

    def put_institution(
        self, institution: SyntheticInstitution, *, state: str = "draft",
        expected_revision: int | None = None,
    ) -> int:
        if state not in {"draft", "curated", "retired"}:
            raise ValueError(f"invalid curation state: {state}")
        payload = _canonical_json(institution.to_dict())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, payload, state FROM institutions WHERE key=?", (institution.key,)
            ).fetchone()
            if row:
                revision = int(row["revision"])
                if expected_revision is not None and expected_revision != revision:
                    connection.rollback()
                    raise RuntimeError(f"stale institution revision: expected {expected_revision}, found {revision}")
                if row["payload"] == payload and row["state"] == state:
                    connection.commit()
                    return revision
                revision += 1
                connection.execute(
                    "UPDATE institutions SET payload=?, state=?, revision=?, updated_at=? WHERE key=?",
                    (payload, state, revision, _now(), institution.key),
                )
            else:
                if expected_revision not in (None, 0):
                    connection.rollback()
                    raise RuntimeError("institution does not exist")
                revision = 1
                timestamp = _now()
                connection.execute(
                    "INSERT INTO institutions VALUES (?,?,?,?,?,?)",
                    (institution.key, payload, state, revision, timestamp, timestamp),
                )
            connection.commit()
            return revision

    def get_or_create_institution(
        self, key: str, factory: Callable[[], SyntheticInstitution], *, state: str = "draft",
    ) -> SyntheticInstitution:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM institutions WHERE key=?", (key,)).fetchone()
            if row:
                connection.commit()
                return SyntheticInstitution.from_dict(json.loads(row["payload"]))
            institution = factory()
            if institution.key != key:
                connection.rollback()
                raise ValueError("factory returned a different institution key")
            timestamp = _now()
            connection.execute(
                "INSERT INTO institutions VALUES (?,?,?,?,?,?)",
                (key, _canonical_json(institution.to_dict()), state, 1, timestamp, timestamp),
            )
            connection.commit()
            return institution

    def pin_surname(self, surname: str, classifier: SurnameClassifier) -> Classification:
        surname_key = surname.strip().casefold()
        identity = (surname_key, classifier.provider, classifier.revision, classifier.model)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM surname_pins WHERE surname_key=? AND provider=? AND provider_revision=? AND model=?",
                identity,
            ).fetchone()
            if row:
                connection.commit()
                return Classification(
                    row["label"], row["confidence"], json.loads(row["distribution"]),
                    row["provider"], row["provider_revision"], row["model"],
                )
            prediction = classifier.classify(surname)
            if (prediction.provider, prediction.revision, prediction.model) != identity[1:]:
                connection.rollback()
                raise ValueError("classifier result provenance does not match provider configuration")
            connection.execute(
                "INSERT INTO surname_pins VALUES (?,?,?,?,?,?,?,?,?)",
                (*identity, prediction.label, prediction.confidence,
                 _canonical_json(prediction.distribution), 0, _now()),
            )
            connection.commit()
            return prediction

    def curate_surname(self, surname: str, classifier: SurnameClassifier) -> None:
        self.pin_surname(surname, classifier)
        with self._connect() as connection:
            connection.execute(
                "UPDATE surname_pins SET curated=1 WHERE surname_key=? AND provider=? AND provider_revision=? AND model=?",
                (surname.strip().casefold(), classifier.provider, classifier.revision, classifier.model),
            )

    def headshot_for(self, person: SyntheticPerson, provider: HeadshotProvider) -> SyntheticPerson:
        attributes = {**person.headshot_profile, "style_revision": HEADSHOT_STYLE_REVISION}
        prompt = (
            "photorealistic passport headshot, "
            f"{person.ethnicity or 'diverse'} {attributes.get('sex') or 'adult'} "
            f"age {attributes.get('age_group') or 'adult'}, frontal, direct eye contact, upright, "
            "square shoulders, centered symmetrical ID crop, dark suit, white shirt, pale "
            "blue-grey studio, even biometric lighting, sharp natural skin, cool desaturated "
            "steel-blue wash, navy-charcoal tones, lifted cool blacks, warm skin, low saturation"
        )
        request_hash = hashlib.sha256(_canonical_json({
            "person_key": person.key, "prompt": prompt, "attributes": attributes,
            "provider": provider.provider, "revision": provider.revision,
        }).encode()).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT a.asset_id FROM person_headshots p JOIN assets a USING(asset_id) "
                "WHERE p.person_key=? AND p.request_hash=?",
                (person.key, request_hash),
            ).fetchone()
            if row:
                connection.commit()
                return replace(person, headshot_asset_id=row["asset_id"])
            payload = provider.render(person_key=person.key, prompt=prompt, attributes=attributes)
            if not payload:
                connection.rollback()
                raise ValueError("headshot provider returned an empty asset")
            digest = hashlib.sha256(payload).hexdigest()
            asset_id = f"sha256:{digest}"
            extension = ".png" if payload.startswith(b"\x89PNG") else ".jpg"
            relative = Path("assets") / "sha256" / digest[:2] / f"{digest}{extension}"
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_bytes(payload)
            media_type = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
            connection.execute(
                "INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (asset_id, digest, relative.as_posix(), media_type, len(payload),
                 provider.provider, provider.revision, prompt, _canonical_json(attributes), _now()),
            )
            connection.execute(
                "INSERT INTO person_headshots VALUES (?,?,?,?) "
                "ON CONFLICT(person_key) DO UPDATE SET asset_id=excluded.asset_id, "
                "request_hash=excluded.request_hash, created_at=excluded.created_at",
                (person.key, asset_id, request_hash, _now()),
            )
            connection.commit()
        return replace(person, headshot_asset_id=asset_id)

    def headshot_asset_id(self, person_key: str) -> str:
        """Return the current curated headshot binding for a Cast Person key."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT asset_id FROM person_headshots WHERE person_key=?", (person_key,)
            ).fetchone()
        if not row:
            raise KeyError(person_key)
        return str(row["asset_id"])

    def resolve_person_headshot(self, person_key: str) -> tuple[Path, str, str]:
        """Resolve a Person binding to verified bytes plus media type and immutable ETag."""

        asset_id = self.headshot_asset_id(person_key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT media_type, sha256 FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if not row:
            raise KeyError(asset_id)
        return self.resolve_asset(asset_id), str(row["media_type"]), str(row["sha256"])

    def bind_institution_logo(
        self,
        institution_key: str,
        payload: bytes,
        *,
        aliases: tuple[str, ...] = (),
        provider: str,
        provider_revision: str,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        """Bind verified SVG bytes to an institution and optional stable aliases."""

        keys = (institution_key, *aliases)
        if not all(re.fullmatch(r"[A-Za-z0-9._-]{1,120}", key or "") for key in keys):
            raise ValueError("logo keys must be safe single path segments")
        if not payload.lstrip().startswith(b"<svg"):
            raise ValueError("institution logo must be SVG")
        digest = hashlib.sha256(payload).hexdigest()
        asset_id = f"sha256:{digest}"
        relative = Path("assets") / "sha256" / digest[:2] / f"{digest}.svg"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError("content-addressed logo destination is corrupt")
        else:
            destination.write_bytes(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    asset_id,
                    digest,
                    relative.as_posix(),
                    "image/svg+xml",
                    len(payload),
                    provider,
                    provider_revision,
                    "deterministic synthetic institution mark",
                    _canonical_json(attributes or {}),
                    _now(),
                ),
            )
            connection.execute(
                "INSERT INTO institution_logos VALUES (?,?,?) "
                "ON CONFLICT(institution_key) DO UPDATE SET "
                "asset_id=excluded.asset_id, created_at=excluded.created_at",
                (institution_key, asset_id, _now()),
            )
            connection.execute(
                "DELETE FROM institution_logo_aliases WHERE institution_key=?",
                (institution_key,),
            )
            connection.executemany(
                "INSERT INTO institution_logo_aliases VALUES (?,?)",
                [(alias, institution_key) for alias in aliases],
            )
            connection.commit()
        return asset_id

    def resolve_institution_logo(self, key: str) -> tuple[Path, str, str]:
        """Resolve a logo key or alias to digest-verified SVG bytes."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT a.asset_id, a.media_type, a.sha256 "
                "FROM institution_logos l JOIN assets a USING(asset_id) "
                "WHERE l.institution_key=? OR l.institution_key=("
                "SELECT institution_key FROM institution_logo_aliases WHERE alias=?)",
                (key, key),
            ).fetchone()
        if not row:
            raise KeyError(key)
        return (
            self.resolve_asset(str(row["asset_id"])),
            str(row["media_type"]),
            str(row["sha256"]),
        )

    def curate_institution(
        self,
        institution: SyntheticInstitution,
        classifier: SurnameClassifier,
        *,
        headshots: HeadshotProvider | None = None,
    ) -> SyntheticInstitution:
        """Pin classifier provenance and optional media into every employee."""

        people: list[SyntheticPerson] = []
        for person in institution.people:
            classification = self.pin_surname(person.surname, classifier)
            metadata = dict(person.metadata)
            metadata["ethnicity_classifier"] = {
                "provider": classification.provider,
                "revision": classification.revision,
                "model": classification.model,
                "confidence": classification.confidence,
                "distribution": classification.distribution,
            }
            curated = replace(
                person, ethnicity=classification.label, metadata=metadata
            )
            if headshots is not None:
                curated = self.headshot_for(curated, headshots)
            people.append(curated)
        curated_institution = replace(institution, people=tuple(people))
        self.put_institution(curated_institution, state="curated")
        return curated_institution

    def resolve_asset(self, asset_id: str) -> Path:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT relative_path, sha256 FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if not row:
            raise KeyError(asset_id)
        path = (self.root / row["relative_path"]).resolve()
        if self.root not in path.parents:
            raise RuntimeError("asset path escaped registry root")
        if not path.is_file():
            raise RuntimeError(f"registered asset is missing: {asset_id}")
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != row["sha256"]:
            raise RuntimeError(f"registered asset failed SHA-256 verification: {asset_id}")
        return path

    def verify(self) -> dict[str, Any]:
        """Fail closed if any model reference or content-addressed asset is invalid."""

        with self._connect() as connection:
            institution_rows = connection.execute(
                "SELECT key, payload FROM institutions ORDER BY key"
            ).fetchall()
            asset_ids = [
                row[0] for row in connection.execute(
                    "SELECT asset_id FROM assets ORDER BY asset_id"
                ).fetchall()
            ]
            logo_asset_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT asset_id FROM institution_logos"
                ).fetchall()
            }
        referenced: set[str] = set(logo_asset_ids)
        for row in institution_rows:
            institution = SyntheticInstitution.from_dict(json.loads(row["payload"]))
            if institution.key != row["key"]:
                raise RuntimeError(f"institution payload key mismatch: {row['key']}")
            for person in institution.people:
                if person.headshot_asset_id:
                    referenced.add(person.headshot_asset_id)
        for asset_id in asset_ids:
            self.resolve_asset(asset_id)
        unknown = referenced - set(asset_ids)
        if unknown:
            raise RuntimeError(
                "registry references unknown assets: " + ", ".join(sorted(unknown))
            )
        return {
            "schema": REGISTRY_SCHEMA,
            "status": "PASS",
            "institutions_checked": len(institution_rows),
            "assets_checked": len(asset_ids),
            "asset_references_checked": len(referenced),
        }

    def manifest(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "institutions",
                    "surname_pins",
                    "assets",
                    "person_headshots",
                    "institution_logos",
                    "institution_logo_aliases",
                )
            }
        return {"schema": REGISTRY_SCHEMA, "root": str(self.root), "counts": counts}
