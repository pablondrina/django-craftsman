"""
Noop Demand Backend -- returns zero for all demand queries.

Use this adapter for development or testing when Stockman (or any
other demand source) is not available.

Configuration:
    CRAFTSMAN = {
        "DEMAND_BACKEND": "craftsman.adapters.noop.NoopDemandBackend",
    }
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


class NoopDemandBackend:
    """
    No-operation implementation of the DemandBackend protocol.

    Returns Decimal("0") for every committed-demand query.
    Useful for development environments, standalone Craftsman setups,
    or integration tests that should not depend on a real demand source.
    """

    def committed(self, product, target_date: date) -> Decimal:
        """
        Return zero committed demand.

        Always returns Decimal("0") regardless of product or date,
        effectively telling PlanItem.get_suggested_quantity() that
        there is no pre-committed demand to account for.
        """
        return Decimal("0")
