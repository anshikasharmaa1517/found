"""ConnectionGateway over the API Gateway management API of the WebSocket stage."""

from typing import Any

from botocore.exceptions import ClientError


def _gone(err: ClientError) -> bool:
    return err.response.get("Error", {}).get("Code") == "GoneException"


class ApiGatewayConnections:
    def __init__(self, client: Any) -> None:
        self._client = client

    def send(self, connection_id: str, data: bytes) -> bool:
        try:
            self._client.post_to_connection(ConnectionId=connection_id, Data=data)
            return True
        except ClientError as err:
            if _gone(err):
                return False
            raise

    def close(self, connection_id: str) -> None:
        try:
            self._client.delete_connection(ConnectionId=connection_id)
        except ClientError as err:
            if not _gone(err):
                raise
