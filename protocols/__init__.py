"""
Craftsman Protocols.

Defines interfaces for external integrations.
"""

from craftsman.protocols.stock import (
    AvailabilityResult,
    ConsumeResult,
    MaterialAdjustment,
    MaterialHold,
    MaterialNeed,
    MaterialStatus,
    MaterialUsed,
    ReceiveResult,
    ReleaseResult,
    ReserveResult,
    StockBackend,
)
from craftsman.protocols.product import (
    ProductInfo,
    ProductInfoBackend,
    SkuValidationResult,
)
from craftsman.protocols.demand import DemandBackend

__all__ = [
    # Stock Protocol
    "StockBackend",
    # Stock Input types
    "MaterialNeed",
    "MaterialUsed",
    # Stock Result types
    "MaterialStatus",
    "AvailabilityResult",
    "MaterialHold",
    "ReserveResult",
    "MaterialAdjustment",
    "ConsumeResult",
    "ReleaseResult",
    "ReceiveResult",
    # Product Protocol
    "ProductInfoBackend",
    "ProductInfo",
    "SkuValidationResult",
    # Demand Protocol
    "DemandBackend",
]
