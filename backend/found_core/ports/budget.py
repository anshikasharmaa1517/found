"""Monthly spend ledger for model-driven work (design Section 9.8, Limits).

Every increment is atomic and conditional on the cap, so parallel starts cannot overspend.
Nothing is ever refunded: a failed or timed out run still counts.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BudgetUsage:
    period: str
    runs: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class BudgetLedger(Protocol):
    def reserve_run(self, period: str, cap: int) -> bool:
        """Count one run if fewer than `cap` are counted. True if counted."""
        ...

    def count_model_call(self, period: str, cap: int) -> bool:
        """Count one model call if fewer than `cap` are counted. True if counted."""
        ...

    def add_tokens(self, period: str, input_tokens: int, output_tokens: int) -> None: ...

    def usage(self, period: str) -> BudgetUsage: ...
