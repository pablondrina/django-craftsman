"""
Tests for craftsman.analytics.ProductionAnalytics.

CR4: Verifies SQL aggregate-based analytics produce correct results.
"""

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from craftsman.analytics import ProductionAnalytics
from craftsman.models import Recipe, RecipeItem, WorkOrder, WorkOrderStatus

User = get_user_model()


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Analytics Test", slug="analytics-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="ANALYTICS-001",
        name="Test Product",
        unit="un",
        base_price_q=1000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="analytics-recipe",
        name="Analytics Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Shaping", "Baking"],
        duration_minutes=120,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(username="operador", password="test123")


@pytest.fixture
def location(db):
    from craftsman.conf import get_position_model

    PositionModel = get_position_model()
    pos, _ = PositionModel.objects.get_or_create(
        code="forno-1",
        defaults={"name": "Forno 1"},
    )
    return pos


@pytest.fixture
def completed_orders(db, recipe, user, location):
    """Create a set of completed work orders for testing."""
    orders = []
    base_date = timezone.now() - timedelta(days=5)

    for i in range(5):
        planned = Decimal("50")
        actual = Decimal(str(50 - i))  # 50, 49, 48, 47, 46
        scheduled = base_date + timedelta(days=i)

        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=planned,
            actual_quantity=actual,
            status=WorkOrderStatus.COMPLETED,
            assigned_to=user,
            location=location,
            scheduled_start=scheduled,
            started_at=scheduled,
            completed_at=scheduled + timedelta(hours=2),
            metadata={
                "step_log": [
                    {"step": "Mixing", "quantity": float(planned), "timestamp": scheduled.isoformat()},
                    {"step": "Shaping", "quantity": float(actual + 1), "timestamp": (scheduled + timedelta(hours=1)).isoformat()},
                    {"step": "Baking", "quantity": float(actual), "timestamp": (scheduled + timedelta(hours=2)).isoformat()},
                ]
            },
        )
        orders.append(wo)

    return orders


# ═══════════════════════════════════════════════════════════════════
# summary()
# ═══════════════════════════════════════════════════════════════════


class TestSummary:
    """Tests for ProductionAnalytics.summary()."""

    def test_summary_empty(self, db):
        """Summary with no data returns zeros."""
        result = ProductionAnalytics.summary()

        assert result["total_orders"] == 0
        assert result["completed_orders"] == 0
        assert result["pending_orders"] == 0
        assert result["in_progress_orders"] == 0
        assert result["total_planned"] == 0.0
        assert result["total_produced"] == 0.0
        assert result["overall_efficiency"] == 100  # 100% when no data

    def test_summary_with_data(self, completed_orders, recipe):
        """Summary correctly aggregates completed orders."""
        # Also create a pending order
        WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("30"),
            status=WorkOrderStatus.PENDING,
        )

        result = ProductionAnalytics.summary()

        assert result["total_orders"] == 6  # 5 completed + 1 pending
        assert result["completed_orders"] == 5
        assert result["pending_orders"] == 1
        assert result["total_planned"] == 250.0  # 50 * 5
        assert result["total_produced"] == 240.0  # 50+49+48+47+46
        assert result["overall_efficiency"] == 96.0

    def test_summary_date_filter(self, completed_orders):
        """Summary respects date filters."""
        today = date.today()
        result = ProductionAnalytics.summary(
            date_from=today - timedelta(days=2),
            date_to=today + timedelta(days=1),
        )

        # Should only include orders within the date range
        assert result["total_orders"] <= 5

    def test_summary_single_query(self, completed_orders, django_assert_num_queries):
        """Summary should execute in a single query."""
        with django_assert_num_queries(1):
            ProductionAnalytics.summary()


# ═══════════════════════════════════════════════════════════════════
# efficiency_by_user()
# ═══════════════════════════════════════════════════════════════════


class TestEfficiencyByUser:
    """Tests for ProductionAnalytics.efficiency_by_user()."""

    def test_efficiency_basic(self, completed_orders, user):
        """Calculates efficiency correctly."""
        result = ProductionAnalytics.efficiency_by_user(user)

        assert result["user"] == "operador"
        assert result["total_work_orders"] == 5
        # total_planned = 250, total_actual = 240 → efficiency = 96%
        assert result["efficiency_pct"] == 96.0
        assert result["avg_loss_pct"] == 4.0

    def test_efficiency_no_orders(self, user):
        """Efficiency with no orders returns 100%."""
        result = ProductionAnalytics.efficiency_by_user(user)

        assert result["total_work_orders"] == 0
        assert result["efficiency_pct"] == 100.0
        assert result["avg_loss_pct"] == 0

    def test_efficiency_single_query(self, completed_orders, user, django_assert_num_queries):
        """Efficiency should use aggregate (single query)."""
        with django_assert_num_queries(1):
            ProductionAnalytics.efficiency_by_user(user)


# ═══════════════════════════════════════════════════════════════════
# throughput_by_location()
# ═══════════════════════════════════════════════════════════════════


class TestThroughputByLocation:
    """Tests for ProductionAnalytics.throughput_by_location()."""

    def test_throughput_basic(self, completed_orders, location):
        """Calculates throughput correctly."""
        result = ProductionAnalytics.throughput_by_location(location)

        assert result["location"] == str(location)
        assert result["total_orders"] == 5
        assert result["total_quantity"] == 240.0  # sum of actual quantities
        assert result["avg_quantity_per_order"] == 48.0  # 240/5
        assert result["avg_duration_minutes"] == 120.0  # 2 hours each

    def test_throughput_empty(self, location):
        """Throughput with no data returns zeros."""
        result = ProductionAnalytics.throughput_by_location(location)

        assert result["total_orders"] == 0
        assert result["total_quantity"] == 0.0
        assert result["avg_duration_minutes"] == 0


# ═══════════════════════════════════════════════════════════════════
# loss_by_step()
# ═══════════════════════════════════════════════════════════════════


class TestLossByStep:
    """Tests for ProductionAnalytics.loss_by_step()."""

    def test_loss_by_step_basic(self, completed_orders, recipe):
        """Calculates per-step losses correctly."""
        result = ProductionAnalytics.loss_by_step(recipe)

        assert "Mixing" in result
        assert "Shaping" in result
        assert "Baking" in result

        # All 5 orders have step data
        assert result["Mixing"]["sample_size"] == 5
        assert result["Baking"]["sample_size"] == 5

        # Baking step: actual quantities are 50,49,48,47,46
        # Planned: 50 each → avg_planned = 50, avg_actual = 48
        assert result["Baking"]["avg_planned"] == 50.0
        assert result["Baking"]["avg_actual"] == 48.0
        assert result["Baking"]["avg_loss"] == 2.0
        assert result["Baking"]["avg_loss_pct"] == 4.0

    def test_loss_by_step_no_steps(self, db, product):
        """Recipe without steps returns empty dict."""
        ct = ContentType.objects.get_for_model(product)
        recipe = Recipe.objects.create(
            code="no-steps",
            name="No Steps",
            output_type=ct,
            output_id=product.pk,
            output_quantity=Decimal("1"),
            steps=[],
        )
        result = ProductionAnalytics.loss_by_step(recipe)
        assert result == {}

    def test_loss_by_step_no_completed_orders(self, recipe):
        """No completed orders returns zero for all steps."""
        result = ProductionAnalytics.loss_by_step(recipe)

        for step_name in ["Mixing", "Shaping", "Baking"]:
            assert result[step_name]["sample_size"] == 0
            assert result[step_name]["avg_loss"] == 0

    def test_loss_by_step_date_filter(self, completed_orders, recipe):
        """Date filter narrows the analysis window."""
        future = date.today() + timedelta(days=30)
        result = ProductionAnalytics.loss_by_step(
            recipe, date_from=future, date_to=future + timedelta(days=1)
        )

        # No orders in the future → all zeros
        for step_name in ["Mixing", "Shaping", "Baking"]:
            assert result[step_name]["sample_size"] == 0
