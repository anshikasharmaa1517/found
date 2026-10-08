"""Amazon Location basemap access for the web app (design Sections 4.3 and 15).

The browser fetches map tiles with an API key. The key can only read tiles from the
default provider and only for the app's own origins, so it is safe to ship in the app.
"""

import aws_cdk as cdk
from aws_cdk import aws_location as location
from constructs import Construct

from config import EnvConfig

MAP_ACTIONS = ["geo-maps:GetTile", "geo-maps:GetStaticMap"]


class MapsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.key_name = f"found-{cfg.name}-web-maps"
        self.api_key = location.CfnAPIKey(
            self,
            "WebMapsKey",
            key_name=self.key_name,
            description="Basemap tiles for the web app. Read only, limited to the app's origins.",
            no_expiry=True,
            restrictions=location.CfnAPIKey.ApiKeyRestrictionsProperty(
                allow_actions=MAP_ACTIONS,
                allow_resources=[f"arn:{self.partition}:geo-maps:{self.region}::provider/default"],
                allow_referers=[f"{origin.rstrip('/')}/*" for origin in cfg.web_origins],
            ),
        )

        cdk.CfnOutput(self, "MapsKeyName", value=self.key_name)
        # CloudFormation cannot return the key value; read it once for web/.env.local.
        cdk.CfnOutput(
            self,
            "MapsKeyCommand",
            value=f"aws location describe-key --key-name {self.key_name} --query Key --output text",
        )
