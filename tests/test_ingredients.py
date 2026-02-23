"""
Tests for craftsman.services.ingredients (calculate_daily_ingredients).

CR3: Verifies the French coefficient ingredient calculation method.
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from craftsman.models import (
    IngredientCategory,
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeItem,
)
from craftsman.services.ingredients import IngredientTotal, calculate_daily_ingredients


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Ingredients Test", slug="ingredients-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="ING-PRODUCT-001",
        name="Croissant",
        unit="un",
        base_price_q=800,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def farinha(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="FARINHA",
        name="Farinha de Trigo",
        unit="kg",
        base_price_q=500,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def manteiga(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="MANTEIGA",
        name="Manteiga",
        unit="kg",
        base_price_q=3000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def cat_massa(db):
    return IngredientCategory.objects.create(
        code="massa",
        name="Massa",
        sort_order=1,
    )


@pytest.fixture
def cat_gordura(db):
    return IngredientCategory.objects.create(
        code="gordura",
        name="Gordura",
        sort_order=2,
    )


@pytest.fixture
def recipe(db, product, farinha, manteiga, cat_massa, cat_gordura):
    ct = ContentType.objects.get_for_model(product)
    r = Recipe.objects.create(
        code="croissant-ing-test",
        name="Croissant Test",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Shaping", "Baking"],
    )

    far_ct = ContentType.objects.get_for_model(farinha)
    RecipeItem.objects.create(
        recipe=r,
        item_type=far_ct,
        item_id=farinha.pk,
        quantity=Decimal("1.000"),
        unit="kg",
        category=cat_massa,
    )

    man_ct = ContentType.objects.get_for_model(manteiga)
    RecipeItem.objects.create(
        recipe=r,
        item_type=man_ct,
        item_id=manteiga.pk,
        quantity=Decimal("0.500"),
        unit="kg",
        category=cat_gordura,
    )

    return r


@pytest.fixture
def target_date():
    return date.today() + timedelta(days=14)


@pytest.fixture
def plan_with_items(db, target_date, recipe):
    plan = Plan.objects.create(date=target_date, status=PlanStatus.DRAFT)
    PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("100"))
    return plan


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════


class TestCalculateDailyIngredients:
    """Tests for calculate_daily_ingredients()."""

    def test_empty_date(self, db):
        """No plan items returns empty dict."""
        result = calculate_daily_ingredients(date(2099, 1, 1))
        assert result == {}

    def test_returns_grouped_by_category(self, plan_with_items, target_date):
        """Ingredients are grouped by category."""
        result = calculate_daily_ingredients(target_date)

        assert "Massa" in result
        assert "Gordura" in result

    def test_ingredient_total_structure(self, plan_with_items, target_date):
        """Each entry is an IngredientTotal with correct fields."""
        result = calculate_daily_ingredients(target_date)

        for category_items in result.values():
            for item in category_items:
                assert isinstance(item, IngredientTotal)
                assert item.item_name
                assert item.unit
                assert item.total_quantity > 0

    def test_zero_quantity_skipped(self, db, target_date, recipe):
        """Plan items with quantity=0 are skipped."""
        plan = Plan.objects.create(
            date=target_date + timedelta(days=1),
            status=PlanStatus.DRAFT,
        )
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("0"))

        result = calculate_daily_ingredients(target_date + timedelta(days=1))
        assert result == {}

    def test_category_sort_order(self, plan_with_items, target_date):
        """Categories are returned in sort_order."""
        result = calculate_daily_ingredients(target_date)

        categories = list(result.keys())
        assert categories.index("Massa") < categories.index("Gordura")

    def test_used_in_tracks_recipes(self, plan_with_items, target_date):
        """used_in field tracks which recipes use the ingredient."""
        result = calculate_daily_ingredients(target_date)

        for category_items in result.values():
            for item in category_items:
                assert "Croissant Test" in item.used_in


class TestBackwardsCompatibility:
    """Verify views.py re-exports work."""

    def test_import_from_views(self):
        """Can still import from craftsman.views."""
        from craftsman.views import IngredientTotal as IT
        from craftsman.views import calculate_daily_ingredients as cdi

        assert IT is IngredientTotal
        assert cdi is calculate_daily_ingredients
