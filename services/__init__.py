"""
Craftsman Services.

Business logic that doesn't belong in models:
- ingredients: Ingredient calculation using the French coefficient method
"""

from craftsman.services.ingredients import IngredientTotal, calculate_daily_ingredients

__all__ = [
    "IngredientTotal",
    "calculate_daily_ingredients",
]
