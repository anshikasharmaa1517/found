"""Where the demo dataset is read from, and how a reset is started."""

import json
from pathlib import Path
from typing import Any

from found_core.fixtures import FILES


class DirectoryFixtures:
    """`data/fixtures/<version>` on disk, for local runs and tests."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, Any]:
        return {name: json.loads((self._path / name).read_text(encoding="utf-8")) for name in FILES}


class S3Fixtures:
    """The same files, deployed to the fixtures bucket under `prefix`."""

    def __init__(self, client: Any, bucket: str, prefix: str) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")

    def read(self) -> dict[str, Any]:
        files = {}
        for name in FILES:
            body = self._client.get_object(Bucket=self._bucket, Key=f"{self._prefix}/{name}")
            files[name] = json.loads(body["Body"].read())
        return files


class LambdaResetTrigger:
    """Invokes the reset worker without waiting, so the API answers at once."""

    def __init__(self, client: Any, function_name: str) -> None:
        self._client = client
        self._function_name = function_name

    def start(self, incident_id: str, actor: str) -> None:
        self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=json.dumps({"incident_id": incident_id, "actor": actor}).encode(),
        )
