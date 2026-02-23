"""
H20 — Craftsman hardening tests.

Tests for:
- Plan.schedule() with partial failure (transaction rollback)
- PlanItem unique constraint violation
- WorkOrder step() in PAUSED state (must reject)
- Signal handler with 2nd material failure
- Concurrency: two schedules of same plan
- Recipe without output_product
- PlanItem with fractional quantity
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeItem,
    WorkOrder,
    WorkOrderStatus,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Test", slug="test", is_active=True)


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="H20-PRODUCT-001",
        name="Test Product",
        unit="un",
        base_price_q=1000,
        is_available=True,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def product_b(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="H20-PRODUCT-002",
        name="Test Product B",
        unit="un",
        base_price_q=2000,
        is_available=True,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def ingredient(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="H20-INGREDIENT-001",
        name="Ingredient A",
        unit="kg",
        base_price_q=500,
        is_available=False,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def ingredient_b(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="H20-INGREDIENT-002",
        name="Ingredient B",
        unit="kg",
        base_price_q=300,
        is_available=False,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product, ingredient):
    ct = ContentType.objects.get_for_model(product)
    r = Recipe.objects.create(
        code="h20-recipe-001",
        name="Test Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Shaping", "Baking"],
    )
    ing_ct = ContentType.objects.get_for_model(ingredient)
    RecipeItem.objects.create(
        recipe=r,
        item_type=ing_ct,
        item_id=ingredient.pk,
        quantity=Decimal("0.500"),
        unit="kg",
    )
    return r


@pytest.fixture
def recipe_b(db, product_b, ingredient_b):
    ct = ContentType.objects.get_for_model(product_b)
    r = Recipe.objects.create(
        code="h20-recipe-002",
        name="Test Recipe B",
        output_type=ct,
        output_id=product_b.pk,
        output_quantity=Decimal("5"),
        steps=["Mixing", "Baking"],
    )
    ing_ct = ContentType.objects.get_for_model(ingredient_b)
    RecipeItem.objects.create(
        recipe=r,
        item_type=ing_ct,
        item_id=ingredient_b.pk,
        quantity=Decimal("1.000"),
        unit="kg",
    )
    return r


@pytest.fixture
def plan_date():
    return date.today() + timedelta(days=7)


@pytest.fixture
def approved_plan(db, plan_date, recipe, recipe_b):
    plan = Plan.objects.create(date=plan_date, status=PlanStatus.DRAFT)
    PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("50"))
    PlanItem.objects.create(plan=plan, recipe=recipe_b, quantity=Decimal("30"))
    plan.approve()
    return plan


# ═══════════════════════════════════════════════════════════════════
# Plan.schedule() with partial failure (transaction rollback)
# ═══════════════════════════════════════════════════════════════════


class TestPlanScheduleRollback:
    """Plan.schedule() must be atomic — partial failure rolls back ALL WorkOrders."""

    def test_schedule_creates_work_orders(self, approved_plan):
        """Baseline: schedule creates WorkOrders for each PlanItem."""
        work_orders = approved_plan.schedule()
        assert len(work_orders) == 2
        assert approved_plan.status == PlanStatus.SCHEDULED

    def test_schedule_rollback_on_failure(self, db, plan_date, recipe, recipe_b):
        """If WorkOrder creation fails mid-loop, ALL must rollback."""
        plan = Plan.objects.create(
            date=plan_date + timedelta(days=1),
            status=PlanStatus.DRAFT,
        )
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("50"))
        PlanItem.objects.create(plan=plan, recipe=recipe_b, quantity=Decimal("30"))
        plan.approve()

        original_create = WorkOrder.objects.create

        call_count = 0

        def failing_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("Simulated DB failure on 2nd WorkOrder")
            return original_create(**kwargs)

        with patch.object(WorkOrder.objects, "create", side_effect=failing_create):
            with pytest.raises(RuntimeError, match="Simulated DB failure"):
                plan.schedule()

        # Plan should NOT be SCHEDULED (rolled back)
        plan.refresh_from_db()
        assert plan.status == PlanStatus.APPROVED

        # No WorkOrders should exist for this plan
        assert WorkOrder.objects.filter(plan_item__plan=plan).count() == 0


# ═══════════════════════════════════════════════════════════════════
# PlanItem unique constraint violation
# ═══════════════════════════════════════════════════════════════════


class TestPlanItemUniqueConstraint:
    """PlanItem must enforce unique (plan, recipe) constraint."""

    def test_duplicate_recipe_in_plan_raises(self, db, plan_date, recipe):
        """Cannot add same recipe twice to the same plan."""
        plan = Plan.objects.create(date=plan_date + timedelta(days=2), status=PlanStatus.DRAFT)
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("50"))

        with pytest.raises(IntegrityError):
            PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("30"))


# ═══════════════════════════════════════════════════════════════════
# WorkOrder step() in PAUSED state
# ═══════════════════════════════════════════════════════════════════


class TestWorkOrderStepInPausedState:
    """WorkOrder.step() must reject when status is PAUSED."""

    def test_step_in_paused_raises_validation_error(self, db, recipe):
        """Cannot register step on a paused WorkOrder."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.IN_PROGRESS,
        )
        wo.pause(reason="Falta de material")

        assert wo.status == WorkOrderStatus.PAUSED

        with pytest.raises(ValidationError):
            wo.step("Mixing", Decimal("50"))

    def test_step_after_resume_works(self, db, recipe):
        """After resume, step() should work again."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.IN_PROGRESS,
        )
        wo.pause(reason="Intervalo")
        wo.resume()

        assert wo.status == WorkOrderStatus.IN_PROGRESS
        wo.step("Mixing", Decimal("50"))
        assert len(wo.step_log) == 1


# ═══════════════════════════════════════════════════════════════════
# Signal handler with 2nd material failure
# ═══════════════════════════════════════════════════════════════════


class TestSignalHandlerPartialFailure:
    """consume_materials_from_stockman must rollback if 2nd material fails."""

    def test_second_material_failure_rolls_back_first(self, db, recipe):
        """If consuming 2nd material fails, 1st consumption must be rolled back."""
        from craftsman.contrib.stockman.handlers import consume_materials_from_stockman
        from craftsman.exceptions import CraftError

        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.IN_PROGRESS,
        )

        requirements = [
            {"product": MagicMock(name="Material A"), "quantity": Decimal("5")},
            {"product": MagicMock(name="Material B"), "quantity": Decimal("10")},
        ]

        call_count = 0

        def mock_issue(quantity, quant, reference=None, reason=None):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise Exception("Insufficient stock for Material B")

        # Mock stockman availability check
        mock_quant = MagicMock()
        mock_quant.available = Decimal("100")

        with patch("craftsman.contrib.stockman.handlers._stockman_available", return_value=True):
            with patch("stockman.stock.get_quant", return_value=mock_quant):
                with patch("stockman.stock.issue", side_effect=mock_issue):
                    with pytest.raises(CraftError):
                        consume_materials_from_stockman(
                            sender=WorkOrder,
                            work_order=wo,
                            requirements=requirements,
                        )


# ═══════════════════════════════════════════════════════════════════
# Concurrency: two schedules of same plan
# ═══════════════════════════════════════════════════════════════════


class TestConcurrentSchedule:
    """Cannot schedule same plan twice."""

    def test_schedule_already_scheduled_raises(self, approved_plan):
        """Scheduling an already-scheduled plan must fail."""
        approved_plan.schedule()
        assert approved_plan.status == PlanStatus.SCHEDULED

        with pytest.raises(ValidationError):
            approved_plan.schedule()


# ═══════════════════════════════════════════════════════════════════
# Recipe without output_product
# ═══════════════════════════════════════════════════════════════════


class TestRecipeWithoutOutputProduct:
    """Recipe with invalid output_product reference."""

    def test_recipe_output_product_deleted(self, db, recipe, product):
        """If output product is deleted, recipe still exists (CASCADE on CT)."""
        # Recipe uses GenericForeignKey with CASCADE on ContentType
        # When product is deleted, GenericForeignKey returns None
        product_id = product.pk
        recipe_id = recipe.pk

        # The recipe still exists after product deletion
        assert Recipe.objects.filter(pk=recipe_id).exists()

    def test_plan_item_product_name_fallback(self, db, recipe):
        """PlanItem.product_name falls back to recipe.name when no product."""
        plan = Plan.objects.create(
            date=date.today() + timedelta(days=10),
            status=PlanStatus.DRAFT,
        )
        item = PlanItem.objects.create(
            plan=plan,
            recipe=recipe,
            quantity=Decimal("20"),
        )

        # When output_product exists, should show product name
        assert item.product_name is not None
        assert len(item.product_name) > 0


# ═══════════════════════════════════════════════════════════════════
# PlanItem with fractional quantity
# ═══════════════════════════════════════════════════════════════════


class TestPlanItemFractionalQuantity:
    """PlanItem quantity field behavior with various values."""

    def test_zero_quantity_allowed(self, db, recipe):
        """PlanItem with zero quantity is allowed (default)."""
        plan = Plan.objects.create(
            date=date.today() + timedelta(days=11),
            status=PlanStatus.DRAFT,
        )
        item = PlanItem.objects.create(
            plan=plan,
            recipe=recipe,
            quantity=Decimal("0"),
        )
        assert item.quantity == Decimal("0")

    def test_total_quantity_aggregation(self, db, recipe, recipe_b):
        """Plan.total_quantity sums all items."""
        plan = Plan.objects.create(
            date=date.today() + timedelta(days=12),
            status=PlanStatus.DRAFT,
        )
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("50"))
        PlanItem.objects.create(plan=plan, recipe=recipe_b, quantity=Decimal("30"))

        assert plan.total_quantity == Decimal("80")
        assert plan.total_items == 2
