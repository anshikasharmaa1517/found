import aws_cdk as cdk
from aws_cdk.assertions import Template

from config import load
from stacks.maps_stack import MapsStack

ENVS = {
    "dev": {
        "deletion_protection": False,
        "web_origins": ["http://localhost:5173", "https://found.example.org/"],
    }
}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template() -> Template:
    app = cdk.App()
    return Template.from_stack(MapsStack(app, "Maps", cfg=load("dev", ENVS), env=ENV))


def test_key_reads_tiles_only_from_the_app_origins():
    template().has_resource_properties(
        "AWS::Location::APIKey",
        {
            "KeyName": "found-dev-web-maps",
            "NoExpiry": True,
            "Restrictions": {
                "AllowActions": ["geo-maps:GetTile", "geo-maps:GetStaticMap"],
                "AllowResources": [
                    {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {"Ref": "AWS::Partition"},
                                ":geo-maps:ap-south-1::provider/default",
                            ],
                        ]
                    }
                ],
                "AllowReferers": ["http://localhost:5173/*", "https://found.example.org/*"],
            },
        },
    )


def test_outputs_explain_how_to_read_the_key():
    outputs = template().find_outputs("*")
    assert outputs["MapsKeyName"]["Value"] == "found-dev-web-maps"
    assert "describe-key --key-name found-dev-web-maps" in outputs["MapsKeyCommand"]["Value"]
