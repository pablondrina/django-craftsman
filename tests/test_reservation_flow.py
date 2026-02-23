"""
Tests for _schedule_with_reservation() — the material reservation path.

QC3: Validates the critical path when RESERVE_INPUTS is enabled:
availability checks, shortage reporting, hold creation, and rollback.
"""

import pytest
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType

from craftsman.exceptions import CraftError
from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeItem,
    WorkOrder,
    WorkOrderStatus,
)
from craftsman.protocols.stock import (
    AvailabilityResult,
    MaterialHold,
    MaterialNeed,
    MaterialStatus,
    ReserveResult,
)
from craftsman.results import ScheduleResult
from craftsman.service import Craft


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Reservation Test", slug="reservation-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RES-PRODUCT",
        name="Croissant Reserve",
        unit="un",
        base_price_q=800,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def farinha(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RES-FARINHA",
        name="Farinha",
        unit="kg",
        base_price_q=500,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def manteiga(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RES-MANTEIGA",
        name="Manteiga",
        unit="kg",
        base_price_q=3000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product, farinha, manteiga):
    ct = ContentType.objects.get_for_model(product)
    r = Recipe.objects.create(
        code="croissant-reserve",
        name="Croissant Reserve",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Lamination", "Baking"],
    )

    far_ct = ContentType.objects.get_for_model(farinha)
    RecipeItem.objects.create(
        recipe=r,
        item_type=far_ct,
        item_id=farinha.pk,
        quantity=Decimal("1.000"),
        unit="kg",
    )

    man_ct = ContentType.objects.get_for_model(manteiga)
    RecipeItem.objects.create(
        recipe=r,
        item_type=man_ct,
        item_id=manteiga.pk,
        quantity=Decimal("0.500"),
        unit="kg",
    )

    return r


@pytest.fixture
def target_date():
    return date.today() + timedelta(days=14)


@pytest.fixture
def approved_plan(db, target_date, recipe):
    plan = Plan.objects.create(date=target_date, status=PlanStatus.APPROVED)
    PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("100"))
    return plan


def _make_available_result(all_ok=True, shortages=None):
    """Helper: create AvailabilityResult."""
    materials = []
    if shortages:
        for sku, needed, avail in shortages:
            materials.append(MaterialStatus(sku=sku, needed=needed, available=avail))
        return AvailabilityResult(all_available=False, materials=materials)

    return AvailabilityResult(all_available=all_ok, materials=materials)


def _make_reserve_result(success=True, holds=None):
    """Helper: create ReserveResult."""
    return ReserveResult(
        success=success,
        holds=holds or [],
        message=None if success else "Reservation failed",
    )


# ═══════════════════════════════════════════════════════════════════
# Schedule Without Reservation (bypass path)
# ═══════════════════════════════════════════════════════════════════


class TestScheduleBypassReservation:
    """schedule() without reservation (default path)."""

    def test_schedule_without_reservation(self, approved_plan, target_date):
        """When RESERVE_INPUTS=False, schedules without calling stock backend."""
        with patch("craftsman.service.get_setting", return_value=False):
            result = Craft.schedule(target_date)

        assert result.success is True
        assert len(result.work_orders) == 1
        assert result.work_orders[0].status == WorkOrderStatus.PENDING

    def test_skip_reservation_flag(self, approved_plan, target_date):
        """skip_reservation=True bypasses even when setting is True."""
        with patch("craftsman.service.get_setting", return_value=True):
            result = Craft.schedule(target_date, skip_reservation=True)

        assert result.success is True
        assert len(result.work_orders) == 1


# ═══════════════════════════════════════════════════════════════════
# Happy Path: All Materials Available
# ═══════════════════════════════════════════════════════════════════


class TestReservationHappyPath:
    """_schedule_with_reservation() when all materials are available."""

    def test_creates_work_orders_with_holds(self, approved_plan, target_date):
        """WorkOrders created with hold metadata when reservation succeeds."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(
            success=True,
            holds=[
                MaterialHold(sku="RES-FARINHA", quantity=Decimal("10"), hold_id="hold:1"),
                MaterialHold(sku="RES-MANTEIGA", quantity=Decimal("5"), hold_id="hold:2"),
            ],
        )

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                result = Craft.schedule(target_date)

        assert result.success is True
        assert len(result.work_orders) == 1

        wo = result.work_orders[0]
        assert wo.status == WorkOrderStatus.PENDING
        assert "holds" in wo.metadata
        assert len(wo.metadata["holds"]) == 2

    def test_plan_transitions_to_scheduled(self, approved_plan, target_date):
        """Plan status changes to SCHEDULED after successful reservation."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(success=True, holds=[])

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                Craft.schedule(target_date)

        approved_plan.refresh_from_db()
        assert approved_plan.status == PlanStatus.SCHEDULED

    def test_materials_calculated_with_coefficient(self, approved_plan, target_date):
        """Materials list uses French coefficient: qty * (planned / output_qty)."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(success=True, holds=[])

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                Craft.schedule(target_date)

        # Verify available() was called with correct material quantities
        # Recipe: 100 units planned, output_qty=10 → coefficient=10
        # Farinha: 1.000 * 10 = 10.000 kg
        # Manteiga: 0.500 * 10 = 5.000 kg
        available_call = mock_backend.available.call_args[0][0]
        skus = {m.sku: m.quantity for m in available_call}

        assert skus["RES-FARINHA"] == Decimal("10.000")
        assert skus["RES-MANTEIGA"] == Decimal("5.000")


# ═══════════════════════════════════════════════════════════════════
# Shortage Path: Insufficient Materials
# ═══════════════════════════════════════════════════════════════════


class TestReservationShortage:
    """_schedule_with_reservation() when materials are insufficient."""

    def test_returns_shortage_errors(self, approved_plan, target_date):
        """Shortage returns ScheduleResult with errors, no WorkOrders."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(
            shortages=[
                ("RES-FARINHA", Decimal("10"), Decimal("3")),
                ("RES-MANTEIGA", Decimal("5"), Decimal("5")),  # sufficient
            ],
        )

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                result = Craft.schedule(target_date)

        assert result.success is False
        assert result.has_shortages is True
        assert len(result.errors) >= 1

        # Only the insufficient material should be in errors
        farinha_error = next(
            (e for e in result.errors if e.sku == "RES-FARINHA"), None
        )
        assert farinha_error is not None
        assert farinha_error.shortage == Decimal("7")

    def test_plan_stays_approved_on_shortage(self, approved_plan, target_date):
        """Plan stays APPROVED when reservation fails."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(
            shortages=[("RES-FARINHA", Decimal("10"), Decimal("0"))],
        )

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                Craft.schedule(target_date)

        approved_plan.refresh_from_db()
        assert approved_plan.status == PlanStatus.APPROVED

    def test_no_work_orders_on_shortage(self, approved_plan, target_date):
        """No WorkOrders are created when materials are insufficient."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(
            shortages=[("RES-FARINHA", Decimal("10"), Decimal("0"))],
        )

        initial_count = WorkOrder.objects.count()

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                Craft.schedule(target_date)

        assert WorkOrder.objects.count() == initial_count


# ═══════════════════════════════════════════════════════════════════
# Rollback: Reserve Fails After Availability OK
# ═══════════════════════════════════════════════════════════════════


class TestReservationRollback:
    """_schedule_with_reservation() rollback when reserve() fails."""

    def test_rollback_on_reserve_failure(self, approved_plan, target_date):
        """If reserve() fails, transaction rolls back — no WOs created."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(
            success=False,
        )

        initial_count = WorkOrder.objects.count()

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                with pytest.raises(CraftError) as exc:
                    Craft.schedule(target_date)

        assert exc.value.code == "RESERVATION_FAILED"
        assert WorkOrder.objects.count() == initial_count

    def test_plan_unchanged_after_rollback(self, approved_plan, target_date):
        """Plan stays APPROVED after reserve() rollback."""
        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(success=False)

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                with pytest.raises(CraftError):
                    Craft.schedule(target_date)

        approved_plan.refresh_from_db()
        assert approved_plan.status == PlanStatus.APPROVED


# ═══════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestReservationEdgeCases:
    """Edge cases for the reservation flow."""

    def test_zero_quantity_items_skipped(self, db, target_date, recipe):
        """PlanItems with quantity<=0 are skipped."""
        plan = Plan.objects.create(date=target_date, status=PlanStatus.APPROVED)
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("0"))

        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(success=True, holds=[])

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                result = Craft.schedule(target_date)

        assert result.success is True
        assert len(result.work_orders) == 0
        # available() should be called with empty materials list
        mock_backend.available.assert_called_once()

    def test_multiple_plan_items(self, db, target_date, recipe, collection):
        """Multiple PlanItems aggregate materials correctly."""
        from offerman.models import CollectionItem, Product

        # Create second product + recipe
        p2 = Product.objects.create(
            sku="RES-PRODUCT-2",
            name="Baguete Reserve",
            unit="un",
            base_price_q=600,
        )
        CollectionItem.objects.create(collection=collection, product=p2, is_primary=True)

        ct2 = ContentType.objects.get_for_model(p2)
        r2 = Recipe.objects.create(
            code="baguete-reserve",
            name="Baguete Reserve",
            output_type=ct2,
            output_id=p2.pk,
            output_quantity=Decimal("10"),
        )

        # Same farinha ingredient
        from offerman.models import Product as P

        farinha = P.objects.get(sku="RES-FARINHA")
        far_ct = ContentType.objects.get_for_model(farinha)
        RecipeItem.objects.create(
            recipe=r2,
            item_type=far_ct,
            item_id=farinha.pk,
            quantity=Decimal("2.000"),
            unit="kg",
        )

        plan = Plan.objects.create(date=target_date, status=PlanStatus.APPROVED)
        PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("100"))
        PlanItem.objects.create(plan=plan, recipe=r2, quantity=Decimal("50"))

        mock_backend = MagicMock()
        mock_backend.available.return_value = _make_available_result(all_ok=True)
        mock_backend.reserve.return_value = _make_reserve_result(success=True, holds=[])

        with patch("craftsman.service.get_setting", return_value=True):
            with patch("craftsman.adapters.get_stock_backend", return_value=mock_backend):
                result = Craft.schedule(target_date)

        assert result.success is True
        assert len(result.work_orders) == 2

        # Verify aggregated materials:
        # Recipe 1: farinha 1.000 * (100/10) = 10.000, manteiga 0.500 * 10 = 5.000
        # Recipe 2: farinha 2.000 * (50/10) = 10.000
        # Total farinha: 20.000
        available_call = mock_backend.available.call_args[0][0]
        skus = {m.sku: m.quantity for m in available_call}

        assert skus["RES-FARINHA"] == Decimal("20.000")
        assert skus["RES-MANTEIGA"] == Decimal("5.000")


# ═══════════════════════════════════════════════════════════════════
# InputShortage & ScheduleResult
# ═══════════════════════════════════════════════════════════════════


class TestResultTypes:
    """Tests for InputShortage and ScheduleResult dataclasses."""

    def test_input_shortage_property(self):
        """InputShortage.shortage calculates correctly."""
        from craftsman.results import InputShortage

        s = InputShortage(sku="FARINHA", required=Decimal("10"), available=Decimal("3"))
        assert s.shortage == Decimal("7")

    def test_schedule_result_has_shortages(self):
        """has_shortages is True when errors exist."""
        from craftsman.results import InputShortage

        result = ScheduleResult(
            success=False,
            errors=[InputShortage(sku="X", required=Decimal("5"), available=Decimal("1"))],
        )
        assert result.has_shortages is True

    def test_schedule_result_no_shortages(self):
        """has_shortages is False when no errors."""
        result = ScheduleResult(success=True)
        assert result.has_shortages is False
