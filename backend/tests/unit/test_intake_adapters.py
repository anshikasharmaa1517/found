import io
import json
import urllib.error

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from found_core.adapters import extractors
from found_core.adapters.extractors import (
    ConverseExtractor,
    MantleExtractor,
    mantle_url,
    parse_chat_completion,
)
from found_core.adapters.s3_store import S3ObjectStore
from found_core.adapters.textract_reader import TextractReader
from found_core.ports.intake import ExtractionFailed

CANDIDATES = [{"subject_name": "Kavita Bisht", "claim_type": "SHELTERED", "span_text": "x"}]


def client(service):
    return boto3.client(
        service, region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="x"
    )


@pytest.fixture
def bucket(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="data", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        yield s3


def test_the_upload_form_pins_type_and_size(bucket):
    form = S3ObjectStore(bucket, "data").presign_post("intake/i/ijb_1/a.png", "image/png", 99, 300)
    assert form["fields"]["key"] == "intake/i/ijb_1/a.png"
    assert form["fields"]["Content-Type"] == "image/png"
    policy = json.loads(__import__("base64").b64decode(form["fields"]["policy"]))
    assert ["content-length-range", 1, 99] in policy["conditions"]
    assert {"Content-Type": "image/png"} in policy["conditions"]


def test_text_round_trips_and_size_is_checked_first(bucket):
    store = S3ObjectStore(bucket, "data")
    store.put_text("intake/i/ijb_1/pasted.txt", "Kavita Bisht is safe.")
    stored = store.read("intake/i/ijb_1/pasted.txt", 100)
    assert stored.content_type == "text/plain" and stored.data == b"Kavita Bisht is safe."
    with pytest.raises(ValueError):
        store.read("intake/i/ijb_1/pasted.txt", 5)


def test_textract_lines_are_joined():
    textract = client("textract")
    stub = Stubber(textract)
    stub.add_response(
        "detect_document_text",
        {
            "Blocks": [
                {"BlockType": "PAGE"},
                {"BlockType": "LINE", "Text": "Kavita Bisht, 29"},
                {"BlockType": "WORD", "Text": "Kavita"},
                {"BlockType": "LINE", "Text": "staying in hall B"},
            ]
        },
        {"Document": {"S3Object": {"Bucket": "data", "Name": "intake/k"}}},
    )
    with stub:
        assert TextractReader(textract, "data").read_text("intake/k") == (
            "Kavita Bisht, 29\nstaying in hall B"
        )


def test_textract_throttling_is_left_to_the_workflow_and_other_errors_fail():
    from botocore.exceptions import ClientError

    textract = client("textract")
    stub = Stubber(textract)
    stub.add_client_error("detect_document_text", service_error_code="ThrottlingException")
    stub.add_client_error("detect_document_text", service_error_code="BadDocumentException")
    with stub:
        with pytest.raises(ClientError):
            TextractReader(textract, "data").read_text("k")
        with pytest.raises(ExtractionFailed, match="TEXTRACT_BadDocumentException"):
            TextractReader(textract, "data").read_text("k")


def test_converse_forces_the_tool_and_reads_its_input():
    runtime = client("bedrock-runtime")
    stub = Stubber(runtime)
    stub.add_response(
        "converse",
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "t1",
                                "name": "emit_candidates",
                                "input": {"candidates": CANDIDATES},
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1},
        },
    )
    with stub:
        assert ConverseExtractor(runtime, "model-x").extract("text") == CANDIDATES


def test_mantle_request_forces_the_tool_and_marks_text_untrusted():
    body = MantleExtractor(mantle_url("ap-south-1"), "key", "model-x").request_body("Kavita")
    assert body["tool_choice"] == {"type": "function", "function": {"name": "emit_candidates"}}
    assert body["messages"][1]["content"] == "<text_untrusted>\nKavita\n</text_untrusted>"
    assert mantle_url("ap-south-1") == "https://bedrock-mantle.ap-south-1.api.aws/v1"


def test_mantle_tool_arguments_are_parsed():
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "emit_candidates",
                                "arguments": json.dumps({"candidates": CANDIDATES}),
                            }
                        }
                    ]
                }
            }
        ]
    }
    assert parse_chat_completion(payload) == CANDIDATES


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"choices": [{"message": {"content": "No tool."}}]}, "MODEL_NO_TOOL_CALL"),
        (
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "emit_candidates", "arguments": "{not json"}}
                            ]
                        }
                    }
                ]
            },
            "MODEL_INVALID_JSON",
        ),
        (
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "emit_candidates", "arguments": "{}"}}
                            ]
                        }
                    }
                ]
            },
            "MODEL_INVALID_OUTPUT",
        ),
    ],
)
def test_unusable_model_output_has_a_reason(payload, reason):
    with pytest.raises(ExtractionFailed) as err:
        parse_chat_completion(payload)
    assert err.value.reason == reason


def test_mantle_http_errors_have_a_reason(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

    monkeypatch.setattr(extractors.urllib.request, "urlopen", refuse)
    with pytest.raises(ExtractionFailed) as err:
        MantleExtractor(mantle_url("ap-south-1"), "key", "model-x").extract("text")
    assert err.value.reason == "MODEL_HTTP_403"
