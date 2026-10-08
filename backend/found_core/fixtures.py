"""The demo dataset and how it is loaded (design Sections 5.5 and 13, `data/fixtures`).

Fixtures go through `IngestService`, the single write path, so demo data follows the
same rules as real reports: idempotency by reference, sequencing, mention detection.
Loading twice therefore changes nothing, and a partial load can simply be run again.

Recorded runs (`runs.json`) are real investigations captured after they ran. They name
reports by external reference, because claim ids change every time the dataset loads.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from found_core.domain.commands import PublishCommand
from found_core.domain.enums import ExtractionMethod, SourceType
from found_core.domain.models import Claim, Incident, Organization
from found_core.domain.normalize import normalize_text
from found_core.ports.repository import FoundRepository
from found_core.services.ingest import IngestService

FIXTURE_ACTOR = "demo-loader"
FILES = ("incident.json", "organizations.json", "people.json", "reports.json", "runs.json")


class _Fixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IncidentFixture(_Fixture):
    id: str = Field(pattern=r"^inc_[A-Za-z0-9_]{1,40}$")
    name: str
    is_demo: bool
    started_at: datetime | None = None
    version: str
    seed: int


class OrganizationFixture(_Fixture):
    id: str
    name: str
    org_type: SourceType


class PersonFixture(_Fixture):
    key: str
    name: str
    age: int | None = None
    notes: str | None = None


class LocationFixture(_Fixture):
    name: str
    lat: float | None = None
    lon: float | None = None


class ReportFixture(_Fixture):
    org_id: str
    external_reference: str
    person: str
    claim_type: str
    value: str | None = None
    original_text: str
    reported_at: str | None = None
    location: LocationFixture | None = None


class Dataset(_Fixture):
    incident: IncidentFixture
    organizations: tuple[OrganizationFixture, ...]
    people: tuple[PersonFixture, ...]
    reports: tuple[ReportFixture, ...]
    runs: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_files(cls, files: dict[str, Any]) -> "Dataset":
        """`files` maps each file name in FILES to its parsed JSON."""
        return cls(
            incident=files["incident.json"],
            organizations=files["organizations.json"],
            people=files["people.json"],
            reports=files["reports.json"],
            runs=files.get("runs.json") or (),
        )


@dataclass(frozen=True)
class LoadResult:
    claims_by_reference: dict[str, Claim]
    subjects_by_person: dict[str, str]
    published: int
    replayed: int


def reference_key(org_id: str, external_reference: str) -> str:
    return f"{org_id}/{external_reference}"


def load_dataset(dataset: Dataset, repo: FoundRepository, ingest: IngestService) -> LoadResult:
    incident = dataset.incident
    repo.put_incident(
        Incident(
            id=incident.id,
            name=incident.name,
            is_demo=incident.is_demo,
            started_at=incident.started_at,
        )
    )
    orgs = {o.id: o for o in dataset.organizations}
    for org in dataset.organizations:
        repo.put_organization(
            Organization(
                id=org.id,
                incident_id=incident.id,
                name=org.name,
                name_norm=normalize_text(org.name),
                org_type=org.org_type,
            )
        )
    people = {p.key: p for p in dataset.people}
    subjects: dict[str, str] = {}
    claims: dict[str, Claim] = {}
    published = replayed = 0
    for report in dataset.reports:
        org = orgs[report.org_id]
        person = people[report.person]
        if report.person in subjects:
            subject: dict[str, Any] = {"type": "PERSON", "id": subjects[report.person]}
        else:
            new = {"name": person.name, "age": person.age, "notes": person.notes}
            subject = {"type": "PERSON", "new": {k: v for k, v in new.items() if v is not None}}
        result = ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": incident.id,
                    "org_id": org.id,
                    "org_name": org.name,
                    "org_type": org.org_type,
                    "actor": FIXTURE_ACTOR,
                    "subject": subject,
                    "claim_type": report.claim_type,
                    "value": report.value,
                    "original_text": report.original_text,
                    "external_reference": report.external_reference,
                    "reported_at": report.reported_at,
                    "location": report.location.model_dump() if report.location else None,
                    "extraction_method": ExtractionMethod.FIXTURE,
                }
            )
        )
        subjects.setdefault(report.person, result.claim.subject_id)
        claims[reference_key(org.id, report.external_reference)] = result.claim
        if result.replayed:
            replayed += 1
        else:
            published += 1
    return LoadResult(
        claims_by_reference=claims,
        subjects_by_person=subjects,
        published=published,
        replayed=replayed,
    )
