"""
Craftsman Views.

Includes the "Insumos do Dia" view for calculating ingredients
using the French coefficient method.

Referência: http://techno.boulangerie.free.fr/
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from craftsman.models import IngredientCategory, PlanItem, RecipeItem


@dataclass
class IngredientTotal:
    """Aggregated ingredient data for a day."""

    item_name: str
    category: str
    total_quantity: Decimal
    unit: str
    coefficient: Decimal
    used_in: list[str]


def calculate_daily_ingredients(target_date: date) -> dict[str, list[IngredientTotal]]:
    """
    Calculate ingredients needed for a specific day using the coefficient method.

    Returns ingredients grouped by category.
    """
    # Get all PlanItems for the date
    plan_items = PlanItem.objects.filter(
        plan__date=target_date,
        quantity__gt=0,
    ).select_related("recipe")

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

        # Get product dough weight (in kg)
        product = recipe.output_product
        dough_weight_kg = Decimal("0.100")  # Default 100g

        if hasattr(product, "dough_weight_grams") and product.dough_weight_grams:
            dough_weight_kg = Decimal(str(product.dough_weight_grams)) / 1000

        # Calculate total dough weight needed
        total_dough = plan_item.quantity * dough_weight_kg

        # Calculate coefficient
        # coef = total_dough / recipe.output_quantity
        if recipe.output_quantity > 0:
            coefficient = total_dough / recipe.output_quantity
        else:
            coefficient = Decimal("1")

        # Get recipe items
        for item in recipe.items.filter(is_active=True):
            item_name = str(item.item) if item.item else f"Item {item.item_id}"
            key = f"{item_name}_{item.unit}"

            # Apply coefficient
            qty_needed = item.quantity * coefficient

            ingredients[key]["quantity"] += qty_needed
            ingredients[key]["unit"] = item.unit
            ingredients[key]["category"] = (
                item.category.name if item.category else "Outros"
            )
            ingredients[key]["coefficient_total"] += coefficient
            if recipe.name not in ingredients[key]["used_in"]:
                ingredients[key]["used_in"].append(recipe.name)

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


@staff_member_required
def daily_ingredients_view(request):
    """
    View to display daily ingredients calculation.
    """
    # Get date from query param or use today
    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()

    # Calculate ingredients
    ingredients_by_category = calculate_daily_ingredients(target_date)

    # Get filter category if any
    filter_category = request.GET.get("category")
    if filter_category and filter_category in ingredients_by_category:
        ingredients_by_category = {
            filter_category: ingredients_by_category[filter_category]
        }

    # Get all categories for filter dropdown
    all_categories = IngredientCategory.objects.filter(is_active=True).order_by(
        "sort_order"
    )

    context = {
        "title": f"Insumos {target_date.strftime('%d/%m/%Y')}",
        "target_date": target_date,
        "ingredients_by_category": ingredients_by_category,
        "all_categories": all_categories,
        "filter_category": filter_category,
    }

    return render(request, "craftsman/daily_ingredients.html", context)
