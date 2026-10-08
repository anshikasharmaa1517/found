"""Authorizer for the WebSocket connect route.

Browsers cannot set headers on a WebSocket, so the ID token arrives as the `token`
query parameter over TLS (design Section 5.4). The verified identity is passed to the
connect handler in the authorizer context.
"""

from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.adapters.cognito_jwt import InvalidToken
from found_core.domain.auth import Caller
from found_core.domain.errors import Unauthenticated

logger = Logger(service="ws_authorizer")


def _policy(
    principal: str, effect: str, resource: str, context: dict[str, str] | None = None
) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}],
        },
    }
    if context:
        policy["context"] = context
    return policy


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    resource = event["methodArn"]
    token = (event.get("queryStringParameters") or {}).get("token") or ""
    try:
        caller = Caller.from_claims(container.token_verifier().verify(token))
    except (InvalidToken, Unauthenticated) as err:
        logger.info("connection refused", extra={"reason": str(err)})
        return _policy("anonymous", "Deny", resource)
    return _policy(
        caller.user_id,
        "Allow",
        resource,
        {
            "user_id": caller.user_id,
            "groups": " ".join(sorted(caller.groups)),
            "org_id": caller.org_id or "",
        },
    )
