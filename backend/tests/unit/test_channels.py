import boto3
import pytest
from botocore.stub import Stubber

from found_core.adapters.ses_email import SesEmail
from found_core.adapters.sns_sms import SnsSms
from found_core.ports.channels import DeliveryRejected, DeliveryUnavailable


def ses():
    client = boto3.client(
        "ses", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    return client, Stubber(client)


def sns():
    client = boto3.client(
        "sns", region_name="ap-south-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    return client, Stubber(client)


def test_email_is_sent_as_plain_text_from_the_sender():
    client, stub = ses()
    stub.add_response(
        "send_email",
        {"MessageId": "m-1"},
        {
            "Source": "alerts@example.org",
            "Destination": {"ToAddresses": ["family@example.com"]},
            "Message": {
                "Subject": {"Data": "Subject", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "Body", "Charset": "UTF-8"}},
            },
        },
    )
    with stub:
        SesEmail(client, "alerts@example.org").send("family@example.com", "Subject", "Body")
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "code, error",
    [("MessageRejected", DeliveryRejected), ("Throttling", DeliveryUnavailable)],
)
def test_email_errors_say_whether_a_retry_can_help(code, error):
    client, stub = ses()
    stub.add_client_error("send_email", service_error_code=code)
    with stub, pytest.raises(error):
        SesEmail(client, "alerts@example.org").send("family@example.com", "s", "t")


def test_sms_is_sent_as_transactional():
    client, stub = sns()
    stub.add_response(
        "publish",
        {"MessageId": "m-1"},
        {
            "PhoneNumber": "+919876543210",
            "Message": "Body",
            "MessageAttributes": {
                "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}
            },
        },
    )
    with stub:
        SnsSms(client).send("+919876543210", "Subject", "Body")
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "code, error",
    [("OptedOut", DeliveryRejected), ("InternalError", DeliveryUnavailable)],
)
def test_sms_errors_say_whether_a_retry_can_help(code, error):
    client, stub = sns()
    stub.add_client_error("publish", service_error_code=code)
    with stub, pytest.raises(error):
        SnsSms(client).send("+919876543210", "s", "t")
