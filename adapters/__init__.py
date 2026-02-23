"""
Craftsman Adapters.

Implementations of protocols for external systems.
Adapters use lazy imports — they only fail if you actually call them
without the required package installed.
"""

from craftsman.adapters.stockman import StockmanBackend, get_stock_backend
from craftsman.adapters.offerman import (
    get_product_info_backend,
    reset_product_info_backend,
)

__all__ = [
    # Stockman adapters
    "StockmanBackend",
    "get_stock_backend",
    # Offerman adapters
    "get_product_info_backend",
    "reset_product_info_backend",
]
