import pytest

from found_core import container
from found_core.domain.enums import InvestigationStatus
from found_core.services.runner import RunResult
from handlers import investigation_runner


class Context:
    function_name = "investigation_runner"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:runner"
    aws_request_id = "req-1"


class FakeRunner:
    def __init__(self, error=None):
        self.error = error
        self.ran = []
        self.failed = []

    def run(self, investigation_id):
        self.ran.append(investigation_id)
        if self.error:
            raise self.error
        return RunResult(investigation_id, InvestigationStatus.NEEDS_REVIEW, steps=4)

    def fail_queued(self, investigation_id, reason):
        self.failed.append((investigation_id, reason))
        return True


def record(body, receives="1", message_id="m1"):
    return {
        "messageId": message_id,
        "body": body,
        "attributes": {"ApproximateReceiveCount": receives},
    }


@pytest.fixture
def use(monkeypatch):
    def install(runner):
        monkeypatch.setattr(container, "investigation_runner", lambda: runner)
        return runner

    return install


def test_runs_the_named_investigation(use):
    runner = use(FakeRunner())
    result = investigation_runner.handler(
        {"Records": [record('{"investigation_id": "inv_1"}')]}, Context()
    )
    assert result == {"batchItemFailures": []}
    assert runner.ran == ["inv_1"]


@pytest.mark.parametrize("body", ["not json", "{}", '{"investigation_id": 7}', '["inv_1"]'])
def test_malformed_messages_are_dropped(use, body):
    runner = use(FakeRunner())
    assert investigation_runner.handler({"Records": [record(body)]}, Context()) == {
        "batchItemFailures": []
    }
    assert runner.ran == []


def test_infrastructure_errors_are_retried(use):
    runner = use(FakeRunner(RuntimeError("throttled")))
    result = investigation_runner.handler(
        {"Records": [record('{"investigation_id": "inv_1"}')]}, Context()
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert runner.failed == []


def test_last_attempt_fails_the_run_before_dead_lettering(use):
    runner = use(FakeRunner(RuntimeError("throttled")))
    investigation_runner.handler(
        {"Records": [record('{"investigation_id": "inv_1"}', receives="2")]}, Context()
    )
    assert runner.failed == [("inv_1", "RUNNER_ERROR")]
