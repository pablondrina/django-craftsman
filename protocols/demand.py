"""
Demand Protocol — Interface for committed demand (holds/reservations).

Craftsman defines this protocol. External systems (e.g. Stockman) implement it
to provide committed quantities for production planning.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class DemandBackend(Protocol):
    """
    Protocol for querying committed demand.

    Implementations should provide the total committed (reserved/held)
    quantity for a product on a given date.
    """

    def committed(self, product, target_date: date) -> Decimal:
        """
        Return total committed quantity for a product on a date.

        Args:
            product: The product instance (any model)
            target_date: The target delivery date

        Returns:
            Total committed/reserved quantity
        """
        ...
