"""Verifies Cognito ID tokens where API Gateway cannot, such as the WebSocket connect."""

from typing import Any

import jwt


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not ours."""


class CognitoTokenVerifier:
    def __init__(
        self, region: str, user_pool_id: str, client_id: str, jwks: Any | None = None
    ) -> None:
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._client_id = client_id
        # Keys are fetched once and cached for the life of the execution environment.
        self._jwks = jwks or jwt.PyJWKClient(f"{self._issuer}/.well-known/jwks.json")

    def verify(self, token: str) -> dict[str, Any]:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError) as err:
            raise InvalidToken(str(err)) from err
        # Access tokens carry no groups or org; only ID tokens are accepted.
        if claims.get("token_use") != "id":
            raise InvalidToken("not an ID token")
        return claims
