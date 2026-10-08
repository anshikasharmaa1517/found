"""Following people and reading one's alerts (design Sections 2.1 FR-15, FR-16 and 7.4).

A user has at most one subscription per person, so following again changes the channels
instead of creating a second subscription that would double every alert. Unfollowing
keeps the item, because past alerts point to it, but drops the contact details.
"""

from dataclasses import dataclass
from typing import Any

from found_core.domain.auth import FAMILY, Caller
from found_core.domain.commands import FollowCommand
from found_core.domain.cursor import CursorCodec, parse_limit
from found_core.domain.enums import SubjectType
from found_core.domain.errors import BadRequest, Forbidden, NotFound
from found_core.domain.ids import subscription_id
from found_core.domain.models import Alert, Subscription
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read


@dataclass(frozen=True)
class FollowResult:
    subscription: Subscription
    created: bool


@dataclass(frozen=True)
class AlertPage:
    alerts: list[Alert]
    next_cursor: str | None


def _require_family(caller: Caller) -> None:
    if not caller.has(FAMILY):
        raise Forbidden("Only family accounts can follow people.")


class SubscriptionService:
    def __init__(
        self, repo: FoundRepository, cursors: CursorCodec, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._cursors = cursors
        self._clock = clock or SystemClock()

    def follow(self, caller: Caller, person_id: str, body: dict[str, Any]) -> FollowResult:
        _require_family(caller)
        person = self._repo.get_subject(person_id)
        if person is None or person.subject_type != SubjectType.PERSON:
            raise NotFound("Person not found.", person_id=person_id)
        ensure_can_read(self._repo, caller, person.incident_id)
        cmd = FollowCommand.parse(body)

        sub_id = subscription_id(person_id, caller.user_id)
        existing = self._repo.get_subscription(person_id, sub_id)
        subscription = Subscription(
            id=sub_id,
            subject_id=person_id,
            user_id=caller.user_id,
            channel_sms=cmd.channel_sms,
            channel_email=cmd.channel_email,
            phone_e164=cmd.phone_e164,
            email=cmd.email,
            active=True,
            created_at=existing.created_at if existing else self._clock.now(),
        )
        self._repo.save_subscription(subscription)
        return FollowResult(subscription, created=existing is None or not existing.active)

    def unfollow(self, caller: Caller, sub_id: str) -> None:
        _require_family(caller)
        mine = next(
            (s for s in self._repo.list_user_subscriptions(caller.user_id) if s.id == sub_id),
            None,
        )
        # Another user's subscription is reported as missing, not forbidden.
        if mine is None:
            raise NotFound("Subscription not found.", subscription_id=sub_id)
        current = self._repo.get_subscription(mine.subject_id, sub_id) or mine
        if not current.active:
            return
        self._repo.save_subscription(
            current.model_copy(
                update={
                    "active": False,
                    "channel_sms": False,
                    "channel_email": False,
                    "phone_e164": None,
                    "email": None,
                }
            )
        )

    def my_subscriptions(self, caller: Caller) -> list[Subscription]:
        _require_family(caller)
        return [s for s in self._repo.list_user_subscriptions(caller.user_id) if s.active]

    def alert_feed(
        self, caller: Caller, *, limit: str | None = None, cursor: str | None = None
    ) -> AlertPage:
        _require_family(caller)
        page_size = parse_limit(limit)
        scope = f"alerts:{caller.user_id}"
        after = self._cursors.decode(scope, cursor) if cursor else None
        if after is not None and not all(isinstance(v, str) for v in after.values()):
            raise BadRequest("Cursor is invalid.")
        try:
            alerts, position = self._repo.list_user_alerts(caller.user_id, page_size, after)
        except ValueError:
            raise BadRequest("Cursor is invalid.") from None
        next_cursor = self._cursors.encode(scope, position) if position else None
        return AlertPage(alerts=alerts, next_cursor=next_cursor)
