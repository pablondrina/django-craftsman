"""
Craftsman Adapters.

Implementations of protocols for external systems.
"""

from craftsman.adapters.stockman import StockmanBackend, get_stock_backend
from craftsman.adapters.offerman import (
    ResilientProductInfoBackend,
    get_product_info_backend,
    reset_product_info_backend,
)
from craftsman.adapters.production import (
    CraftsmanProductionBackend,
    get_production_backend,
    reset_production_backend,
)

__all__ = [
    # Stockman adapters
    "StockmanBackend",
    "get_stock_backend",
    # Offerman adapters
    "ResilientProductInfoBackend",
    "get_product_info_backend",
    "reset_product_info_backend",
    # Production adapters (for Stockman → Craftsman)
    "CraftsmanProductionBackend",
    "get_production_backend",
    "reset_production_backend",
]
