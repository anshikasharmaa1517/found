import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from config import load
from stacks.auth_stack import AuthStack

ENVS = {
    "dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]},
    "demo": {"deletion_protection": True, "web_origins": ["https://demo.example.org"]},
}


def template(env_name: str = "dev") -> Template:
    app = cdk.App()
    stack = AuthStack(
        app,
        "Auth",
        cfg=load(env_name, ENVS),
        env=cdk.Environment(account="111111111111", region="ap-south-1"),
    )
    return Template.from_stack(stack)


def pool(t: Template) -> dict:
    return next(iter(t.find_resources("AWS::Cognito::UserPool").values()))


def client(t: Template) -> dict:
    return next(iter(t.find_resources("AWS::Cognito::UserPoolClient").values()))["Properties"]


def test_only_admins_create_accounts():
    props = pool(template())["Properties"]
    assert props["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert props["UsernameAttributes"] == ["email"]
    assert props["AutoVerifiedAttributes"] == ["email"]


def test_pool_has_org_attribute():
    schema = pool(template())["Properties"]["Schema"]
    org = next(a for a in schema if a["Name"] == "org_id")
    assert org["AttributeDataType"] == "String"
    assert org["StringAttributeConstraints"] == {"MinLength": "1", "MaxLength": "64"}


def test_password_and_mfa_policy():
    props = pool(template())["Properties"]
    policy = props["Policies"]["PasswordPolicy"]
    assert policy["MinimumLength"] == 12
    assert props["MfaConfiguration"] == "OPTIONAL"
    assert props["EnabledMfas"] == ["SOFTWARE_TOKEN_MFA"]


def test_role_groups_exist_with_precedence():
    groups = template().find_resources("AWS::Cognito::UserPoolGroup")
    found = {g["Properties"]["GroupName"]: g["Properties"]["Precedence"] for g in groups.values()}
    assert found == {"admin": 0, "reviewer": 1, "publisher": 2, "family": 3}


def test_web_client_is_public_srp_only():
    props = client(template())
    assert props.get("GenerateSecret") in (None, False)
    assert set(props["ExplicitAuthFlows"]) == {"ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"}
    assert props["PreventUserExistenceErrors"] == "ENABLED"
    assert props["EnableTokenRevocation"] is True
    assert "AllowedOAuthFlows" not in props


def test_users_can_read_but_never_write_their_organization():
    props = client(template())
    assert "custom:org_id" in props["ReadAttributes"]
    assert "custom:org_id" not in props["WriteAttributes"]
    # Cognito refuses a client that cannot write a required attribute (email).
    assert sorted(props["WriteAttributes"]) == ["email", "name"]


def test_token_lifetimes():
    props = client(template())
    assert props["IdTokenValidity"] == 60
    assert props["AccessTokenValidity"] == 60
    assert props["RefreshTokenValidity"] == 43200
    assert props["TokenValidityUnits"] == {
        "IdToken": "minutes",
        "AccessToken": "minutes",
        "RefreshToken": "minutes",
    }


@pytest.mark.parametrize(
    ("env_name", "policy", "protection"),
    [("dev", "Delete", "INACTIVE"), ("demo", "Retain", "ACTIVE")],
)
def test_pool_protection_follows_environment(env_name, policy, protection):
    resource = pool(template(env_name))
    assert resource["DeletionPolicy"] == policy
    assert resource["Properties"]["DeletionProtection"] == protection


def test_stack_exports_pool_client_and_issuer():
    outputs = template().find_outputs("*")
    assert {"UserPoolId", "UserPoolClientId", "IssuerUrl"} <= set(outputs)
