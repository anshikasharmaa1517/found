"""Cognito user pool, role groups and the web app client (design Sections 4.3 and 7.1)."""

import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from config import EnvConfig

# Lower precedence wins when a user is in several groups.
ROLES = {"admin": 0, "reviewer": 1, "publisher": 2, "family": 3}
ORG_ATTRIBUTE = "org_id"


class AuthStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Accounts are created by an admin, who also sets the role and organization.
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=f"found-{cfg.name}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                fullname=cognito.StandardAttribute(required=False, mutable=True),
            ),
            custom_attributes={
                ORG_ATTRIBUTE: cognito.StringAttribute(min_len=1, max_len=64, mutable=True),
            },
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
                temp_password_validity=cdk.Duration.days(3),
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            deletion_protection=cfg.deletion_protection,
            removal_policy=(
                cdk.RemovalPolicy.RETAIN if cfg.deletion_protection else cdk.RemovalPolicy.DESTROY
            ),
        )

        for role, precedence in ROLES.items():
            cognito.CfnUserPoolGroup(
                self,
                f"Group{role.capitalize()}",
                user_pool_id=self.user_pool.user_pool_id,
                group_name=role,
                precedence=precedence,
            )

        # The organization is readable by the app but only an admin can set it, so a user
        # can never move themselves into another organization.
        self.web_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"found-{cfg.name}-web",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            disable_o_auth=True,
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            id_token_validity=cdk.Duration.hours(1),
            access_token_validity=cdk.Duration.hours(1),
            refresh_token_validity=cdk.Duration.days(30),
            read_attributes=cognito.ClientAttributes()
            .with_standard_attributes(email=True, email_verified=True, fullname=True)
            .with_custom_attributes(ORG_ATTRIBUTE),
            write_attributes=cognito.ClientAttributes().with_standard_attributes(fullname=True),
        )

        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.web_client.user_pool_client_id)
        cdk.CfnOutput(
            self,
            "IssuerUrl",
            value=f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}",
        )
