"""Email through Amazon SES. In the SES sandbox only verified addresses receive mail."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from found_core.ports.channels import DeliveryRejected, DeliveryUnavailable

# Errors that will not change on a retry.
_PERMANENT = frozenset(
    {
        "MessageRejected",
        "MailFromDomainNotVerifiedException",
        "ConfigurationSetDoesNotExistException",
        "AccountSendingPausedException",
        "InvalidParameterValue",
    }
)


class SesEmail:
    name = "email"

    def __init__(self, client: Any, sender: str) -> None:
        self._client = client
        self._sender = sender

    def send(self, to: str, subject: str, text: str) -> None:
        try:
            self._client.send_email(
                Source=self._sender,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
                },
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in _PERMANENT:
                raise DeliveryRejected(code) from err
            raise DeliveryUnavailable(code or "ClientError") from err
        except BotoCoreError as err:
            raise DeliveryUnavailable(type(err).__name__) from err
