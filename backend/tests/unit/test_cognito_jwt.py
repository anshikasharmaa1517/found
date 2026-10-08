import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from found_core.adapters.cognito_jwt import CognitoTokenVerifier, InvalidToken

REGION, POOL, CLIENT = "ap-south-1", "ap-south-1_Pool", "client123"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Stands in for the pool's JWKS endpoint."""

    class _Signing:
        def __init__(self, key):
            self.key = key

    def get_signing_key_from_jwt(self, token):
        try:
            jwt.get_unverified_header(token)
        except jwt.PyJWTError as err:
            raise jwt.PyJWKClientError(str(err)) from err
        return self._Signing(KEY.public_key())


def token(key=KEY, **overrides):
    now = int(time.time())
    claims = {
        "sub": "user_1",
        "iss": ISSUER,
        "aud": CLIENT,
        "token_use": "id",
        "iat": now,
        "exp": now + 3600,
        "cognito:groups": ["reviewer"],
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def verifier():
    return CognitoTokenVerifier(REGION, POOL, CLIENT, jwks=FakeJwks())


def test_valid_id_token_returns_claims(verifier):
    claims = verifier.verify(token())
    assert claims["sub"] == "user_1" and claims["cognito:groups"] == ["reviewer"]


@pytest.mark.parametrize(
    "bad",
    [
        lambda: token(key=OTHER_KEY),
        lambda: token(exp=int(time.time()) - 10),
        lambda: token(aud="other-client"),
        lambda: token(iss="https://cognito-idp.ap-south-1.amazonaws.com/other"),
        lambda: token(token_use="access"),
        lambda: token(sub=None),
        lambda: "not-a-token",
        lambda: "",
    ],
    ids=["wrong-key", "expired", "audience", "issuer", "access", "no-sub", "garbage", "empty"],
)
def test_bad_tokens_are_rejected(verifier, bad):
    with pytest.raises(InvalidToken):
        verifier.verify(bad())


def test_hs256_token_signed_with_public_key_is_rejected(verifier):
    public_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    forged = jwt.encode(
        {"sub": "u", "iss": ISSUER, "aud": CLIENT, "token_use": "id",
         "iat": int(time.time()), "exp": int(time.time()) + 60},
        public_pem.decode()[:32],
        algorithm="HS256",
    )  # fmt: skip
    with pytest.raises(InvalidToken):
        verifier.verify(forged)
