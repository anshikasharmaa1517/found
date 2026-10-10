"""Delivery channels for alerts (design Section 6.4). SMS and email share one interface."""

from typing import Protocol


class ChannelDisabled(Exception):
    """The channel is switched off here, so nothing was sent."""


class DeliveryRejected(Exception):
    """The provider refused this message for good, for example an unverified address."""


class DeliveryUnavailable(Exception):
    """The provider failed for now; trying again may work."""


class Channel(Protocol):
    name: str

    def send(self, to: str, subject: str, text: str) -> None:
        """Send one message. Raises one of the errors above when it is not sent."""
        ...


class DisabledChannel:
    """Stands in for a channel that is not set up, such as SMS without registration."""

    def __init__(self, name: str) -> None:
        self.name = name

    def send(self, to: str, subject: str, text: str) -> None:
        raise ChannelDisabled(self.name)
