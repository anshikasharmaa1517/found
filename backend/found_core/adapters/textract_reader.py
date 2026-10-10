"""Reads printed or handwritten lines from an intake image or single-page PDF."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from found_core.ports.intake import ExtractionFailed

_RETRYABLE = frozenset(
    {"ThrottlingException", "ProvisionedThroughputExceededException", "InternalServerError"}
)


class TextractReader:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def read_text(self, key: str) -> str:
        try:
            resp = self._client.detect_document_text(
                Document={"S3Object": {"Bucket": self._bucket, "Name": key}}
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in _RETRYABLE:
                raise  # The workflow retries this step with backoff.
            raise ExtractionFailed(f"TEXTRACT_{code or 'ERROR'}") from err
        except BotoCoreError as err:
            raise ExtractionFailed("TEXTRACT_UNREACHABLE") from err
        lines = [b["Text"] for b in resp.get("Blocks", []) if b.get("BlockType") == "LINE"]
        return "\n".join(lines)
