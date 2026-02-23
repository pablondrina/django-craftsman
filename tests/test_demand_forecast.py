"""
Tests for demand forecasting: get_suggested_quantity() and _get_historical_average().

QC1: Validates the "brain" of production planning — the demand forecast engine
that drives daily planning for a bakery (Friday croissants ≠ Monday croissants).
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType

from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    WorkOrder,
    WorkOrderStatus,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Forecast Test", slug="forecast-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="FORECAST-001",
        name="Croissant Forecast",
        unit="un",
        base_price_q=800,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="forecast-croissant",
        name="Croissant Forecast",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Shaping", "Baking"],
    )


@pytest.fixture
def target_date():
    """A future Friday (consistent weekday for tests)."""
    today = date.today()
    # Find the next Friday
    days_ahead = 4 - today.weekday()  # Friday = 4
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead + 14)  # Two weeks ahead


@pytest.fixture
def plan(db, target_date):
    return Plan.objects.create(date=target_date, status=PlanStatus.DRAFT)


@pytest.fixture
def plan_item(db, plan, recipe):
    return PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("0"))


def _create_historical_wo(recipe, plan_date, actual_quantity):
    """Helper: create a completed WorkOrder with plan linkage on a given date."""
    plan, _ = Plan.objects.get_or_create(
        date=plan_date, defaults={"status": PlanStatus.COMPLETED}
    )
    item, _ = PlanItem.objects.get_or_create(
        plan=plan, recipe=recipe, defaults={"quantity": actual_quantity},
    )
    return WorkOrder.objects.create(
        plan_item=item,
        recipe=recipe,
        planned_quantity=actual_quantity,
        actual_quantity=actual_quantity,
        status=WorkOrderStatus.COMPLETED,
    )


# ═══════════════════════════════════════════════════════════════════
# _get_historical_average
# ═══════════════════════════════════════════════════════════════════


class TestGetHistoricalAverage:
    """Tests for PlanItem._get_historical_average()."""

    def test_no_history_returns_zero(self, plan_item):
        """No completed WorkOrders → average is 0."""
        avg = plan_item._get_historical_average(days=28, same_weekday=False)
        assert avg == Decimal("0")

    def test_simple_average(self, plan_item, recipe, target_date):
        """Average of completed WorkOrders in the date range."""
        # Create 3 historical WOs over the past 3 weeks
        for i in range(1, 4):
            past_date = target_date - timedelta(days=7 * i)
            _create_historical_wo(recipe, past_date, Decimal(str(40 + i * 10)))

        avg = plan_item._get_historical_average(days=28, same_weekday=False)

        # 50, 60, 70 → avg = 60
        assert avg == Decimal("60")

    def test_same_weekday_filter(self, plan_item, recipe, target_date):
        """Only same weekday is considered when same_weekday=True."""
        target_weekday = target_date.isoweekday()

        # Create WOs on same weekday (should be included)
        same_day_date = target_date - timedelta(days=7)
        _create_historical_wo(recipe, same_day_date, Decimal("100"))

        # Create WO on different weekday (should be excluded)
        diff_day_date = target_date - timedelta(days=8)
        assert diff_day_date.isoweekday() != target_weekday
        _create_historical_wo(recipe, diff_day_date, Decimal("200"))

        avg_same = plan_item._get_historical_average(days=28, same_weekday=True)
        avg_all = plan_item._get_historical_average(days=28, same_weekday=False)

        # Same weekday only → avg = 100
        assert avg_same == Decimal("100")
        # All days → avg = 150
        assert avg_all == Decimal("150")

    def test_excludes_future_dates(self, plan_item, recipe, target_date):
        """WorkOrders on or after target_date are excluded."""
        _create_historical_wo(recipe, target_date, Decimal("999"))

        avg = plan_item._get_historical_average(days=28, same_weekday=False)
        assert avg == Decimal("0")

    def test_excludes_dates_beyond_window(self, plan_item, recipe, target_date):
        """WorkOrders older than the window are excluded."""
        old_date = target_date - timedelta(days=60)
        _create_historical_wo(recipe, old_date, Decimal("500"))

        avg = plan_item._get_historical_average(days=28, same_weekday=False)
        assert avg == Decimal("0")

    def test_only_completed_orders(self, plan_item, recipe, target_date):
        """Pending/in-progress/cancelled WorkOrders are excluded."""
        past_date = target_date - timedelta(days=7)
        plan_obj, _ = Plan.objects.get_or_create(
            date=past_date, defaults={"status": PlanStatus.COMPLETED}
        )
        item = PlanItem.objects.create(
            plan=plan_obj, recipe=recipe, quantity=Decimal("50"),
        )

        # Pending WO (no actual_quantity)
        WorkOrder.objects.create(
            plan_item=item,
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.PENDING,
        )

        avg = plan_item._get_historical_average(days=28, same_weekday=False)
        assert avg == Decimal("0")


# ═══════════════════════════════════════════════════════════════════
# get_suggested_quantity
# ═══════════════════════════════════════════════════════════════════


class TestGetSuggestedQuantity:
    """Tests for PlanItem.get_suggested_quantity()."""

    def test_no_history_no_demand(self, plan_item):
        """No history + no demand backend → returns 0."""
        result = plan_item.get_suggested_quantity()
        assert result == Decimal("0")

    def test_with_history_only(self, plan_item, recipe, target_date):
        """Historical average * (1 + safety_stock)."""
        # Historical avg = 100
        for i in range(1, 4):
            past_date = target_date - timedelta(days=7 * i)
            _create_historical_wo(recipe, past_date, Decimal("100"))

        with patch("craftsman.conf.get_setting") as mock_setting:
            mock_setting.side_effect = lambda name, default=None: {
                "SAFETY_STOCK_PERCENT": Decimal("0.20"),
                "HISTORICAL_DAYS": 28,
                "SAME_WEEKDAY_ONLY": False,
            }.get(name, default)

            with patch("craftsman.conf.get_demand_backend", return_value=None):
                result = plan_item.get_suggested_quantity()

        # 100 * 1.20 = 120.00
        assert result == Decimal("120.00")

    def test_with_demand_backend(self, plan_item, recipe, target_date):
        """Historical avg + committed demand, both with safety stock."""
        for i in range(1, 4):
            past_date = target_date - timedelta(days=7 * i)
            _create_historical_wo(recipe, past_date, Decimal("80"))

        mock_backend = MagicMock()
        mock_backend.committed.return_value = Decimal("30")

        with patch("craftsman.conf.get_setting") as mock_setting:
            mock_setting.side_effect = lambda name, default=None: {
                "SAFETY_STOCK_PERCENT": Decimal("0.10"),
                "HISTORICAL_DAYS": 28,
                "SAME_WEEKDAY_ONLY": False,
            }.get(name, default)

            with patch("craftsman.conf.get_demand_backend", return_value=mock_backend):
                result = plan_item.get_suggested_quantity()

        # (80 + 30) * 1.10 = 121.00
        assert result == Decimal("121.00")

    def test_safety_stock_zero(self, plan_item, recipe, target_date):
        """Safety stock = 0% → no markup."""
        _create_historical_wo(
            recipe, target_date - timedelta(days=7), Decimal("50")
        )

        with patch("craftsman.conf.get_setting") as mock_setting:
            mock_setting.side_effect = lambda name, default=None: {
                "SAFETY_STOCK_PERCENT": Decimal("0"),
                "HISTORICAL_DAYS": 28,
                "SAME_WEEKDAY_ONLY": False,
            }.get(name, default)

            with patch("craftsman.conf.get_demand_backend", return_value=None):
                result = plan_item.get_suggested_quantity()

        assert result == Decimal("50.00")

    def test_product_none_returns_zero(self, db, plan):
        """Recipe with deleted product returns 0."""
        ct = ContentType.objects.get_for_model(plan)  # dummy CT
        recipe = Recipe.objects.create(
            code="orphan-forecast",
            name="Orphan",
            output_type=ct,
            output_id=99999,  # non-existent
            output_quantity=Decimal("10"),
        )
        item = PlanItem.objects.create(
            plan=plan, recipe=recipe, quantity=Decimal("0"),
        )

        result = item.get_suggested_quantity()
        assert result == Decimal("0")

    def test_graceful_on_error(self, plan_item):
        """Returns 0 on unexpected errors (doesn't crash)."""
        with patch.object(
            type(plan_item.recipe), "output_product",
            new_callable=lambda: property(lambda self: (_ for _ in ()).throw(TypeError("boom"))),
        ):
            result = plan_item.get_suggested_quantity()

        assert result == Decimal("0")
