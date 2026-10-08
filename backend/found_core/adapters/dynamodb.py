"""DynamoDB repository over the single table `found-main` (design Section 8.5).

Publish is one TransactWriteItems call (design Section 9.5). Cancellation reasons are
read per item to tell an idempotency conflict from a sequence conflict.
"""

from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from found_core.domain.enums import SubjectType
from found_core.domain.models import (
    Alert,
    Claim,
    IdemMarker,
    Organization,
    ReviewItem,
    Source,
    Subject,
    Subscription,
)
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

# BatchGetItem accepts at most this many keys per call.
_BATCH_GET_MAX = 100
_BATCH_GET_ATTEMPTS = 5

# Positions of the conditional items in the publish transaction.
_TX_MARKER, _TX_SUBJECT, _TX_CLAIM, _TX_SOURCE = 0, 1, 2, 3


def incident_key(incident_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": "META"}


def organization_key(incident_id: str, org_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"ORG#{org_id}"}


def source_key(incident_id: str, source_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"SRC#{source_id}"}


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


def alert_key(subscription_id: str, claim_id: str) -> dict[str, str]:
    return {"PK": f"SUB#{subscription_id}", "SK": f"ALR#{claim_id}"}


def review_item_key(incident_id: str, review_id: str) -> dict[str, str]:
    return {"PK": f"INC#{incident_id}", "SK": f"REV#{review_id}"}


def marker_key(org_id: str, external_reference: str) -> dict[str, str]:
    return {"PK": f"IDEM#{org_id}#{external_reference}", "SK": "META"}


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


def alert_item(alert: Alert) -> dict[str, Any]:
    attrs = _attrs(alert)
    return {
        **alert_key(alert.subscription_id, alert.claim_id),
        "GSI1PK": f"USER#{alert.user_id}",
        "GSI1SK": f"ALR#{attrs['created_at']}#{alert.id}",
        "GSI3PK": f"ALERT#{alert.id}",
        "GSI3SK": "META",
        "entity_type": "ALERT",
        "schema_version": SCHEMA_VERSION,
        **attrs,
    }


def review_item_item(item: ReviewItem) -> dict[str, Any]:
    attrs = _attrs(item)
    return {
        **review_item_key(item.incident_id, item.id),
        "GSI2PK": f"REVQ#{item.incident_id}#{item.status}",
        "GSI2SK": f"{item.priority}#{attrs['created_at']}#{item.id}",
        "entity_type": "REVIEW_ITEM",
        "schema_version": SCHEMA_VERSION,
        **attrs,
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
