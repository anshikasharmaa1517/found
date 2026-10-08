"""Python code assets: the backend for every Lambda, the agent for AgentCore Runtime.

Both target Linux arm64 and Python 3.12, so they share one bundler.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3_assets as s3_assets
from constructs import Construct

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
AGENT = ROOT / "agent"
PACKAGES = ("found_core", "handlers")
AGENT_PACKAGES = ("found_agent",)
AGENT_FILES = ("main.py",)
ASSET_EXCLUDE = [
    "tests",
    "build",
    "*.egg-info",
    "**/__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
]


@jsii.implements(cdk.ILocalBundling)
class _LocalBundling:
    """Installs Linux arm64 wheels with the local pip, so Docker is only a fallback."""

    def __init__(
        self,
        source: Path = BACKEND,
        requirements: str = "requirements-lambda.txt",
        packages: tuple[str, ...] = PACKAGES,
        files: tuple[str, ...] = (),
    ) -> None:
        self._source = source
        self._requirements = requirements
        self._packages = packages
        self._files = files

    def try_bundle(self, output_dir: str, _options: object = None) -> bool:
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet",
            "-r", str(self._source / self._requirements),
            "--target", output_dir,
            "--platform", "manylinux2014_aarch64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
        ]  # fmt: skip
        if subprocess.run(cmd, check=False).returncode != 0:
            return False
        for package in self._packages:
            shutil.copytree(
                self._source / package,
                Path(output_dir) / package,
                ignore=shutil.ignore_patterns("__pycache__"),
                dirs_exist_ok=True,
            )
        for name in self._files:
            shutil.copy2(self._source / name, Path(output_dir) / name)
        return True


def _docker_command(requirements: str, copied: tuple[str, ...]) -> list[str]:
    return [
        "bash",
        "-c",
        f"pip install -r {requirements} -t /asset-output && cp -r {' '.join(copied)} /asset-output",
    ]


def _bundling(local: _LocalBundling, requirements: str, copied: tuple[str, ...]):
    return cdk.BundlingOptions(
        image=lambda_.Runtime.PYTHON_3_12.bundling_image,
        platform="linux/arm64",
        local=local,
        command=_docker_command(requirements, copied),
    )


def backend_code() -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(BACKEND),
        exclude=ASSET_EXCLUDE,
        bundling=_bundling(_LocalBundling(), "requirements-lambda.txt", PACKAGES),
    )


def agent_code(scope: Construct, construct_id: str) -> s3_assets.Asset:
    """The agent as a zip for AgentCore Runtime direct code deployment."""
    local = _LocalBundling(AGENT, "requirements.txt", AGENT_PACKAGES, AGENT_FILES)
    return s3_assets.Asset(
        scope,
        construct_id,
        path=str(AGENT),
        exclude=ASSET_EXCLUDE,
        bundling=_bundling(local, "requirements.txt", AGENT_PACKAGES + AGENT_FILES),
    )
