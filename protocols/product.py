"""
Product Info Protocol — Interface for catalog/product information.

Craftsman defines this protocol, Offerman (or other catalog systems) implements it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProductInfo:
    """Product information from catalog."""

    sku: str
    name: str
    description: str | None
    category: str | None
    unit: str
    base_price_q: int | None
    is_active: bool


@dataclass(frozen=True)
class SkuValidationResult:
    """SKU validation result."""

    valid: bool
    sku: str
    product_name: str | None = None
    is_active: bool = True
    error_code: str | None = None
    message: str | None = None


@runtime_checkable
class ProductInfoBackend(Protocol):
    """
    Protocol for product information.

    Implementations should provide methods to:
    - Get product information
    - Validate if SKU can be used as production output
    """

    def get_product_info(self, sku: str) -> ProductInfo | None:
        """
        Get product information.

        Args:
            sku: Product code

        Returns:
            ProductInfo or None if not found
        """
        ...

    def validate_output_sku(self, sku: str) -> SkuValidationResult:
        """
        Validate if SKU can be used as production output.

        Args:
            sku: Product code

        Returns:
            SkuValidationResult
        """
        ...
