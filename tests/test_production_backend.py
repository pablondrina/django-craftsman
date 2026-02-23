"""
Tests for CraftsmanProductionBackend (craftsman.contrib.stockman.production).

CR4: Verifies the Stockman integration adapter that allows
Stockman to request production when stock reaches reorder point.
"""

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType

from craftsman.contrib.stockman.production import (
    CraftsmanProductionBackend,
    reset_production_backend,
)
from craftsman.models import Recipe, WorkOrder, WorkOrderStatus


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Prod Backend", slug="prod-backend")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="PB-001",
        name="PB Product",
        unit="un",
        base_price_q=1000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="pb-recipe",
        name="PB Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        lead_time_days=1,
    )


@pytest.fixture
def backend():
    reset_production_backend()
    return CraftsmanProductionBackend()


# ═══════════════════════════════════════════════════════════════════
# request_production_simple
# ═══════════════════════════════════════════════════════════════════


class TestRequestProductionSimple:
    """Tests for simplified production request API."""

    def test_creates_work_order(self, backend, product, recipe):
        """request_production_simple creates a WorkOrder."""
        with patch.object(backend, "_get_product_by_sku", return_value=product):
            result = backend.request_production_simple(
                sku="PB-001",
                qty=Decimal("50"),
                needed_by=datetime(2026, 3, 1, 12, 0),
            )

        assert result.success is True
        assert result.work_order_id is not None

        wo = WorkOrder.objects.get(uuid=result.work_order_id)
        assert wo.planned_quantity == Decimal("50")
        assert wo.status == WorkOrderStatus.PENDING
        assert wo.created_by == "system:stockman-reorder"

    def test_product_not_found(self, backend):
        """Returns failure when product not found."""
        with patch.object(backend, "_get_product_by_sku", return_value=None):
            result = backend.request_production_simple(
                sku="NONEXISTENT",
                qty=Decimal("50"),
            )

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_recipe_not_found(self, backend, product):
        """Returns failure when no active recipe exists."""
        # Product exists but no recipe
        with patch.object(backend, "_get_product_by_sku", return_value=product):
            # Delete all recipes
            Recipe.objects.filter(
                output_type=ContentType.objects.get_for_model(product),
                output_id=product.pk,
            ).delete()

            result = backend.request_production_simple(
                sku="PB-001",
                qty=Decimal("50"),
            )

        assert result.success is False
        assert "recipe" in result.message.lower()


# ═══════════════════════════════════════════════════════════════════
# check_status
# ═══════════════════════════════════════════════════════════════════


class TestCheckStatus:
    """Tests for production status checking."""

    def test_check_status_by_request_id(self, backend, product, recipe):
        """check_status returns correct status for a work order."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.PENDING,
            created_by="system:stockman-reorder",
        )

        result = backend.check_status(f"production:{wo.pk}")

        assert result is not None
        assert result.quantity == Decimal("50")

    def test_check_status_by_uuid(self, backend, recipe):
        """check_status works with UUID."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("30"),
            status=WorkOrderStatus.IN_PROGRESS,
        )

        result = backend.check_status(str(wo.uuid))

        assert result is not None

    def test_check_status_not_found(self, backend):
        """check_status returns None for unknown request."""
        result = backend.check_status("production:99999")

        assert result is None


# ═══════════════════════════════════════════════════════════════════
# cancel_request
# ═══════════════════════════════════════════════════════════════════


class TestCancelRequest:
    """Tests for production cancellation."""

    def test_cancel_pending(self, backend, recipe):
        """cancel_request cancels a pending work order."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.PENDING,
        )

        result = backend.cancel_request(f"production:{wo.pk}", reason="no longer needed")

        assert result.success is True
        wo.refresh_from_db()
        assert wo.status == WorkOrderStatus.CANCELLED

    def test_cancel_not_found(self, backend):
        """cancel_request returns failure for unknown request."""
        result = backend.cancel_request("production:99999", reason="test")

        assert result.success is False


# ═══════════════════════════════════════════════════════════════════
# list_pending
# ═══════════════════════════════════════════════════════════════════


class TestListPending:
    """Tests for listing pending production requests."""

    def test_list_pending_all(self, backend, recipe):
        """list_pending returns stockman-originated pending orders."""
        WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
            status=WorkOrderStatus.PENDING,
            created_by="system:stockman-reorder",
        )
        WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("30"),
            status=WorkOrderStatus.PENDING,
            created_by="user:manual",  # Not from stockman
        )

        result = backend.list_pending()

        assert len(result) == 1
        assert result[0].quantity == Decimal("50")

    def test_list_pending_empty(self, backend):
        """list_pending returns empty list when no pending orders."""
        result = backend.list_pending()

        assert result == []
