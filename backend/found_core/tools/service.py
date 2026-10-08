"""The only path from the agent to data (design Sections 5.2 step 5, 6.7 and 9.9).

Each call is counted against the run's tool cap before anything else happens, so a
rejected or malformed call still uses one. Reads are scoped to the run's incident.
Report text goes back marked as untrusted data. `record_finding` validates the finding
against stored claims, decides the outcome in code and writes it once, only while the
run is RUNNING.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from found_core.domain.enums import InvestigationStatus, ReviewItemType, SubjectType
from found_core.domain.findings import cited_ids, decide_outcome, validate_finding
from found_core.domain.ids import review_item_id
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import Claim, Investigation, ReviewItem, Source, Subject
from found_core.domain.normalize import name_tokens
from found_core.domain.rules import age_matches, report_order
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository
from found_core.tools.arguments import (
    TOOL_ARGS,
    ClaimArgs,
    RecordFindingArgs,
    SearchPeopleArgs,
    SourceReportsArgs,
    TimelineArgs,
)

MAX_PEOPLE = 10


class ToolError(Exception):
    def __init__(self, code: str, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = errors or []

    def body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.errors:
            error["errors"] = self.errors
        return {"ok": False, "error": error}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


class AgentToolService:
    def __init__(
        self, repo: FoundRepository, config: InvestigationConfig, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._config = config
        self._clock = clock or SystemClock()
        self._handlers: dict[str, Callable[[Investigation, Any], dict[str, Any]]] = {
            "get_report": self._get_report,
            "list_mentioned_sources": self._list_mentioned_sources,
            "find_reports_by_source": self._find_reports_by_source,
            "get_person_timeline": self._get_person_timeline,
            "search_people": self._search_people,
            "record_finding": self._record_finding,
        }

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._call(tool, arguments)
        except ToolError as err:
            return err.body()

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in TOOL_ARGS:
            raise ToolError("UNKNOWN_TOOL", f"There is no tool named {tool!r}.")
        investigation_id = arguments.get("investigation_id") if arguments else None
        if not isinstance(investigation_id, str) or not investigation_id:
            raise ToolError("BAD_ARGUMENTS", "investigation_id is required.")

        cap = self._config.max_tool_calls
        count = self._repo.count_tool_call(investigation_id, cap)
        investigation = self._repo.get_investigation(investigation_id)
        if investigation is None:
            raise ToolError("NOT_FOUND", "Investigation not found.")
        if count is None:
            if investigation.status != InvestigationStatus.RUNNING:
                raise ToolError("NOT_RUNNING", "This investigation is not running.")
            raise ToolError("TOOL_CAP", f"The limit of {cap} tool calls is reached.")

        args = self._parse(TOOL_ARGS[tool], arguments)
        result = self._handlers[tool](investigation, args)
        return {"ok": True, "tool_calls_left": max(cap - count, 0), **result}

    @staticmethod
    def _parse(model: type[BaseModel], arguments: dict[str, Any]) -> BaseModel:
        try:
            return model.model_validate(arguments)
        except ValidationError as err:
            errors = [
                {
                    "field": ".".join(str(p) for p in e["loc"]) or None,
                    "code": e["type"],
                    "message": e["msg"],
                }
                for e in err.errors(include_url=False, include_input=False)
            ]
            raise ToolError("BAD_ARGUMENTS", "Arguments are invalid.", errors) from None

    def _claim(self, investigation: Investigation, claim_id: str) -> Claim:
        claim = self._repo.get_claim(claim_id)
        if claim is None or claim.incident_id != investigation.incident_id:
            raise ToolError("NOT_FOUND", f"Claim {claim_id} is not in this incident.")
        return claim

    def _sources(self, investigation: Investigation) -> dict[str, Source]:
        return {s.id: s for s in self._repo.list_sources(investigation.incident_id)}

    @staticmethod
    def _report(claim: Claim, sources: dict[str, Source]) -> dict[str, Any]:
        source = sources.get(claim.source_id)
        return {
            "claim_id": claim.id,
            "subject_id": claim.subject_id,
            "source_id": claim.source_id,
            "source": source.name if source else None,
            "claim_type": claim.claim_type,
            "reported_at": _iso(claim.reported_at),
            "reported_at_raw": claim.reported_at_raw,
            "external_reference": claim.external_reference,
            "text_untrusted": claim.original_text,
        }

    @staticmethod
    def _person(subject: Subject) -> dict[str, Any]:
        return {
            "id": subject.id,
            "type": subject.subject_type.value,
            "name": subject.display_name,
            "age": subject.age,
        }

    def _get_report(self, investigation: Investigation, args: ClaimArgs) -> dict[str, Any]:
        claim = self._claim(investigation, args.claim_id)
        report = self._report(claim, self._sources(investigation))
        subject = self._repo.get_subject(claim.subject_id)
        report["subject"] = self._person(subject) if subject else None
        return {"report": report}

    def _list_mentioned_sources(
        self, investigation: Investigation, args: ClaimArgs
    ) -> dict[str, Any]:
        claim = self._claim(investigation, args.claim_id)
        sources = self._sources(investigation)
        return {
            "claim_id": claim.id,
            "sources": [
                {"id": s.id, "name": s.name, "type": s.source_type.value}
                for sid in claim.mentioned_source_ids
                if (s := sources.get(sid)) is not None
            ],
        }

    def _find_reports_by_source(
        self, investigation: Investigation, args: SourceReportsArgs
    ) -> dict[str, Any]:
        source = self._repo.get_source(investigation.incident_id, args.source_id)
        if source is None:
            raise ToolError("NOT_FOUND", f"Source {args.source_id} is not in this incident.")
        claims = self._repo.list_source_claims(source.id, args.limit, args.subject_id)
        sources = {source.id: source}
        return {
            "source": {"id": source.id, "name": source.name, "type": source.source_type.value},
            "reports": [self._report(c, sources) for c in claims],
        }

    def _get_person_timeline(
        self, investigation: Investigation, args: TimelineArgs
    ) -> dict[str, Any]:
        person = self._repo.get_subject(args.person_id)
        if (
            person is None
            or person.subject_type != SubjectType.PERSON
            or person.incident_id != investigation.incident_id
        ):
            raise ToolError("NOT_FOUND", f"Person {args.person_id} is not in this incident.")
        claims = sorted(self._repo.list_subject_claims(person.id), key=report_order)
        sources = self._sources(investigation)
        return {
            "person": self._person(person),
            "reports": [self._report(c, sources) for c in claims[-args.limit :]],
            "total": len(claims),
        }

    def _search_people(
        self, investigation: Investigation, args: SearchPeopleArgs
    ) -> dict[str, Any]:
        tokens = name_tokens(args.name)
        if not tokens:
            raise ToolError("BAD_ARGUMENTS", "name needs at least 2 letters.")
        incident_id = investigation.incident_id
        ids = self._repo.find_subject_ids_by_token(incident_id, max(tokens, key=len))
        matches = sorted(
            (
                s
                for s in self._repo.get_subjects(ids)
                if s.incident_id == incident_id
                and s.subject_type == SubjectType.PERSON
                and all(any(t.startswith(q) for t in s.tokens()) for q in tokens)
                and (args.age is None or age_matches(s.age, args.age))
            ),
            key=lambda s: (s.name_norm, s.id),
        )
        return {"people": [self._person(s) for s in matches[:MAX_PEOPLE]]}

    def _record_finding(
        self, investigation: Investigation, args: RecordFindingArgs
    ) -> dict[str, Any]:
        claim = self._claim(investigation, investigation.claim_id)
        cited: dict[str, Claim] = {}
        for claim_id in cited_ids(args):
            found = self._repo.get_claim(claim_id)
            if found is not None and found.incident_id == investigation.incident_id:
                cited[claim_id] = found
        source_id = args.referenced_source_id
        has_reports = (
            source_id is not None
            and source_id in claim.mentioned_source_ids
            and self._repo.latest_source_claim_id(source_id) is not None
        )

        errors = validate_finding(args, claim, cited, has_reports)
        if errors:
            raise ToolError(
                "FINDING_REJECTED",
                "The finding was not recorded. Correct the errors and call again.",
                [{"field": e.field, "code": e.code, "message": e.message} for e in errors],
            )

        outcome = decide_outcome(args, has_reports)
        now = self._clock.now()
        stored = self._repo.update_investigation_if(
            investigation.id,
            InvestigationStatus.RUNNING,
            {
                "status": outcome.status,
                "attribution": args.attribution,
                "referenced_source_id": source_id,
                "comparison": args.comparison,
                "summary": args.summary.strip(),
                "citations": args.citations,
                "outcome_reasons": outcome.reasons,
                "finished_at": now,
            },
        )
        if stored is None:
            raise ToolError("NOT_RUNNING", "This investigation is not running.")
        if outcome.priority is not None:
            self._repo.put_review_item_if_absent(
                ReviewItem(
                    id=review_item_id(ReviewItemType.FINDING, investigation.id),
                    incident_id=investigation.incident_id,
                    item_type=ReviewItemType.FINDING,
                    ref_id=investigation.id,
                    subject_id=claim.subject_id,
                    priority=outcome.priority,
                    created_at=now,
                )
            )
        self._repo.release_run_lock(claim.id, investigation.id)
        return {"recorded": True, "status": outcome.status.value}
