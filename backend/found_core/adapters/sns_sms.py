"""Text messages through Amazon SNS. Used only where SMS is switched on for the env."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from found_core.ports.channels import DeliveryRejected, DeliveryUnavailable

_PERMANENT = frozenset(
    {"InvalidParameter", "InvalidParameterValue", "OptedOut", "AuthorizationError"}
)


class SnsSms:
    name = "sms"

    def __init__(self, client: Any) -> None:
        self._client = client

    def send(self, to: str, subject: str, text: str) -> None:
        try:
            self._client.publish(
                PhoneNumber=to,
                Message=text,
                MessageAttributes={
                    "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}
                },
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in _PERMANENT:
                raise DeliveryRejected(code) from err
            raise DeliveryUnavailable(code or "ClientError") from err
        except BotoCoreError as err:
            raise DeliveryUnavailable(type(err).__name__) from err
