"""
Ingredient calculation using the French coefficient method.

Given a production plan for a day, calculates the total quantities
of each ingredient needed, grouped by category.

Supports multilevel BOM: if a RecipeItem points to a product that
has its own Recipe, the sub-recipe is expanded recursively.

Referência: http://techno.boulangerie.free.fr/

Usage:
    from craftsman.services import calculate_daily_ingredients

    ingredients = calculate_daily_ingredients(date(2026, 2, 23))
    for category, items in ingredients.items():
        for item in items:
            print(f"{item.item_name}: {item.total_quantity} {item.unit}")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Generator

from craftsman.models import IngredientCategory, PlanItem, Recipe, RecipeItem

logger = logging.getLogger("craftsman")

_MAX_BOM_DEPTH = 5


@dataclass
class IngredientTotal:
    """Aggregated ingredient data for a day."""

    item_name: str
    category: str
    total_quantity: Decimal
    unit: str
    coefficient: Decimal
    used_in: list[str]


def _get_sub_recipe(item: RecipeItem) -> Recipe | None:
    """
    Check if a RecipeItem's item has its own Recipe (multilevel BOM).

    Returns the Recipe whose output_product matches the item's GenericFK,
    or None if it's a terminal ingredient.
    """
    try:
        return Recipe.objects.get(
            output_type_id=item.item_type_id,
            output_id=item.item_id,
            is_active=True,
        )
    except Recipe.DoesNotExist:
        return None


def _expand_recipe_items(
    recipe: Recipe,
    coefficient: Decimal,
    recipe_name: str,
    *,
    depth: int = 0,
) -> Generator[tuple[RecipeItem, Decimal, str], None, None]:
    """
    Expand RecipeItems recursively for multilevel BOMs.

    Yields (item, quantity_needed, recipe_name) tuples for terminal
    ingredients only.  Sub-recipes are expanded inline.

    Args:
        recipe:      The recipe to expand.
        coefficient: Multiplier from the parent context
                     (plan_qty / recipe.output_quantity).
        recipe_name: Human-readable recipe trail for ``used_in``.
        depth:       Current recursion depth (cycle protection).
    """
    if depth >= _MAX_BOM_DEPTH:
        logger.warning(
            "BOM depth limit (%d) reached for recipe %s — possible cycle.",
            _MAX_BOM_DEPTH,
            recipe.code,
        )
        return

    for item in recipe.items.filter(is_active=True):
        sub_recipe = _get_sub_recipe(item)

        if sub_recipe is not None:
            # Sub-recipe: calculate child coefficient and recurse.
            if sub_recipe.output_quantity > 0:
                sub_coef = (item.quantity * coefficient) / sub_recipe.output_quantity
            else:
                sub_coef = coefficient
            yield from _expand_recipe_items(
                sub_recipe,
                sub_coef,
                f"{recipe_name} > {sub_recipe.name}",
                depth=depth + 1,
            )
        else:
            # Terminal ingredient.
            yield item, item.quantity * coefficient, recipe_name


def calculate_daily_ingredients(target_date: date) -> dict[str, list[IngredientTotal]]:
    """
    Calculate ingredients needed for a specific day using the coefficient method.

    Returns ingredients grouped by category.
    """
    plan_items = PlanItem.objects.filter(
        plan__date=target_date,
        quantity__gt=0,
    ).select_related(
        "recipe",
    ).prefetch_related(
        "recipe__items",
        "recipe__items__category",
    )

    # Aggregate ingredients
    ingredients: dict[str, dict] = defaultdict(
        lambda: {
            "quantity": Decimal("0"),
            "unit": "",
            "category": "",
            "used_in": [],
            "coefficient_total": Decimal("0"),
        }
    )

    for plan_item in plan_items:
        recipe = plan_item.recipe
        if not recipe:
            continue

        # Calculate coefficient: how many batches of this recipe?
        if recipe.output_quantity > 0:
            coefficient = plan_item.quantity / recipe.output_quantity
        else:
            coefficient = Decimal("1")

        # Expand items recursively (handles multilevel BOM)
        for item, qty_needed, trail in _expand_recipe_items(
            recipe, coefficient, recipe.name,
        ):
            item_name = str(item.item) if item.item else f"Item {item.item_id}"
            key = f"{item_name}_{item.unit}"

            ingredients[key]["quantity"] += qty_needed
            ingredients[key]["unit"] = item.unit
            ingredients[key]["category"] = (
                item.category.name if item.category else "Outros"
            )
            ingredients[key]["coefficient_total"] += coefficient
            if trail not in ingredients[key]["used_in"]:
                ingredients[key]["used_in"].append(trail)

    # Group by category
    result: dict[str, list[IngredientTotal]] = defaultdict(list)

    for key, data in ingredients.items():
        item_name = key.rsplit("_", 1)[0]
        category = data["category"]

        result[category].append(
            IngredientTotal(
                item_name=item_name,
                category=category,
                total_quantity=data["quantity"].quantize(Decimal("0.001")),
                unit=data["unit"],
                coefficient=data["coefficient_total"],
                used_in=data["used_in"],
            )
        )

    # Sort by category order
    categories = list(
        IngredientCategory.objects.filter(name__in=result.keys())
        .values_list("name", flat=True)
        .order_by("sort_order")
    )

    # Add categories not in DB
    for cat in result.keys():
        if cat not in categories:
            categories.append(cat)

    return {cat: result[cat] for cat in categories if cat in result}
