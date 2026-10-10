"""Sends a due alert by text or email, at most once (design Sections 5.1 step 6 and 6.4).

An alert is due when it is created PENDING, or when a reviewer releases a held one.
The notifier first moves it from PENDING to SENDING with a conditional write, so of two
deliveries of the same event only one sends. A crash after that leaves the alert in
SENDING for a person to check: a missed text is better than a repeated one.

`DECEASED` alerts are created HELD and only reach here after a reviewer releases them
(product rule 8). The in-app alert exists whatever happens here.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import sleep as default_sleep

from found_core.domain.enums import DeliveryStatus, ReviewItemType, ReviewStatus
from found_core.domain.ids import review_item_id
from found_core.domain.models import Alert, Subscription
from found_core.ports.channels import (
    Channel,
    ChannelDisabled,
    DeliveryRejected,
    DeliveryUnavailable,
)
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository

ATTEMPTS = 3
BACKOFF_SECONDS = 0.5
EMAIL_SUBJECT = "Found: an update about someone you follow"
EMAIL_FOOTER = (
    "\n\nOpen Found to see every report and its source. Reports are kept as they were "
    "received; Found does not decide which one is true."
)


class HeldNotReleased(Exception):
    """A held alert is PENDING but its review item is not closed yet.

    A release frees the alerts first and closes the item second, so this is usually a
    moment of overlap. Raising lets the event be retried once the item is closed.
    """


@dataclass(frozen=True)
class NotifyResult:
    claim_id: str
    subscription_id: str
    status: DeliveryStatus | None = None
    sent: list[str] = field(default_factory=list)
    note: str | None = None
    skipped_reason: str | None = None


class NotifyService:
    def __init__(
        self,
        repo: FoundRepository,
        email: Channel,
        sms: Channel,
        clock: Clock | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._repo = repo
        self._email = email
        self._sms = sms
        self._clock = clock or SystemClock()
        self._sleep = sleep

    def deliver(self, subscription_id: str, claim_id: str) -> NotifyResult:
        def skipped(reason: str) -> NotifyResult:
            return NotifyResult(claim_id, subscription_id, skipped_reason=reason)

        alert = self._repo.get_alert(subscription_id, claim_id)
        if alert is None:
            return skipped("ALERT_NOT_FOUND")
        if alert.delivery_status != DeliveryStatus.PENDING:
            # Held, in-app only, or already taken by another delivery of this event.
            return skipped(f"NOT_PENDING_{alert.delivery_status}")

        if alert.held_reason is not None and not self._released(alert):
            # Defence in depth for product rule 8: never text a held report unreleased.
            raise HeldNotReleased(alert.id)

        subscription = self._repo.get_subscription(alert.subject_id, subscription_id)
        targets = self._targets(subscription)
        if not targets:
            done = self._repo.transition_alert(
                subscription_id,
                claim_id,
                DeliveryStatus.PENDING,
                DeliveryStatus.NOT_REQUIRED,
                note="NO_ACTIVE_CHANNEL",
            )
            return skipped("NO_ACTIVE_CHANNEL" if done else "NOT_PENDING")

        if not self._repo.transition_alert(
            subscription_id, claim_id, DeliveryStatus.PENDING, DeliveryStatus.SENDING
        ):
            return skipped("ALREADY_TAKEN")

        sent: list[str] = []
        notes: list[str] = []
        for channel, to in targets:
            outcome = self._send(channel, to, alert)
            if outcome is None:
                sent.append(channel.name)
            else:
                notes.append(f"{channel.name.upper()}_{outcome}")

        status = DeliveryStatus.SENT if sent else DeliveryStatus.FAILED
        note = ", ".join(notes) or None
        self._repo.transition_alert(
            subscription_id,
            claim_id,
            DeliveryStatus.SENDING,
            status,
            channels=tuple(sent),
            note=note,
            at=self._clock.now(),
        )
        return NotifyResult(claim_id, subscription_id, status=status, sent=sent, note=note)

    def _released(self, alert: Alert) -> bool:
        item = self._repo.get_review_item(
            alert.incident_id, review_item_id(ReviewItemType.HELD_ALERT, alert.claim_id)
        )
        return item is not None and item.status == ReviewStatus.DONE

    def _targets(self, subscription: Subscription | None) -> list[tuple[Channel, str]]:
        if subscription is None or not subscription.active:
            return []
        targets: list[tuple[Channel, str]] = []
        if subscription.channel_sms and subscription.phone_e164:
            targets.append((self._sms, subscription.phone_e164))
        if subscription.channel_email and subscription.email:
            targets.append((self._email, subscription.email))
        return targets

    def _send(self, channel: Channel, to: str, alert: Alert) -> str | None:
        """None when sent, otherwise why not: NOT_ENABLED, REJECTED or UNAVAILABLE."""
        text = alert.message + (EMAIL_FOOTER if channel.name == "email" else "")
        for attempt in range(1, ATTEMPTS + 1):
            try:
                channel.send(to, EMAIL_SUBJECT, text)
                return None
            except ChannelDisabled:
                return "NOT_ENABLED"
            except DeliveryRejected:
                return "REJECTED"
            except DeliveryUnavailable:
                if attempt < ATTEMPTS:
                    self._sleep(BACKOFF_SECONDS * attempt)
        return "UNAVAILABLE"
