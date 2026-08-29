"""Canonical first-generation Ficta institution."""

from __future__ import annotations

from .model import SyntheticInstitution, SyntheticPerson
from .providers import HeadshotProvider, SurnameClassifier
from .registry import StoreRegistry


FICTA_KEY = "ficta-meridian-bank"
FICTA_FIXTURE_VERSION = 2
FICTA_EMPLOYEE_COUNT = 200

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

# This mapping is a synthetic image-generation heuristic, not an assertion
# about the age of a real employee or a hiring/promotion rule.
AGE_GROUP_BY_SENIORITY = {
    "Managing Director": "50s",
    "Director": "40s",
    "Vice President": "30s",
    "Associate": "20s",
    "Analyst": "20s",
}


def _title_for(team_index: int, position: int) -> tuple[str, int]:
    if position == 0:
        return ("Managing Director", 5) if team_index < 5 else ("Director", 4)
    if position <= 2:
        return "Vice President", 3
    if position <= 5:
        return "Associate", 2
    return "Analyst", 1


def first_generation() -> SyntheticInstitution:
    people: list[SyntheticPerson] = []
    for index in range(FICTA_EMPLOYEE_COUNT):
        team_index, position = divmod(index, 10)
        title, seniority_band = _title_for(team_index, position)
        given_name = GIVEN_NAMES[index % len(GIVEN_NAMES)]
        # Exercise all twenty surname pins while keeping every full name unique.
        family_index = ((index // len(GIVEN_NAMES)) * 2 + index % 2) % len(FAMILY_NAMES)
        surname = FAMILY_NAMES[family_index]
        person_number = index + 1
        manager_number = 1 if position == 0 else team_index * 10 + 1
        people.append(SyntheticPerson(
            key=f"ficta-person-{person_number:03d}",
            given_name=given_name,
            surname=surname,
            title=title,
            team=OPERATING_FUNCTIONS[team_index],
            email=(
                f"{given_name}.{surname}{person_number:03d}@ficta.example"
            ).casefold(),
            sex="female" if index % 2 == 0 else "male",
            metadata={
                "seniority_band": seniority_band,
                "age_group": AGE_GROUP_BY_SENIORITY[title],
                "age_group_source": "synthetic_seniority_proxy/v1",
                "gender": "female" if index % 2 == 0 else "male",
                "reports_to": (
                    None if person_number == 1
                    else f"ficta-person-{manager_number:03d}"
                ),
            },
        ))
    return SyntheticInstitution(
        key=FICTA_KEY, name="Ficta Meridian Bank 001", domain="ficta.example",
        jurisdiction="GB", people=tuple(people),
        metadata={
            "classification": "SYNTHETIC_CLEAN_ROOM",
            "generation": 1,
            "fixture_version": FICTA_FIXTURE_VERSION,
            "age_proxy": {
                "schema": "synthetic.seniority-age-proxy/v1",
                "mapping": AGE_GROUP_BY_SENIORITY,
                "scope": "headshot-generation-only",
            },
        },
    )


def _upgrade(existing: SyntheticInstitution) -> SyntheticInstitution:
    """Expand older Ficta fixtures while retaining already curated assets."""

    desired = first_generation()
    existing_people = {person.key: person for person in existing.people}
    people: list[SyntheticPerson] = []
    for person in desired.people:
        previous = existing_people.get(person.key)
        if previous is None:
            people.append(person)
            continue
        people.append(SyntheticPerson(
            key=person.key,
            given_name=person.given_name,
            surname=person.surname,
            title=person.title,
            team=person.team,
            email=person.email,
            sex=person.sex,
            ethnicity=previous.ethnicity,
            headshot_asset_id=previous.headshot_asset_id,
            # New structural/proxy facts supersede the old fixture, while
            # classifier provenance and other curation metadata survive.
            metadata={**previous.metadata, **person.metadata},
        ))
    return SyntheticInstitution(
        key=desired.key,
        name=desired.name,
        domain=desired.domain,
        jurisdiction=desired.jurisdiction,
        people=tuple(people),
        metadata={**existing.metadata, **desired.metadata},
    )


def install(
    registry: StoreRegistry,
    *,
    classifier: SurnameClassifier | None = None,
    headshots: HeadshotProvider | None = None,
) -> SyntheticInstitution:
    """Install once and thereafter return the curated canonical Ficta record."""

    institution = registry.get_or_create_institution(
        FICTA_KEY, first_generation, state="curated"
    )
    if (
        institution.metadata.get("fixture_version", 0) < FICTA_FIXTURE_VERSION
        or len(institution.people) < FICTA_EMPLOYEE_COUNT
    ):
        institution = _upgrade(institution)
        registry.put_institution(institution, state="curated")
    if classifier is not None:
        institution = registry.curate_institution(
            institution, classifier, headshots=headshots
        )
    elif headshots is not None:
        raise ValueError("headshots require a classifier-curated institution")
    return institution
