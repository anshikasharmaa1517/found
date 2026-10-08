"""Run queue producer. The body names the investigation and nothing else."""

import json
from typing import Any


def run_message(investigation_id: str) -> str:
    return json.dumps({"investigation_id": investigation_id})


class SqsInvestigationQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def send(self, investigation_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=run_message(investigation_id)
        )
