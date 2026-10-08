"""The backend package as Lambda code, shared by every Python function."""

import shutil
import subprocess
import sys
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import aws_lambda as lambda_

BACKEND = Path(__file__).resolve().parents[2] / "backend"
PACKAGES = ("found_core", "handlers")
ASSET_EXCLUDE = ["tests", "build", "*.egg-info", "**/__pycache__", ".pytest_cache", ".ruff_cache"]


@jsii.implements(cdk.ILocalBundling)
class _LocalBundling:
    """Installs Linux arm64 wheels with the local pip, so Docker is only a fallback."""

    def try_bundle(self, output_dir: str, _options: object = None) -> bool:
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet",
            "-r", str(BACKEND / "requirements-lambda.txt"),
            "--target", output_dir,
            "--platform", "manylinux2014_aarch64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
        ]  # fmt: skip
        if subprocess.run(cmd, check=False).returncode != 0:
            return False
        for package in PACKAGES:
            shutil.copytree(
                BACKEND / package,
                Path(output_dir) / package,
                ignore=shutil.ignore_patterns("__pycache__"),
                dirs_exist_ok=True,
            )
        return True


def backend_code() -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(BACKEND),
        exclude=ASSET_EXCLUDE,
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            platform="linux/arm64",
            local=_LocalBundling(),
            command=[
                "bash",
                "-c",
                "pip install -r requirements-lambda.txt -t /asset-output"
                " && cp -r found_core handlers /asset-output",
            ],
        ),
    )
