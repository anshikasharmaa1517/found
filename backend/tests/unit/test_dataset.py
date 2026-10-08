import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import ReviewItemType
from found_core.fixtures import FILES, Dataset, load_dataset, reference_key
from found_core.services.ingest import IngestService
from found_core.services.people import PeopleService
from found_core.services.watch import WatchService

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "data" / "fixtures" / "demo-v1"
GENERATOR = ROOT / "data" / "generator" / "generate.py"
REVIEWER = Caller(user_id="rev", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam", groups=frozenset({"family"}))


class Clock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def read_dataset() -> Dataset:
    return Dataset.from_files(
        {name: json.loads((FIXTURES / name).read_text(encoding="utf-8")) for name in FILES}
    )


def generator():
    spec = importlib.util.spec_from_file_location("found_demo_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def loaded():
    repo = InMemoryFoundRepository()
    ingest = IngestService(repo, clock=Clock(), sleep=lambda _: None)
    result = load_dataset(read_dataset(), repo, ingest)
    watch = WatchService(repo, clock=Clock())
    for claim in sorted(result.claims_by_reference.values(), key=lambda c: c.ingested_at):
        watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
    return repo, ingest, result


def test_committed_fixtures_match_the_generator():
    # Regenerate with: python data/generator/generate.py
    assert generator().main(["--check", "--out", str(FIXTURES)]) == 0


def test_generator_is_deterministic():
    gen = generator()
    assert gen.render(gen.build()) == gen.render(gen.build())
    assert gen.build(seed=1)["people.json"] != gen.build()["people.json"]


def test_dataset_is_a_fictional_demo_with_no_recorded_runs_yet():
    dataset = read_dataset()
    assert dataset.incident.is_demo and "fictional" in dataset.incident.name
    assert all(o.name.endswith(" Demo") for o in dataset.organizations)
    references = [(r.org_id, r.external_reference) for r in dataset.reports]
    assert len(references) == len(set(references))
    assert {r.person for r in dataset.reports} == {p.key for p in dataset.people}
    # Recorded runs come only from real investigations (product rule 7).
    assert dataset.runs == ()


def test_load_goes_through_ingest_and_gives_the_story(loaded):
    repo, _, result = loaded
    dataset = read_dataset()
    assert result.published == len(dataset.reports) and result.replayed == 0
    assert repo.get_incident("inc_demo").is_demo
    assert len(result.subjects_by_person) == len(dataset.people)

    people = PeopleService(repo, CursorCodec(b"k" * 32))
    maya = people.profile(REVIEWER, result.subjects_by_person["maya"])
    hospital = result.claims_by_reference[reference_key("org_hospital", "CHD-0001")]
    relay = result.claims_by_reference[reference_key("org_ngo", "FRD-0001")]
    assert maya.summary.label == "Reported found safe"
    # The summary cites the latest dated report, here the relay; tracing it is UC-2.
    assert maya.summary.cited_claim_id == relay.id
    assert relay.mentioned_source_ids == (hospital.source_id,)
    assert relay.location_id is None and hospital.location_id is not None


def test_story_feeds_the_review_queue(loaded):
    repo, _, result = loaded
    by_type = {}
    for item in repo.review_items.values():
        by_type.setdefault(item.item_type, set()).add(item.ref_id)
    deceased = next(
        c for c in result.claims_by_reference.values() if c.claim_type == "DECEASED"
    )
    assert deceased.id in by_type[ReviewItemType.HELD_ALERT]
    vikram = result.subjects_by_person["vikram"]
    conflicts = {repo.get_claim(ref).subject_id for ref in by_type[ReviewItemType.CONFLICT]}
    assert vikram in conflicts
    people = PeopleService(repo, CursorCodec(b"k" * 32))
    ramesh = result.subjects_by_person["ramesh"]
    assert deceased.id in people.profile(FAMILY, ramesh).withheld


def test_misspelled_source_is_not_a_mention(loaded):
    _, _, result = loaded
    relay = next(
        c for c in result.claims_by_reference.values() if "Centrel Hospitl" in c.original_text
    )
    assert relay.mentioned_source_ids == ()


def test_loading_again_changes_nothing(loaded):
    repo, ingest, first = loaded
    claims_before = dict(repo.claims)
    again = load_dataset(read_dataset(), repo, ingest)
    assert again.published == 0 and again.replayed == len(first.claims_by_reference)
    assert repo.claims == claims_before
    assert again.subjects_by_person == first.subjects_by_person
