"""DynamoDB repository over the single table `found-main` (design Section 8.5).

Publish is one TransactWriteItems call (design Section 9.5). Cancellation reasons are
read per item to tell an idempotency conflict from a sequence conflict.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from found_core.domain.enums import (
    DeliveryStatus,
    InvestigationStatus,
    ReviewItemType,
    ReviewStatus,
    SubjectType,
)
from found_core.domain.investigation import CACHEABLE_STATUSES
from found_core.domain.models import (
    Activity,
    Alert,
    Claim,
    Connection,
    IdemMarker,
    Incident,
    Investigation,
    InvestigationStep,
    Location,
    Organization,
    ReviewItem,
    Settings,
    Source,
    Subject,
    Subscription,
)
from found_core.ports.budget import BudgetUsage
from found_core.ports.repository import (
    IdempotencyConflict,
    NamePosition,
    PublishPlan,
    SequenceConflict,
)

SCHEMA_VERSION = 1

_KEY_ATTRS = frozenset(
    {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"}
)
_META_ATTRS = _KEY_ATTRS | {"entity_type", "schema_version", "ttl"}

_ALERT_POSITION_KEYS = frozenset({"PK", "SK", "GSI1PK", "GSI1SK"})

# BatchGetItem accepts at most this many keys per call.
_BATCH_GET_MAX = 100
_BATCH_GET_ATTEMPTS = 5

# Attempts to take a run lock when its holder vanishes between the put and the read.
_LOCK_ATTEMPTS = 3

# Positions of the conditional items in the publish transaction.
_TX_MARKER, _TX_SUBJECT, _TX_CLAIM, _TX_SOURCE = 0, 1, 2, 3


def incident_key(incident_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": "META"}


def organization_key(incident_id: str, org_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"ORG#{org_id}"}


def source_key(incident_id: str, source_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"SRC#{source_id}"}


def location_key(incident_id: str, loc_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"LOC#{loc_id}"}


def subject_key(subject_id: str) -> dict[str, str]:
    return {"PK": f"SUBJ#{subject_id}", "SK": "META"}


def subject_list_pk(incident_id: str, subject_type: SubjectType) -> str:
    return f"INC#{incident_id}#{subject_type}"


def subject_list_sk(name_norm: str, subject_id: str) -> str:
    return f"{name_norm}#{subject_id}"


def claim_key(subject_id: str, seq: int) -> dict[str, str]:
    return {"PK": f"SUBJ#{subject_id}", "SK": f"CLM#{seq:010d}"}


def subscription_key(subject_id: str, subscription_id: str) -> dict[str, str]:
    return {"PK": f"SUBJ#{subject_id}", "SK": f"SUB#{subscription_id}"}


def connection_key(connection_id: str) -> dict[str, str]:
    return {"PK": f"CONN#{connection_id}", "SK": "META"}


def alert_key(subscription_id: str, claim_id: str) -> dict[str, str]:
    return {"PK": f"SUB#{subscription_id}", "SK": f"ALR#{claim_id}"}


def review_item_key(incident_id: str, review_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"REV#{review_id}"}


def marker_key(org_id: str, external_reference: str) -> dict[str, str]:
    return {"PK": f"IDEM#{org_id}#{external_reference}", "SK": "META"}


def investigation_key(investigation_id: str) -> dict[str, str]:
    return {"PK": f"INV#{investigation_id}", "SK": "META"}


def investigation_step_key(investigation_id: str, seq: int) -> dict[str, str]:
    return {"PK": f"INV#{investigation_id}", "SK": f"STEP#{seq:04d}"}


def run_lock_key(claim_id: str) -> dict[str, str]:
    return {"PK": f"LOCK#INV#{claim_id}", "SK": "META"}


SETTINGS_KEY = {"PK": "SETTINGS", "SK": "META"}


def budget_key(period: str) -> dict[str, str]:
    return {"PK": f"BUDGET#{period}", "SK": "META"}


def _attrs(model: Any) -> dict[str, Any]:
    return {k: v for k, v in model.model_dump(mode="json").items() if v is not None}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _fields(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _plain(v) for k, v in item.items() if k not in _META_ATTRS}


def activity_key(activity: Activity) -> dict[str, str]:
    created = activity.model_dump(mode="json")["created_at"]
    return {"PK": f"INC#{activity.incident_id}", "SK": f"ACT#{created}#{activity.id}"}


def activity_item(activity: Activity) -> dict[str, Any]:
    return {
        **activity_key(activity),
        "entity_type": "ACTIVITY",
        "schema_version": SCHEMA_VERSION,
        **_attrs(activity),
    }


def incident_item(incident: Incident) -> dict[str, Any]:
    attrs = _attrs(incident)
    return {
        **incident_key(incident.id),
        "GSI1PK": "LIST#INCIDENT",
        "GSI1SK": f"{attrs.get('started_at', '0')}#{incident.id}",
        "entity_type": "INCIDENT",
        "schema_version": SCHEMA_VERSION,
        "incident_id": incident.id,
        **attrs,
    }


def organization_item(org: Organization) -> dict[str, Any]:
    return {
        **organization_key(org.incident_id, org.id),
        "entity_type": "ORGANIZATION",
        "schema_version": SCHEMA_VERSION,
        **_attrs(org),
    }


def source_item(source: Source) -> dict[str, Any]:
    return {
        **source_key(source.incident_id, source.id),
        "entity_type": "SOURCE",
        "schema_version": SCHEMA_VERSION,
        **_attrs(source),
    }


def location_item(location: Location) -> dict[str, Any]:
    attrs = _attrs(location)
    # DynamoDB stores numbers as Decimal; str() keeps the value exactly as given.
    for axis in ("lat", "lon"):
        if axis in attrs:
            attrs[axis] = Decimal(str(attrs[axis]))
    return {
        **location_key(location.incident_id, location.id),
        "entity_type": "LOCATION",
        "schema_version": SCHEMA_VERSION,
        **attrs,
    }


def subject_item(subject: Subject) -> dict[str, Any]:
    return {
        **subject_key(subject.id),
        "GSI1PK": subject_list_pk(subject.incident_id, subject.subject_type),
        "GSI1SK": subject_list_sk(subject.name_norm, subject.id),
        "entity_type": "SUBJECT",
        "schema_version": SCHEMA_VERSION,
        **_attrs(subject),
    }


def claim_item(claim: Claim) -> dict[str, Any]:
    attrs = _attrs(claim)
    reported = attrs.get("reported_at", "0")
    return {
        **claim_key(claim.subject_id, claim.seq),
        "GSI1PK": f"INC#{claim.incident_id}#CLAIM",
        "GSI1SK": f"{attrs['ingested_at']}#{claim.id}",
        "GSI2PK": f"SRC#{claim.source_id}",
        "GSI2SK": f"{reported}#{claim.id}",
        "GSI3PK": f"CLAIM#{claim.id}",
        "GSI3SK": "META",
        "entity_type": "CLAIM",
        "schema_version": SCHEMA_VERSION,
        **attrs,
    }


def marker_item(marker: IdemMarker) -> dict[str, Any]:
    return {
        **marker_key(marker.org_id, marker.external_reference),
        "entity_type": "IDEM",
        "schema_version": SCHEMA_VERSION,
        **_attrs(marker),
    }


def subscription_item(subscription: Subscription) -> dict[str, Any]:
    return {
        **subscription_key(subscription.subject_id, subscription.id),
        "GSI1PK": f"USER#{subscription.user_id}",
        "GSI1SK": f"SUB#{subscription.id}",
        "entity_type": "SUBSCRIPTION",
        "schema_version": SCHEMA_VERSION,
        **_attrs(subscription),
    }


def _alert_index_keys(alert: Alert) -> dict[str, str]:
    created = alert.model_dump(mode="json")["created_at"]
    return {
        **alert_key(alert.subscription_id, alert.claim_id),
        "GSI1PK": f"USER#{alert.user_id}",
        "GSI1SK": f"ALR#{created}#{alert.id}",
    }


def alert_item(alert: Alert) -> dict[str, Any]:
    return {
        **_alert_index_keys(alert),
        "GSI3PK": f"ALERT#{alert.id}",
        "GSI3SK": "META",
        "entity_type": "ALERT",
        "schema_version": SCHEMA_VERSION,
        **_attrs(alert),
    }


def review_queue_pk(incident_id: str, status: ReviewStatus | str) -> str:
    return f"REVQ#{incident_id}#{status}"


def review_queue_sk(item: ReviewItem) -> str:
    created = item.model_dump(mode="json")["created_at"]
    return f"{item.priority}#{created}#{item.id}"


def review_item_item(item: ReviewItem) -> dict[str, Any]:
    attrs = _attrs(item)
    return {
        **review_item_key(item.incident_id, item.id),
        "GSI2PK": review_queue_pk(item.incident_id, item.status),
        "GSI2SK": review_queue_sk(item),
        "entity_type": "REVIEW_ITEM",
        "schema_version": SCHEMA_VERSION,
        **attrs,
    }


def connection_item(connection: Connection) -> dict[str, Any]:
    attrs = _attrs(connection)
    item = {
        **connection_key(connection.id),
        "GSI1PK": f"USER#{connection.user_id}",
        "GSI1SK": f"CONN#{attrs['connected_at']}#{connection.id}",
        "entity_type": "CONNECTION",
        "schema_version": SCHEMA_VERSION,
        # DynamoDB TTL removes the item some time after this; readers also check expiry.
        "ttl": int(connection.expires_at.timestamp()),
        **attrs,
    }
    if connection.incident_id:
        item["GSI3PK"] = f"WSINC#{connection.incident_id}"
        item["GSI3SK"] = f"CONN#{connection.id}"
    return item


def investigation_item(investigation: Investigation) -> dict[str, Any]:
    attrs = _attrs(investigation)
    queued = f"{attrs['queued_at']}#{investigation.id}"
    item = {
        **investigation_key(investigation.id),
        "GSI1PK": f"INC#{investigation.incident_id}#INV",
        "GSI1SK": queued,
        "GSI2PK": f"CLMINV#{investigation.claim_id}",
        "GSI2SK": queued,
        "entity_type": "INVESTIGATION",
        "schema_version": SCHEMA_VERSION,
        **attrs,
    }
    # Only a cacheable result joins the fingerprint index, so failures are never reused.
    if investigation.status in CACHEABLE_STATUSES:
        if investigation.finished_at is None:
            raise ValueError("a cacheable result needs finished_at")
        item["GSI3PK"] = f"FP#{investigation.fingerprint}"
        item["GSI3SK"] = attrs["finished_at"]
    return item


def investigation_step_item(step: InvestigationStep) -> dict[str, Any]:
    return {
        **investigation_step_key(step.investigation_id, step.seq),
        "entity_type": "INVESTIGATION_STEP",
        "schema_version": SCHEMA_VERSION,
        **_attrs(step),
    }


def mention_item(claim: Claim, mentioned_source_id: str) -> dict[str, Any]:
    return {
        "PK": f"SRCMENT#{mentioned_source_id}",
        "SK": f"CLM#{claim.id}",
        "entity_type": "MENTION",
        "schema_version": SCHEMA_VERSION,
        "incident_id": claim.incident_id,
        "claim_id": claim.id,
        "subject_id": claim.subject_id,
        "source_id": mentioned_source_id,
    }


def name_token_item(subject: Subject, token: str) -> dict[str, Any]:
    return {
        "PK": f"NTOK#{subject.incident_id}",
        "SK": f"{token}#{subject.id}",
        "entity_type": "NAME_TOKEN",
        "schema_version": SCHEMA_VERSION,
        "incident_id": subject.incident_id,
        "subject_id": subject.id,
        "token": token,
    }


def _error_code(err: ClientError) -> str:
    return err.response.get("Error", {}).get("Code", "")


class DynamoFoundRepository:
    """Implements `FoundRepository` on a boto3 DynamoDB Table resource."""

    def __init__(self, table: Any) -> None:
        self._table = table
        self._client = table.meta.client

    def incident_exists(self, incident_id: str) -> bool:
        resp = self._table.get_item(Key=incident_key(incident_id), ProjectionExpression="PK")
        return "Item" in resp

    def get_incident(self, incident_id: str) -> Incident | None:
        item = self._get(incident_key(incident_id))
        if item is None:
            return None
        fields = {k: v for k, v in _fields(item).items() if k != "incident_id"}
        fields.setdefault("id", incident_id)
        fields.setdefault("name", incident_id)
        return Incident.model_validate(fields)

    def put_incident(self, incident: Incident) -> None:
        self._table.put_item(Item=incident_item(incident))

    def put_organization(self, org: Organization) -> None:
        self._table.put_item(Item=organization_item(org))

    def get_organization(self, incident_id: str, org_id: str) -> Organization | None:
        item = self._get(organization_key(incident_id, org_id))
        return Organization.model_validate(_fields(item)) if item else None

    def get_idempotency(self, org_id: str, external_reference: str) -> IdemMarker | None:
        item = self._get(marker_key(org_id, external_reference))
        return IdemMarker.model_validate(_fields(item)) if item else None

    def get_subject(self, subject_id: str) -> Subject | None:
        item = self._get(subject_key(subject_id))
        return Subject.model_validate(_fields(item)) if item else None

    def get_subjects(self, subject_ids: list[str]) -> list[Subject]:
        wanted = list(dict.fromkeys(subject_ids))
        found: dict[str, Subject] = {}
        for start in range(0, len(wanted), _BATCH_GET_MAX):
            keys = [subject_key(sid) for sid in wanted[start : start + _BATCH_GET_MAX]]
            for item in self._batch_get(keys):
                subject = Subject.model_validate(_fields(item))
                found[subject.id] = subject
        return [found[sid] for sid in wanted if sid in found]

    def list_subjects(
        self,
        incident_id: str,
        subject_type: SubjectType,
        limit: int,
        after: NamePosition | None = None,
    ) -> list[Subject]:
        pk = subject_list_pk(incident_id, subject_type)
        kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(pk),
            "Limit": limit,
        }
        if after is not None:
            kwargs["ExclusiveStartKey"] = {
                **subject_key(after.subject_id),
                "GSI1PK": pk,
                "GSI1SK": subject_list_sk(after.name_norm, after.subject_id),
            }
        subjects: list[Subject] = []
        while len(subjects) < limit:
            resp = self._table.query(**kwargs)
            subjects += [Subject.model_validate(_fields(i)) for i in resp.get("Items", [])]
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
            kwargs["Limit"] = limit - len(subjects)
        return subjects[:limit]

    def find_subject_ids_by_token(self, incident_id: str, prefix: str) -> list[str]:
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"NTOK#{incident_id}")
            & Key("SK").begins_with(prefix),
            ProjectionExpression="subject_id",
        )
        return sorted({i["subject_id"] for i in items})

    def ensure_source(self, source: Source) -> Source:
        try:
            self._table.put_item(
                Item=source_item(source), ConditionExpression="attribute_not_exists(PK)"
            )
            return source
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
        existing = self._get(source_key(source.incident_id, source.id))
        if existing is None:  # pragma: no cover - deleted between calls, only on reset
            raise RuntimeError("source vanished after conditional put")
        return Source.model_validate(_fields(existing))

    def list_sources(self, incident_id: str) -> list[Source]:
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"INC#{incident_id}")
            & Key("SK").begins_with("SRC#")
        )
        return [Source.model_validate(_fields(i)) for i in items]

    def get_source(self, incident_id: str, source_id: str) -> Source | None:
        item = self._get(source_key(incident_id, source_id))
        return Source.model_validate(_fields(item)) if item else None

    def ensure_location(self, location: Location) -> Location:
        if self._put_if_absent(location_item(location)):
            return location
        existing = self._get(location_key(location.incident_id, location.id))
        if existing is None:  # pragma: no cover - deleted between calls, only on reset
            raise RuntimeError("location vanished after conditional put")
        return Location.model_validate(_fields(existing))

    def list_locations(self, incident_id: str) -> list[Location]:
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"INC#{incident_id}")
            & Key("SK").begins_with("LOC#")
        )
        return [Location.model_validate(_fields(i)) for i in items]

    def list_incident_claims(self, incident_id: str) -> list[Claim]:
        items = self._query(
            IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq(f"INC#{incident_id}#CLAIM")
        )
        return [Claim.model_validate(_fields(i)) for i in items]

    def publish_claim_tx(self, plan: PublishPlan) -> Claim:
        claim = plan.claim
        subject = plan.subject
        if plan.create_subject:
            subject_op = {
                "Put": {
                    "TableName": self._table.name,
                    "Item": subject_item(subject),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        else:
            subject_op = {
                "Update": {
                    "TableName": self._table.name,
                    "Key": subject_key(subject.id),
                    "UpdateExpression": "SET claim_seq = :new",
                    "ConditionExpression": "claim_seq = :expected",
                    "ExpressionAttributeValues": {
                        ":new": subject.claim_seq,
                        ":expected": plan.expected_seq,
                    },
                }
            }
        items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table.name,
                    "Item": marker_item(plan.marker),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            subject_op,
            {
                "Put": {
                    "TableName": self._table.name,
                    "Item": claim_item(claim),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            {
                "ConditionCheck": {
                    "TableName": self._table.name,
                    "Key": source_key(claim.incident_id, claim.source_id),
                    "ConditionExpression": "attribute_exists(PK)",
                }
            },
        ]
        items += [
            {"Put": {"TableName": self._table.name, "Item": mention_item(claim, sid)}}
            for sid in claim.mentioned_source_ids
        ]
        items += [
            {"Put": {"TableName": self._table.name, "Item": name_token_item(subject, token)}}
            for token in dict.fromkeys(plan.name_tokens)
        ]
        try:
            self._client.transact_write_items(TransactItems=items)
        except ClientError as err:
            if _error_code(err) != "TransactionCanceledException":
                raise
            self._raise_for_cancellation(err)
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        items = self._query(
            IndexName="GSI3",
            KeyConditionExpression=Key("GSI3PK").eq(f"CLAIM#{claim_id}") & Key("GSI3SK").eq("META"),
        )
        return Claim.model_validate(_fields(items[0])) if items else None

    def list_subject_claims(self, subject_id: str, before_seq: int | None = None) -> list[Claim]:
        upper = 10**10 if before_seq is None else before_seq
        if upper <= 1:
            return []
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"SUBJ#{subject_id}")
            & Key("SK").between("CLM#0000000000", f"CLM#{upper - 1:010d}"),
            ConsistentRead=True,
        )
        return [Claim.model_validate(_fields(i)) for i in items]

    def _get(self, key: dict[str, str]) -> dict[str, Any] | None:
        return self._table.get_item(Key=key, ConsistentRead=True).get("Item")

    def list_subscriptions(self, subject_id: str) -> list[Subscription]:
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"SUBJ#{subject_id}")
            & Key("SK").begins_with("SUB#"),
            ConsistentRead=True,
        )
        return [Subscription.model_validate(_fields(i)) for i in items]

    def put_alert_if_absent(self, alert: Alert) -> bool:
        return self._put_if_absent(alert_item(alert))

    def put_review_item_if_absent(self, item: ReviewItem) -> bool:
        return self._put_if_absent(review_item_item(item))

    def get_subscription(self, subject_id: str, subscription_id: str) -> Subscription | None:
        item = self._get(subscription_key(subject_id, subscription_id))
        return Subscription.model_validate(_fields(item)) if item else None

    def save_subscription(self, subscription: Subscription) -> None:
        self._table.put_item(Item=subscription_item(subscription))

    def list_user_subscriptions(self, user_id: str) -> list[Subscription]:
        items = self._query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_id}")
            & Key("GSI1SK").begins_with("SUB#"),
        )
        return [Subscription.model_validate(_fields(i)) for i in items]

    def list_user_alerts(
        self, user_id: str, limit: int, after: dict[str, str] | None = None
    ) -> tuple[list[Alert], dict[str, str] | None]:
        pk = f"USER#{user_id}"
        kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(pk) & Key("GSI1SK").begins_with("ALR#"),
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if after is not None:
            if set(after) != _ALERT_POSITION_KEYS or after["GSI1PK"] != pk:
                raise ValueError("position does not belong to this user")
            kwargs["ExclusiveStartKey"] = after
        alerts: list[Alert] = []
        while len(alerts) <= limit:
            resp = self._table.query(**kwargs)
            alerts += [Alert.model_validate(_fields(i)) for i in resp.get("Items", [])]
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
            kwargs["Limit"] = limit + 1 - len(alerts)
        if len(alerts) <= limit:
            return alerts, None
        page = alerts[:limit]
        return page, _alert_index_keys(page[-1])

    def put_connection(self, connection: Connection) -> None:
        self._table.put_item(Item=connection_item(connection))

    def get_connection(self, connection_id: str) -> Connection | None:
        item = self._get(connection_key(connection_id))
        return Connection.model_validate(_fields(item)) if item else None

    def delete_connection(self, connection_id: str) -> None:
        self._table.delete_item(Key=connection_key(connection_id))

    def set_connection_incident(self, connection_id: str, incident_id: str) -> bool:
        try:
            self._table.update_item(
                Key=connection_key(connection_id),
                UpdateExpression="SET incident_id = :iid, GSI3PK = :pk, GSI3SK = :sk",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":iid": incident_id,
                    ":pk": f"WSINC#{incident_id}",
                    ":sk": f"CONN#{connection_id}",
                },
            )
            return True
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return False

    def list_incident_connections(self, incident_id: str) -> list[Connection]:
        items = self._query(
            IndexName="GSI3", KeyConditionExpression=Key("GSI3PK").eq(f"WSINC#{incident_id}")
        )
        return [Connection.model_validate(_fields(i)) for i in items]

    def list_user_connections(self, user_id: str) -> list[Connection]:
        items = self._query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_id}")
            & Key("GSI1SK").begins_with("CONN#"),
        )
        return [Connection.model_validate(_fields(i)) for i in items]

    def get_review_item(self, incident_id: str, review_id: str) -> ReviewItem | None:
        item = self._get(review_item_key(incident_id, review_id))
        return ReviewItem.model_validate(_fields(item)) if item else None

    def list_source_claims(
        self, source_id: str, limit: int, subject_id: str | None = None
    ) -> list[Claim]:
        kwargs: dict[str, Any] = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(f"SRC#{source_id}"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if subject_id is not None:
            kwargs["FilterExpression"] = Attr("subject_id").eq(subject_id)
        claims: list[Claim] = []
        while len(claims) < limit:
            resp = self._table.query(**kwargs)
            claims += [Claim.model_validate(_fields(i)) for i in resp.get("Items", [])]
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return claims[:limit]

    def count_tool_call(self, investigation_id: str, cap: int) -> int | None:
        try:
            resp = self._table.update_item(
                Key=investigation_key(investigation_id),
                UpdateExpression="ADD tool_calls :one",
                ConditionExpression=(
                    "attribute_exists(PK) AND #status = :running AND tool_calls < :cap"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":running": str(InvestigationStatus.RUNNING),
                    ":cap": cap,
                },
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return None
        return int(resp["Attributes"]["tool_calls"])

    def latest_source_claim_id(self, source_id: str) -> str | None:
        resp = self._table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"SRC#{source_id}"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return str(items[0]["id"]) if items else None

    def get_settings(self) -> Settings:
        item = self._get(SETTINGS_KEY)
        return Settings.model_validate(_fields(item)) if item else Settings()

    def put_investigation(self, investigation: Investigation) -> None:
        if not self._put_if_absent(investigation_item(investigation)):
            raise ValueError("investigation id already exists")

    def get_investigation(self, investigation_id: str) -> Investigation | None:
        item = self._get(investigation_key(investigation_id))
        return Investigation.model_validate(_fields(item)) if item else None

    def update_investigation_if(
        self,
        investigation_id: str,
        expected_status: InvestigationStatus,
        changes: dict[str, Any],
    ) -> Investigation | None:
        current = self.get_investigation(investigation_id)
        if current is None or current.status != expected_status:
            return None
        updated = Investigation.model_validate({**current.model_dump(), **changes})
        if updated.id != investigation_id:
            raise ValueError("an update cannot change the id")
        new_item = investigation_item(updated)
        # Only the named fields are written, so counters bumped meanwhile are kept.
        fields = [f for f in changes if f != "id"]
        fields += [k for k in ("GSI3PK", "GSI3SK") if k in new_item]
        names: dict[str, str] = {"#status": "status"}
        values: dict[str, Any] = {":expected": str(expected_status)}
        sets: list[str] = []
        removes: list[str] = []
        for n, field in enumerate(dict.fromkeys(fields)):
            names[f"#f{n}"] = field
            if field in new_item:
                values[f":v{n}"] = new_item[field]
                sets.append(f"#f{n} = :v{n}")
            else:
                removes.append(f"#f{n}")
        if not sets and not removes:
            return current
        parts = []
        if sets:
            parts.append("SET " + ", ".join(sets))
        if removes:
            parts.append("REMOVE " + ", ".join(removes))
        try:
            resp = self._table.update_item(
                Key=investigation_key(investigation_id),
                UpdateExpression=" ".join(parts),
                ConditionExpression="attribute_exists(PK) AND #status = :expected",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return None
        return Investigation.model_validate(_fields(resp["Attributes"]))

    def find_cached_investigation(self, fingerprint: str) -> Investigation | None:
        resp = self._table.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("GSI3PK").eq(f"FP#{fingerprint}"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return Investigation.model_validate(_fields(items[0])) if items else None

    def acquire_run_lock(
        self, claim_id: str, investigation_id: str, now: datetime, expires_at: datetime
    ) -> str:
        item = {
            **run_lock_key(claim_id),
            "entity_type": "RUN_LOCK",
            "schema_version": SCHEMA_VERSION,
            "claim_id": claim_id,
            "investigation_id": investigation_id,
            "ttl": int(expires_at.timestamp()),
        }
        for _ in range(_LOCK_ATTEMPTS):
            try:
                # TTL deletion lags, so an expired lock is taken over, not waited for.
                self._table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK) OR #ttl <= :now",
                    ExpressionAttributeNames={"#ttl": "ttl"},
                    ExpressionAttributeValues={":now": int(now.timestamp())},
                )
                return investigation_id
            except ClientError as err:
                if _error_code(err) != "ConditionalCheckFailedException":
                    raise
            held = self._get(run_lock_key(claim_id))
            if held is not None:
                return str(held["investigation_id"])
        raise RuntimeError("run lock changed hands repeatedly")

    def release_run_lock(self, claim_id: str, investigation_id: str) -> None:
        try:
            self._table.delete_item(
                Key=run_lock_key(claim_id),
                ConditionExpression="investigation_id = :inv",
                ExpressionAttributeValues={":inv": investigation_id},
            )
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise

    def list_review_items(
        self,
        incident_id: str,
        status: ReviewStatus,
        limit: int,
        item_type: ReviewItemType | None = None,
        after: dict[str, str] | None = None,
    ) -> tuple[list[ReviewItem], dict[str, str] | None]:
        pk = review_queue_pk(incident_id, status)
        kwargs: dict[str, Any] = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(pk),
            "Limit": limit + 1,
        }
        if item_type is not None:
            kwargs["FilterExpression"] = Attr("item_type").eq(str(item_type))
        if after is not None:
            if set(after) != {"s", "r"}:
                raise ValueError("position does not belong to this listing")
            kwargs["ExclusiveStartKey"] = {
                **review_item_key(incident_id, after["r"]),
                "GSI2PK": pk,
                "GSI2SK": after["s"],
            }
        items: list[ReviewItem] = []
        while len(items) <= limit:
            resp = self._table.query(**kwargs)
            items += [ReviewItem.model_validate(_fields(i)) for i in resp.get("Items", [])]
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        if len(items) <= limit:
            return items, None
        page = items[:limit]
        return page, {"s": review_queue_sk(page[-1]), "r": page[-1].id}

    def resolve_review_item(
        self, incident_id: str, review_id: str, resolved_by: str, note: str | None, at: datetime
    ) -> ReviewItem | None:
        current = self.get_review_item(incident_id, review_id)
        if current is None or current.status != ReviewStatus.OPEN:
            return None
        done = current.model_copy(
            update={
                "status": ReviewStatus.DONE,
                "resolved_by": resolved_by,
                "resolved_at": at,
                "note": note,
            }
        )
        item = review_item_item(done)
        names = {"#status": "status", "#note": "note"}
        values: dict[str, Any] = {
            ":done": str(ReviewStatus.DONE),
            ":open": str(ReviewStatus.OPEN),
            ":by": resolved_by,
            ":at": item["resolved_at"],
            ":pk": item["GSI2PK"],
        }
        expression = "SET #status = :done, resolved_by = :by, resolved_at = :at, GSI2PK = :pk"
        if note is not None:
            values[":note"] = note
            expression += ", #note = :note"
        try:
            self._table.update_item(
                Key=review_item_key(incident_id, review_id),
                UpdateExpression=expression,
                ConditionExpression="attribute_exists(PK) AND #status = :open",
                ExpressionAttributeNames=names if note is not None else {"#status": "status"},
                ExpressionAttributeValues=values,
            )
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return None
        return done

    def get_alert(self, subscription_id: str, claim_id: str) -> Alert | None:
        item = self._get(alert_key(subscription_id, claim_id))
        return Alert.model_validate(_fields(item)) if item else None

    def release_held_alert(
        self, subscription_id: str, claim_id: str, status: DeliveryStatus
    ) -> bool:
        try:
            self._table.update_item(
                Key=alert_key(subscription_id, claim_id),
                UpdateExpression="SET delivery_status = :new",
                ConditionExpression="attribute_exists(PK) AND delivery_status = :held",
                ExpressionAttributeValues={
                    ":new": str(status),
                    ":held": str(DeliveryStatus.HELD),
                },
            )
            return True
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return False

    def put_investigation_step(self, step: InvestigationStep) -> bool:
        return self._put_if_absent(investigation_step_item(step))

    def put_activity(self, activity: Activity) -> None:
        self._table.put_item(Item=activity_item(activity))

    def list_activity(self, incident_id: str, limit: int) -> list[Activity]:
        resp = self._table.query(
            KeyConditionExpression=Key("PK").eq(f"INC#{incident_id}")
            & Key("SK").begins_with("ACT#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [Activity.model_validate(_fields(i)) for i in resp.get("Items", [])]

    def delete_incident_data(self, incident_id: str) -> int:
        """Scan for the incident's items, then delete them with their keyless companions.

        Items without an `incident_id` that still belong to it: subscriptions (in the
        subject partitions), idempotency markers and run locks (found from its claims).
        The demo table is small, so a filtered scan is the simple, complete way.
        """
        keys: dict[tuple[str, str], dict[str, str]] = {}
        subjects: set[str] = set()
        org_of_source: dict[str, str] = {}
        claims: list[tuple[str, str, str]] = []
        kwargs: dict[str, Any] = {"FilterExpression": Attr("incident_id").eq(incident_id)}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                kind = item.get("entity_type")
                if kind == "CONNECTION":
                    continue
                keys[(item["PK"], item["SK"])] = {"PK": item["PK"], "SK": item["SK"]}
                if kind == "SUBJECT":
                    subjects.add(str(item["id"]))
                elif kind == "SOURCE" and item.get("organization_id"):
                    org_of_source[str(item["id"])] = str(item["organization_id"])
                elif kind == "CLAIM":
                    claims.append(
                        (str(item["id"]), str(item["source_id"]), str(item["external_reference"]))
                    )
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        for subject in subjects:
            for item in self._query(
                KeyConditionExpression=Key("PK").eq(f"SUBJ#{subject}"),
                ProjectionExpression="PK, SK",
            ):
                keys[(item["PK"], item["SK"])] = {"PK": item["PK"], "SK": item["SK"]}
        for claim_id, source, reference in claims:
            lock = run_lock_key(claim_id)
            keys[(lock["PK"], lock["SK"])] = lock
            org = org_of_source.get(source)
            if org:
                marker = marker_key(org, reference)
                keys[(marker["PK"], marker["SK"])] = marker
        with self._table.batch_writer() as batch:
            for key in keys.values():
                batch.delete_item(Key=key)
        return len(keys)

    def list_investigation_steps(self, investigation_id: str) -> list[InvestigationStep]:
        items = self._query(
            KeyConditionExpression=Key("PK").eq(f"INV#{investigation_id}")
            & Key("SK").begins_with("STEP#"),
            ConsistentRead=True,
        )
        return [InvestigationStep.model_validate(_fields(i)) for i in items]

    def _put_if_absent(self, item: dict[str, Any]) -> bool:
        try:
            self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
            return True
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return False

    def _batch_get(self, keys: list[dict[str, str]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        request: dict[str, Any] = {self._table.name: {"Keys": keys}}
        for _ in range(_BATCH_GET_ATTEMPTS):
            resp = self._client.batch_get_item(RequestItems=request)
            items += resp.get("Responses", {}).get(self._table.name, [])
            request = resp.get("UnprocessedKeys") or {}
            if not request:
                return items
        raise RuntimeError("batch get left unprocessed keys")

    def _query(self, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            resp = self._table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                return items
            kwargs["ExclusiveStartKey"] = last

    @staticmethod
    def _raise_for_cancellation(err: ClientError) -> None:
        reasons = [r.get("Code") for r in err.response.get("CancellationReasons", [])]

        def failed(index: int) -> bool:
            return index < len(reasons) and reasons[index] == "ConditionalCheckFailed"

        if failed(_TX_MARKER):
            raise IdempotencyConflict() from err
        if failed(_TX_SUBJECT) or failed(_TX_CLAIM):
            raise SequenceConflict() from err
        if failed(_TX_SOURCE):
            raise ValueError("source must exist before publish") from err
        raise err


class DynamoBudgetLedger:
    """Implements `BudgetLedger` with conditional atomic counters on `BUDGET#{period}`."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def _bump(self, period: str, counter: str, cap_attr: str, cap: int) -> bool:
        try:
            self._table.update_item(
                Key=budget_key(period),
                UpdateExpression=(
                    "ADD #counter :one SET #et = :et, #sv = :sv, #period = :period, #cap = :cap"
                ),
                ConditionExpression="attribute_not_exists(#counter) OR #counter < :cap",
                ExpressionAttributeNames={
                    "#counter": counter,
                    "#cap": cap_attr,
                    "#et": "entity_type",
                    "#sv": "schema_version",
                    "#period": "period",
                },
                ExpressionAttributeValues={
                    ":one": 1,
                    ":cap": cap,
                    ":et": "BUDGET",
                    ":sv": SCHEMA_VERSION,
                    ":period": period,
                },
            )
            return True
        except ClientError as err:
            if _error_code(err) != "ConditionalCheckFailedException":
                raise
            return False

    def reserve_run(self, period: str, cap: int) -> bool:
        return self._bump(period, "runs", "run_cap", cap)

    def count_model_call(self, period: str, cap: int) -> bool:
        return self._bump(period, "model_calls", "model_call_cap", cap)

    def add_tokens(self, period: str, input_tokens: int, output_tokens: int) -> None:
        self._table.update_item(
            Key=budget_key(period),
            UpdateExpression="ADD input_tokens :i, output_tokens :o SET #period = :period",
            ExpressionAttributeNames={"#period": "period"},
            ExpressionAttributeValues={":i": input_tokens, ":o": output_tokens, ":period": period},
        )

    def usage(self, period: str) -> BudgetUsage:
        item = self._table.get_item(Key=budget_key(period), ConsistentRead=True).get("Item")
        if not item:
            return BudgetUsage(period)
        return BudgetUsage(
            period=period,
            runs=int(item.get("runs", 0)),
            model_calls=int(item.get("model_calls", 0)),
            input_tokens=int(item.get("input_tokens", 0)),
            output_tokens=int(item.get("output_tokens", 0)),
        )
