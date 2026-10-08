"""MCP client for AgentCore Gateway, signed with the runtime role (SigV4).

Gateway checks the signature against its IAM inbound authorizer, so no shared secret is
stored in the runtime.
"""

from collections.abc import Generator
from typing import Any

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from strands.tools.mcp import MCPClient

SIGNING_SERVICE = "bedrock-agentcore"
# Hop-by-hop headers can change in transit, so they are left out of the signature.
_UNSIGNED = frozenset({"connection", "content-length", "transfer-encoding", "user-agent"})


class SigV4HttpxAuth(httpx.Auth):
    requires_request_body = True

    def __init__(self, session: Any, region: str, service: str = SIGNING_SERVICE) -> None:
        self._session = session
        self._region = region
        self._service = service

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        credentials = self._session.get_credentials().get_frozen_credentials()
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() not in _UNSIGNED},
        )
        SigV4Auth(credentials, self._service, self._region).add_auth(signed)
        request.headers.update(dict(signed.headers.items()))
        yield request


def gateway_client(url: str, region: str, session: Any | None = None) -> MCPClient:
    auth = SigV4HttpxAuth(session or boto3.Session(region_name=region), region)
    return MCPClient(url=url, auth_provider=auth, application_name="found-agent")
