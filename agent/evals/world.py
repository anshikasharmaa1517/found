"""One eval case as a live incident in memory, with the real tools behind the agent.

The tools are `found_core`'s `AgentToolService`, the same code the Gateway Lambda runs,
so every citation is checked against stored text and code decides the outcome exactly
as in production. Only the transport differs: tools are called in process.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import InvestigationStatus
from found_core.domain.ids import source_id
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import Claim, Investigation, Settings, Source
from found_core.domain.normalize import normalize_text
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService
from found_core.tools.arguments import TOOL_ARGS, TOOL_DESCRIPTIONS, input_schema
from found_core.tools.service import AgentToolService
from strands.tools import PythonAgentTool

from evals.cases import Case

INCIDENT = "inc_eval"
REVIEWER = Caller(user_id="eval", groups=frozenset({"reviewer"}))
# Gateway names tools `{target}___{tool}`; the agent sees the same names here.
TOOL_PREFIX = "found-tools___"


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class _NoQueue:
    def send(self, investigation_id: str) -> None:
        pass


def _org_id(name: str) -> str:
    return "org_" + normalize_text(name).replace(" ", "_")


@dataclass
class World:
    case: Case
    config: InvestigationConfig
    repo: InMemoryFoundRepository = field(default_factory=InMemoryFoundRepository)
    claims: dict[str, Claim] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    investigation: Investigation | None = None
    tool_log: list[tuple[str, dict[str, Any], dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def build(cls, case: Case, config: InvestigationConfig) -> "World":
        world = cls(case=case, config=config)
        world._seed()
        return world

    def _seed(self) -> None:
        repo = self.repo
        repo.add_incident(INCIDENT)
        repo.settings = Settings(live_enabled=True)
        # Every source exists before any report, so mention detection sees all of them.
        names = {r.source for r in self.case.reports} | set(self.case.silent_sources)
        for name, kind in sorted(names):
            norm = normalize_text(name)
            self.sources[name] = repo.ensure_source(
                Source(
                    id=source_id(INCIDENT, norm),
                    incident_id=INCIDENT,
                    name=name,
                    name_norm=norm,
                    source_type=kind,
                    organization_id=_org_id(name),
                )
            )
        ingest = IngestService(repo, clock=_FixedClock(), sleep=lambda _: None)
        people: dict[str, str] = {}
        for n, report in enumerate(self.case.reports):
            name, kind = report.source
            subject = (
                {"type": "PERSON", "id": people[report.person]}
                if report.person in people
                else {"type": "PERSON", "new": {"name": report.person}}
            )
            claim = ingest.publish(
                PublishCommand.parse(
                    {
                        "incident_id": INCIDENT,
                        "org_id": _org_id(name),
                        "org_name": name,
                        "org_type": kind,
                        "actor": "eval",
                        "subject": subject,
                        "claim_type": report.claim_type,
                        "original_text": report.text,
                        "external_reference": f"EVAL-{n + 1}",
                        "reported_at": report.reported_at,
                    }
                )
            ).claim
            people.setdefault(report.person, claim.subject_id)
            self.claims[report.key] = claim

        starter = InvestigationService(
            repo, InMemoryBudgetLedger(), _NoQueue(), self.config, clock=_FixedClock()
        )
        target = self.claims[self.case.target]
        investigation = starter.start(REVIEWER, target.id).investigation
        # The runner's first move: the run is RUNNING before the agent calls a tool.
        running = repo.update_investigation_if(
            investigation.id, InvestigationStatus.QUEUED, {"status": InvestigationStatus.RUNNING}
        )
        assert running is not None
        self.investigation = running

    def target(self) -> Claim:
        return self.claims[self.case.target]

    def result(self) -> Investigation:
        assert self.investigation is not None
        stored = self.repo.get_investigation(self.investigation.id)
        assert stored is not None
        return stored

    def tools(self) -> list[PythonAgentTool]:
        service = AgentToolService(self.repo, self.config, clock=_FixedClock())

        def make(name: str) -> PythonAgentTool:
            def call(tool_use: dict[str, Any], **_: Any) -> dict[str, Any]:
                arguments = dict(tool_use.get("input") or {})
                body = service.call(name, arguments)
                self.tool_log.append((name, arguments, body))
                return {
                    "toolUseId": tool_use["toolUseId"],
                    "status": "success",
                    "content": [{"text": json.dumps(body)}],
                }

            spec = {
                "name": TOOL_PREFIX + name,
                "description": TOOL_DESCRIPTIONS[name],
                "inputSchema": {"json": input_schema(TOOL_ARGS[name])},
            }
            return PythonAgentTool(TOOL_PREFIX + name, spec, call)

        return [make(name) for name in TOOL_ARGS]
