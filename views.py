"""
Craftsman Views.

Business logic moved to craftsman.services.ingredients.
This module re-exports for backwards compatibility.
"""

from craftsman.services.ingredients import (  # noqa: F401
    IngredientTotal,
    calculate_daily_ingredients,
)

__all__ = ["IngredientTotal", "calculate_daily_ingredients"]
