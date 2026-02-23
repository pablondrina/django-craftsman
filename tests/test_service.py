"""
Tests for Craftsman service (craft API) v2.3.
"""

import pytest
from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from craftsman import craft, CraftError
from craftsman.conf import get_position_model
from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeItem,
    WorkOrder,
    WorkOrderStatus,
)


@pytest.fixture
def product(db):
    """Create a test product."""
    from offerman.models import Collection, CollectionItem, Product

    collection = Collection.objects.create(name="Pães", slug="paes")
    p = Product.objects.create(
        sku="SVC-CROISSANT-001",
        name="Croissant",
        unit="un",
        base_price_q=500,
        is_batch_produced=True,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def position(db):
    """Create or get a test position."""
    PositionModel = get_position_model()
    defaults = {"name": "Vitrine"}
    # Add stockman-specific fields if available
    try:
        from stockman.models import PositionKind
        defaults.update({
            "kind": PositionKind.PHYSICAL,
            "is_saleable": True,
            "is_default": True,
        })
    except ImportError:
        pass
    position, _ = PositionModel.objects.get_or_create(
        code="vitrine",
        defaults=defaults,
    )
    return position


@pytest.fixture
def recipe(db, product, position):
    """Create a test recipe with steps."""
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="croissant-v1",
        name="Croissant Tradicional",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        duration_minutes=180,
        steps=["Mixing", "Shaping", "Baking"],
        work_center=position,
    )


@pytest.fixture
def recipe_simple(db, product, position):
    """Create a simple recipe without steps."""
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="croissant-simple",
        name="Croissant Simples",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        duration_minutes=60,
        work_center=position,
    )


class TestCraftCreate:
    """Tests for craft.create() - legacy API."""

    def test_create_basic(self, recipe, position):
        """Test basic WorkOrder creation."""
        wo = craft.create(50, recipe, position)

        assert wo.code.startswith("WO-")
        assert wo.recipe == recipe
        assert wo.planned_quantity == Decimal("50")
        assert wo.status == WorkOrderStatus.PENDING
        assert wo.destination == position
        assert wo.actual_quantity is None

    def test_create_with_schedule(self, recipe, position):
        """Test WorkOrder creation with schedule."""
        scheduled = timezone.make_aware(datetime(2025, 12, 15, 6, 0))

        wo = craft.create(50, recipe, position, scheduled_start=scheduled)

        assert wo.scheduled_start == scheduled
        assert wo.scheduled_end is not None

    def test_create_with_custom_code(self, recipe, position):
        """Test WorkOrder creation with custom code."""
        wo = craft.create(50, recipe, position, code="WO-CUSTOM-001")

        assert wo.code == "WO-CUSTOM-001"

    def test_create_invalid_quantity(self, recipe, position):
        """Test error on invalid quantity."""
        with pytest.raises(CraftError) as exc:
            craft.create(0, recipe, position)

        assert exc.value.code == "INVALID_QUANTITY"

    def test_create_negative_quantity(self, recipe, position):
        """Test error on negative quantity."""
        with pytest.raises(CraftError) as exc:
            craft.create(-10, recipe, position)

        assert exc.value.code == "INVALID_QUANTITY"


class TestCraftStart:
    """Tests for craft.start()."""

    def test_start_basic(self, recipe_simple, position):
        """Test starting a WorkOrder."""
        wo = craft.create(50, recipe_simple, position)

        wo = craft.start(wo)

        assert wo.status == WorkOrderStatus.IN_PROGRESS
        assert wo.started_at is not None

    def test_start_invalid_status(self, recipe_simple, position):
        """Test error when starting non-pending order."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)

        with pytest.raises(CraftError) as exc:
            craft.start(wo)

        assert exc.value.code == "INVALID_STATUS"


class TestWorkOrderStep:
    """Tests for WorkOrder.step() - SIREL method."""

    def test_step_basic(self, recipe, position):
        """Test registering a step using work.step()."""
        work = craft.create(50, recipe, position)
        craft.start(work)

        work.step("Mixing", 50)

        assert "Mixing" in work.completed_steps
        assert len(work.step_log) == 1
        assert work.step_log[0]["step"] == "Mixing"
        assert work.step_log[0]["quantity"] == 50.0

    def test_step_sequence(self, recipe, position):
        """Test registering steps in sequence."""
        work = craft.create(50, recipe, position)
        craft.start(work)

        work.step("Mixing", 50)
        work.step("Shaping", 48)
        work.step("Baking", 45)  # Last step auto-completes

        work.refresh_from_db()

        assert work.completed_steps == ["Mixing", "Shaping", "Baking"]
        assert work.status == WorkOrderStatus.COMPLETED  # Auto-completed

    def test_step_auto_starts(self, recipe, position):
        """Test that step() auto-starts pending order."""
        work = craft.create(50, recipe, position)

        # step() on PENDING should auto-start
        work.step("Mixing", 50)
        work.refresh_from_db()

        assert work.status == WorkOrderStatus.IN_PROGRESS
        assert work.started_at is not None

    def test_step_via_model_directly(self, recipe, position):
        """Test that WorkOrder.step() works directly."""
        work = craft.create(50, recipe, position)
        craft.start(work)

        work.step("Mixing", 50)
        work.refresh_from_db()

        assert "Mixing" in work.completed_steps


class TestCraftComplete:
    """Tests for craft.complete() and WorkOrder.complete()."""

    def test_complete_basic(self, recipe_simple, position):
        """Test completing a WorkOrder."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)

        wo.complete(actual_quantity=48)

        assert wo.status == WorkOrderStatus.COMPLETED
        assert wo.actual_quantity == Decimal("48")
        assert wo.completed_at is not None

    def test_complete_with_loss(self, recipe_simple, position):
        """Test completing with loss calculation."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)
        wo.complete(actual_quantity=45)

        assert wo.loss_quantity == Decimal("5")
        assert wo.loss_percentage == Decimal("10")

    def test_complete_pending_order(self, recipe_simple, position):
        """Test completing a pending order (auto-starts and completes)."""
        wo = craft.create(50, recipe_simple, position)

        # complete() should work even on pending (will auto-start first internally)
        wo.complete(actual_quantity=48)

        assert wo.status == WorkOrderStatus.COMPLETED
        assert wo.actual_quantity == Decimal("48")


class TestCraftPauseResume:
    """Tests for craft.pause() and craft.resume()."""

    def test_pause_and_resume(self, recipe_simple, position):
        """Test pausing and resuming production."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)

        wo = craft.pause(wo, reason="Waiting for ingredients")
        assert wo.status == WorkOrderStatus.PAUSED

        wo = craft.resume(wo)
        assert wo.status == WorkOrderStatus.IN_PROGRESS


class TestCraftCancel:
    """Tests for craft.cancel() and WorkOrder.cancel()."""

    def test_cancel_pending(self, recipe_simple, position):
        """Test cancelling pending order."""
        wo = craft.create(50, recipe_simple, position)

        wo = craft.cancel(wo, reason="Not needed")

        assert wo.status == WorkOrderStatus.CANCELLED
        assert "Not needed" in wo.notes

    def test_cancel_in_progress(self, recipe_simple, position):
        """Test cancelling in-progress order."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)

        wo = craft.cancel(wo, reason="Quality issue")

        assert wo.status == WorkOrderStatus.CANCELLED

    def test_cancel_completed_fails(self, recipe_simple, position):
        """Test error when cancelling completed order."""
        wo = craft.create(50, recipe_simple, position)
        craft.start(wo)
        wo.complete(actual_quantity=48)

        with pytest.raises(ValidationError):
            wo.cancel(reason="Too late")


class TestCraftBatch:
    """Tests for craft.create_batch() - legacy API."""

    def test_create_batch(self, recipe, recipe_simple, position):
        """Test creating batch of WorkOrders."""
        target_date = date(2025, 12, 15)

        wos = craft.create_batch(
            production_date=target_date,
            items=[
                {"recipe": recipe, "quantity": 50, "destination": position},
                {"recipe": recipe_simple, "quantity": 30, "destination": position},
            ],
            start_time=time(6, 0),
        )

        assert len(wos) == 2
        assert wos[0].recipe == recipe
        assert wos[1].recipe == recipe_simple
        assert wos[0].scheduled_start.date() == target_date


class TestCraftQueries:
    """Tests for craft query methods."""

    def test_find_recipe(self, recipe, product):
        """Test finding recipe for product."""
        found = craft.find_recipe(product)

        assert found == recipe

    def test_get_pending(self, recipe_simple, position):
        """Test getting pending orders."""
        wo1 = craft.create(50, recipe_simple, position)
        wo2 = craft.create(30, recipe_simple, position)
        craft.start(wo1)

        pending = craft.get_pending()

        assert len(pending) == 1
        assert pending[0] == wo2


class TestPlanWorkflow:
    """Tests for Plan/PlanItem workflow (v2.3)."""

    def test_plan_item_creation(self, recipe, product, position):
        """Test creating plan items via craft.plan()."""
        target_date = date(2025, 12, 20)

        item = craft.plan(50, product, target_date, position)

        assert item.quantity == Decimal("50")
        assert item.plan.date == target_date
        assert item.plan.status == PlanStatus.DRAFT

    def test_plan_approve_schedule(self, recipe, product, position):
        """Test approving and scheduling a plan."""
        target_date = date(2025, 12, 21)

        item = craft.plan(50, product, target_date, position)
        craft.approve(target_date)

        plan = craft.get_plan(target_date)
        assert plan.status == PlanStatus.APPROVED

        result = craft.schedule(target_date)

        plan.refresh_from_db()
        assert plan.status == PlanStatus.SCHEDULED
        assert result.success
        assert len(result.work_orders) == 1
        assert result.work_orders[0].planned_quantity == Decimal("50")


class TestE2ECompleteWorkflow:
    """
    End-to-end: plan → approve → schedule → start → step(3x) → complete.

    This verifies the full production lifecycle from planning through
    execution to completion, including auto-complete on last step.
    """

    def test_plan_to_complete(self, recipe, product, position):
        """Full lifecycle: plan → approve → schedule → start → step(3x) → complete."""
        target_date = date(2025, 12, 25)

        # 1. Plan
        item = craft.plan(50, product, target_date, position)
        plan = craft.get_plan(target_date)
        assert plan.status == PlanStatus.DRAFT

        # 2. Approve
        craft.approve(target_date)
        plan.refresh_from_db()
        assert plan.status == PlanStatus.APPROVED

        # 3. Schedule (creates WorkOrder)
        result = craft.schedule(target_date)
        assert result.success
        assert len(result.work_orders) == 1
        wo = result.work_orders[0]
        assert wo.status == WorkOrderStatus.PENDING

        # 4. Start
        craft.start(wo)
        wo.refresh_from_db()
        assert wo.status == WorkOrderStatus.IN_PROGRESS
        assert wo.started_at is not None

        # 5. Steps (recipe has ["Mixing", "Shaping", "Baking"])
        wo.step("Mixing", 50)
        wo.refresh_from_db()
        assert "Mixing" in wo.completed_steps
        assert wo.status == WorkOrderStatus.IN_PROGRESS

        wo.step("Shaping", 48)
        wo.refresh_from_db()
        assert "Shaping" in wo.completed_steps
        assert wo.status == WorkOrderStatus.IN_PROGRESS

        # Last step auto-completes
        wo.step("Baking", 45)
        wo.refresh_from_db()
        assert "Baking" in wo.completed_steps
        assert wo.status == WorkOrderStatus.COMPLETED
        assert wo.actual_quantity == Decimal("45")
        assert wo.completed_at is not None

        # Verify loss tracking
        assert wo.loss_quantity == Decimal("5")

    def test_plan_with_nested_recipe(self, product, position):
        """BOM multinível: recipe with sub-recipe expands ingredients recursively."""
        from craftsman.services.ingredients import calculate_daily_ingredients
        from offerman.models import Collection, CollectionItem, Product

        target_date = date(2025, 12, 26)

        # Create ingredient products
        collection = Collection.objects.get_or_create(
            slug="e2e-test", defaults={"name": "E2E Test"}
        )[0]

        farinha = Product.objects.create(
            sku="E2E-FARINHA", name="Farinha", unit="kg", base_price_q=500,
        )
        CollectionItem.objects.create(collection=collection, product=farinha, is_primary=True)

        agua = Product.objects.create(
            sku="E2E-AGUA", name="Água", unit="L", base_price_q=0,
        )
        CollectionItem.objects.create(collection=collection, product=agua, is_primary=True)

        fermento = Product.objects.create(
            sku="E2E-FERMENTO", name="Fermento", unit="kg", base_price_q=2000,
        )
        CollectionItem.objects.create(collection=collection, product=fermento, is_primary=True)

        # Create "Massa Pão Francês" product (intermediate)
        massa = Product.objects.create(
            sku="E2E-MASSA-PAO", name="Massa Pão Francês", unit="kg", base_price_q=0,
        )
        CollectionItem.objects.create(collection=collection, product=massa, is_primary=True)

        ct_product = ContentType.objects.get_for_model(Product)

        # Sub-recipe: Massa Pão Francês
        # Produces 1.96 kg of dough using 1.000 kg flour + 0.680 L water + 0.020 kg yeast
        sub_recipe = Recipe.objects.create(
            code="massa-pao-frances-e2e",
            name="Massa Pão Francês",
            output_type=ct_product,
            output_id=massa.pk,
            output_quantity=Decimal("1.96"),
        )
        RecipeItem.objects.create(
            recipe=sub_recipe,
            item_type=ct_product,
            item_id=farinha.pk,
            quantity=Decimal("1.000"),
            unit="kg",
        )
        RecipeItem.objects.create(
            recipe=sub_recipe,
            item_type=ct_product,
            item_id=agua.pk,
            quantity=Decimal("0.680"),
            unit="L",
        )
        RecipeItem.objects.create(
            recipe=sub_recipe,
            item_type=ct_product,
            item_id=fermento.pk,
            quantity=Decimal("0.020"),
            unit="kg",
        )

        # Parent recipe: Pão Francês
        # Produces 20 pães using 0.100 kg of Massa per pão = 2.000 kg total Massa
        parent_recipe = Recipe.objects.create(
            code="pao-frances-e2e",
            name="Pão Francês",
            output_type=ct_product,
            output_id=product.pk,
            output_quantity=Decimal("20"),
        )
        # RecipeItem pointing to "Massa Pão Francês" (the product, not the recipe)
        RecipeItem.objects.create(
            recipe=parent_recipe,
            item_type=ct_product,
            item_id=massa.pk,
            quantity=Decimal("2.000"),
            unit="kg",
        )

        # Plan: 100 pães
        plan = Plan.objects.create(date=target_date, status=PlanStatus.DRAFT)
        PlanItem.objects.create(plan=plan, recipe=parent_recipe, quantity=Decimal("100"))

        # Calculate ingredients
        result = calculate_daily_ingredients(target_date)

        # Coefficient: 100 / 20 = 5 (5 batches of parent recipe)
        # Massa needed: 2.000 kg * 5 = 10.000 kg
        # Sub-coefficient: 10.000 / 1.96 ≈ 5.102...
        # Farinha: 1.000 * 5.102 ≈ 5.102 kg
        # Água: 0.680 * 5.102 ≈ 3.469 L
        # Fermento: 0.020 * 5.102 ≈ 0.102 kg

        # Collect all ingredients from all categories
        all_ingredients = {}
        for cat_items in result.values():
            for item in cat_items:
                all_ingredients[item.item_name] = item

        # Collect all ingredients by checking name contains
        def _find(substr):
            for name, item in all_ingredients.items():
                if substr in name:
                    return item
            return None

        # Verify "Massa Pão Francês" was expanded (not listed as raw ingredient)
        assert _find("Massa Pão Francês") is None, (
            "Sub-recipe should be expanded, not listed as ingredient"
        )
        assert _find("Farinha") is not None, f"Keys: {list(all_ingredients.keys())}"
        assert _find("Água") is not None
        assert _find("Fermento") is not None

        # Verify approximate quantities (allow small rounding)
        farinha_qty = _find("Farinha").total_quantity
        assert Decimal("5.0") < farinha_qty < Decimal("5.2"), f"Farinha: {farinha_qty}"

        agua_qty = _find("Água").total_quantity
        assert Decimal("3.4") < agua_qty < Decimal("3.6"), f"Água: {agua_qty}"

        fermento_qty = _find("Fermento").total_quantity
        assert Decimal("0.1") < fermento_qty < Decimal("0.11"), f"Fermento: {fermento_qty}"

        # Verify used_in trail shows recursive path
        assert any("Massa Pão Francês" in trail for trail in _find("Farinha").used_in)
