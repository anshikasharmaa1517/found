"""Intake objects in the data bucket."""

from typing import Any

from found_core.ports.intake import StoredObject


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def presign_post(
        self, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> dict[str, Any]:
        # The policy pins the key, the exact type and the size, so S3 refuses anything else.
        return self._client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires_in,
        )

    def put_text(self, key: str, text: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )

    def read(self, key: str, max_bytes: int) -> StoredObject:
        head = self._client.head_object(Bucket=self._bucket, Key=key)
        size = int(head["ContentLength"])
        if size > max_bytes:
            raise ValueError(f"object is {size} bytes, over the {max_bytes} limit")
        body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read(max_bytes + 1)
        content_type = str(head.get("ContentType", "")).split(";")[0].strip()
        return StoredObject(content_type=content_type, size=len(body), data=body)
