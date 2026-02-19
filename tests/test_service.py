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
from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeInput,
    WorkOrder,
    WorkOrderStatus,
)


@pytest.fixture
def product(db):
    """Create a test product."""
    from catalog.models import Category, Product

    category = Category.objects.create(name="Pães", slug="paes")
    return Product.objects.create(
        name="Croissant",
        slug="croissant",
        category=category,
        price=Decimal("5.00"),
        is_batch_produced=True,
    )


@pytest.fixture
def position(db):
    """Create or get a test position."""
    from stockman.models import Position, PositionKind

    position, _ = Position.objects.get_or_create(
        code="vitrine",
        defaults={
            "name": "Vitrine",
            "kind": PositionKind.PHYSICAL,
            "is_saleable": True,
            "is_default": True,
        },
    )
    return position


@pytest.fixture
def recipe(db, product, position):
    """Create a test recipe with production_stages."""
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="croissant-v1",
        name="Croissant Tradicional",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        duration_minutes=180,
        production_stages=["Mixing", "Shaping", "Baking"],
        work_center=position,
    )


@pytest.fixture
def recipe_simple(db, product, position):
    """Create a simple recipe without stages."""
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

    def test_step_via_craft_api_deprecated(self, recipe, position):
        """Test that craft.step() emits deprecation warning."""
        import warnings

        work = craft.create(50, recipe, position)
        craft.start(work)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            work = craft.step(50, work, "Mixing")

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

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

        work_orders = craft.schedule(target_date)

        plan.refresh_from_db()
        assert plan.status == PlanStatus.SCHEDULED
        assert len(work_orders) == 1
        assert work_orders[0].planned_quantity == Decimal("50")
