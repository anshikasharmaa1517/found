"""Builds services once per cold start. Settings come from the Lambda environment."""

import os
from functools import cache

from found_core.ports.repository import FoundRepository
from found_core.services.ingest import IngestService
from found_core.services.reports import ReportService


@cache
def repository() -> FoundRepository:
    import boto3

    from found_core.adapters.dynamodb import DynamoFoundRepository

    return DynamoFoundRepository(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))


@cache
def report_service() -> ReportService:
    repo = repository()
    return ReportService(repo, IngestService(repo))
