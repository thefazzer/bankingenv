"""The durable identity layer for synthetic institutions and people."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SyntheticPerson:
    key: str
    given_name: str
    surname: str
    title: str
    team: str
    email: str
    sex: str | None = None
    ethnicity: str | None = None
    headshot_asset_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.given_name} {self.surname}"

    @property
    def headshot_profile(self) -> dict[str, Any]:
        """Stable visual identity inputs; seniority is the explicit age proxy."""

        return {
            "schema": "synthetic.person-headshot-profile/v1",
            "person_key": self.key,
            "display_name": self.display_name,
            "surname": self.surname,
            "sex": self.sex or self.metadata.get("sex") or self.metadata.get("gender"),
            "ethnicity": self.ethnicity,
            "title": self.title,
            "team": self.team,
            "seniority_band": self.metadata.get("seniority_band"),
            "age_group": self.metadata.get("age_group"),
            "age_group_source": self.metadata.get("age_group_source"),
        }

    def to_cast_node(self, *, headshot_url_prefix: str = "/synthetic/headshots/") -> dict[str, Any]:
        """Project this reusable record onto the browser's Cast Person contract."""

        properties = {
            "canonical_name": self.display_name,
            "synthetic_person_key": self.key,
            "title": self.title,
            "team": self.team,
            "email": self.email,
            "sex": self.headshot_profile["sex"],
            "ethnicity": self.ethnicity,
            "seniority": self.metadata.get("seniority_band"),
            "headshot_asset_id": self.headshot_asset_id,
        }
        if self.headshot_asset_id:
            properties["headshot_url"] = f"{headshot_url_prefix.rstrip('/')}/{self.key}"
        return {
            "id": self.key,
            "label": self.display_name,
            "kind": "Person",
            "group": "Person",
            "properties": properties,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SyntheticPerson":
        return cls(**value)


@dataclass(frozen=True)
class SyntheticInstitution:
    key: str
    name: str
    domain: str
    jurisdiction: str
    people: tuple[SyntheticPerson, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["people"] = [person.to_dict() for person in self.people]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SyntheticInstitution":
        value = dict(value)
        value["people"] = tuple(
            SyntheticPerson.from_dict(person) for person in value.get("people", ())
        )
        return cls(**value)
