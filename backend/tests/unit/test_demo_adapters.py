import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from found_core import container
from found_core.adapters.fixtures import DirectoryFixtures, LambdaResetTrigger, S3Fixtures
from found_core.fixtures import FILES
from handlers import demo_reset

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "demo-v1"


def test_directory_and_s3_fixtures_read_the_same_files(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    local = DirectoryFixtures(FIXTURES).read()
    assert set(local) == set(FILES)
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="fixtures", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        for name in FILES:
            s3.put_object(
                Bucket="fixtures", Key=f"demo-v1/{name}", Body=(FIXTURES / name).read_bytes()
            )
        assert S3Fixtures(s3, "fixtures", "demo-v1/").read() == local


def test_reset_trigger_invokes_the_worker_without_waiting():
    class Lambda:
        def __init__(self):
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)

    client = Lambda()
    LambdaResetTrigger(client, "found-dev-demo-reset").start("inc_demo", "adm_1")
    (call,) = client.calls
    assert call["FunctionName"] == "found-dev-demo-reset" and call["InvocationType"] == "Event"
    assert json.loads(call["Payload"]) == {"incident_id": "inc_demo", "actor": "adm_1"}


class Context:
    function_name = "demo_reset"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:demo_reset"
    aws_request_id = "req-1"


def test_worker_runs_the_reset(monkeypatch):
    from found_core.services.demo import ResetResult

    calls = []

    class Demo:
        def reset(self, incident_id, actor):
            calls.append((incident_id, actor))
            return ResetResult(incident_id, 3, 56, 0)

    monkeypatch.setattr(container, "demo_service", lambda: Demo())
    result = demo_reset.handler({"incident_id": "inc_demo", "actor": "adm_1"}, Context())
    assert result == {"incident_id": "inc_demo", "removed": 3, "published": 56, "replayed_runs": 0}
    assert calls == [("inc_demo", "adm_1")]


@pytest.fixture
def api_world(monkeypatch):
    from found_core.adapters.memory import InMemoryFoundRepository
    from found_core.services.demo import DemoService
    from found_core.services.ingest import IngestService

    class Trigger:
        def __init__(self):
            self.started = []

        def start(self, incident_id, actor):
            self.started.append((incident_id, actor))

    repo = InMemoryFoundRepository()
    trigger = Trigger()
    demo = DemoService(
        repo, IngestService(repo, sleep=lambda _: None), DirectoryFixtures(FIXTURES), trigger
    )
    demo.reset("inc_demo", "adm_0")
    monkeypatch.setattr(container, "demo_service", lambda: demo)
    return trigger


def test_admin_routes(api_world):
    from tests.unit.test_api_handler import call, event

    admin = {"sub": "adm_1", "cognito:groups": "[admin]"}
    reviewer = {"sub": "rev_1", "cognito:groups": "[reviewer]"}
    status, body, _ = call(event("POST", "/v1/admin/incidents/inc_demo/reset", None, admin))
    assert status == 202 and body == {"incident_id": "inc_demo", "status": "RESETTING"}
    assert api_world.started == [("inc_demo", "adm_1")]
    assert call(event("POST", "/v1/admin/incidents/inc_demo/reset", None, reviewer))[0] == 403
    assert call(event("POST", "/v1/admin/incidents/inc_x/reset", None, admin))[0] == 400
    assert call(event("GET", "/v1/admin/investigations/inv_x/recording", claims=admin))[0] == 404

    status, body, _ = call(event("GET", "/v1/incidents/inc_demo/activity", claims=reviewer))
    assert status == 200
    messages = [a["message"] for a in body["activity"]]
    assert messages[0] == "Demo reset requested" and messages[1].startswith("Demo reset:")
