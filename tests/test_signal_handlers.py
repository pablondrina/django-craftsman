"""
Tests for Craftsman signal handlers (craftsman.contrib.stockman.handlers).

CR4: Verifies that:
- consume_materials_from_stockman correctly consumes from Stockman
- receive_production_in_stockman correctly receives output
- release_materials_on_cancel releases holds
- All handlers gracefully handle Stockman unavailability
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType

from craftsman.contrib.stockman.handlers import (
    consume_materials_from_stockman,
    receive_production_in_stockman,
    release_materials_on_cancel,
)
from craftsman.exceptions import CraftError
from craftsman.models import Recipe, RecipeItem, WorkOrder, WorkOrderStatus


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Signals Test", slug="signals-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="SIG-001",
        name="Signal Product",
        unit="un",
        base_price_q=1000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def ingredient(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="SIG-ING-001",
        name="Signal Ingredient",
        unit="kg",
        base_price_q=500,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product, ingredient):
    ct = ContentType.objects.get_for_model(product)
    r = Recipe.objects.create(
        code="sig-recipe",
        name="Signal Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Baking"],
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
def work_order(db, recipe):
    return WorkOrder.objects.create(
        recipe=recipe,
        planned_quantity=Decimal("50"),
        status=WorkOrderStatus.IN_PROGRESS,
    )


# ═══════════════════════════════════════════════════════════════════
# consume_materials_from_stockman
# ═══════════════════════════════════════════════════════════════════


class TestConsumeMaterials:
    """Tests for consume_materials_from_stockman handler."""

    def test_skips_when_stockman_unavailable(self, work_order):
        """Handler is a no-op when Stockman is not available."""
        requirements = [
            {"product": MagicMock(), "quantity": Decimal("5"), "position": None},
        ]

        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=False,
        ):
            # Should not raise
            consume_materials_from_stockman(
                sender=WorkOrder,
                work_order=work_order,
                requirements=requirements,
            )

    def test_skips_empty_requirements(self, work_order):
        """Handler is a no-op with empty requirements."""
        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            consume_materials_from_stockman(
                sender=WorkOrder,
                work_order=work_order,
                requirements=[],
            )

    def test_raises_on_insufficient_stock(self, work_order):
        """Raises CraftError when stock is insufficient."""
        mock_product = MagicMock()
        requirements = [
            {"product": mock_product, "quantity": Decimal("100"), "position": None},
        ]

        mock_quant = MagicMock()
        mock_quant.available = Decimal("5")  # Much less than needed

        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            with patch("stockman.stock.get_quant", return_value=mock_quant):
                with pytest.raises(CraftError) as exc:
                    consume_materials_from_stockman(
                        sender=WorkOrder,
                        work_order=work_order,
                        requirements=requirements,
                    )

                assert exc.value.code == "INSUFFICIENT_MATERIALS"

    def test_consumes_successfully(self, work_order):
        """Handler calls stock.issue() for each requirement."""
        mock_product = MagicMock()
        requirements = [
            {"product": mock_product, "quantity": Decimal("5"), "position": None},
        ]

        mock_quant = MagicMock()
        mock_quant.available = Decimal("100")
        mock_issue = MagicMock()

        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            with patch("stockman.stock.get_quant", return_value=mock_quant):
                with patch("stockman.stock.issue", mock_issue):
                    consume_materials_from_stockman(
                        sender=WorkOrder,
                        work_order=work_order,
                        requirements=requirements,
                    )

                    mock_issue.assert_called_once_with(
                        Decimal("5"),
                        mock_quant,
                        reference=work_order,
                        reason=f"Consumo WO-{work_order.code}",
                    )


# ═══════════════════════════════════════════════════════════════════
# receive_production_in_stockman
# ═══════════════════════════════════════════════════════════════════


class TestReceiveProduction:
    """Tests for receive_production_in_stockman handler."""

    def test_skips_when_stockman_unavailable(self, work_order, product):
        """Handler is a no-op when Stockman is not available."""
        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=False,
        ):
            receive_production_in_stockman(
                sender=WorkOrder,
                work_order=work_order,
                actual_quantity=Decimal("48"),
                destination=None,
                user=None,
            )

    def test_receives_successfully(self, work_order):
        """Handler calls stock.receive() with correct args."""
        mock_receive = MagicMock()
        mock_destination = MagicMock()

        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            with patch("stockman.stock.receive", mock_receive):
                receive_production_in_stockman(
                    sender=WorkOrder,
                    work_order=work_order,
                    actual_quantity=Decimal("48"),
                    destination=mock_destination,
                    user=None,
                )

                mock_receive.assert_called_once()
                call_args = mock_receive.call_args
                # stock.receive(actual_quantity, product, position=..., ...)
                assert call_args[0][0] == Decimal("48")
                assert call_args.kwargs["position"] is mock_destination
                assert call_args.kwargs["reference"] is work_order

    def test_stores_error_in_metadata_on_failure(self, work_order):
        """On failure, error is stored in metadata (not raised)."""
        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            with patch(
                "stockman.stock.receive",
                side_effect=Exception("DB Error"),
            ):
                receive_production_in_stockman(
                    sender=WorkOrder,
                    work_order=work_order,
                    actual_quantity=Decimal("48"),
                    destination=None,
                    user=None,
                )

                work_order.refresh_from_db()
                assert "stock_receive_error" in work_order.metadata
                assert "DB Error" in work_order.metadata["stock_receive_error"]["error"]


# ═══════════════════════════════════════════════════════════════════
# release_materials_on_cancel
# ═══════════════════════════════════════════════════════════════════


class TestReleaseMaterials:
    """Tests for release_materials_on_cancel handler."""

    def test_skips_when_stockman_unavailable(self, work_order):
        """Handler is a no-op when Stockman is not available."""
        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=False,
        ):
            release_materials_on_cancel(
                sender=WorkOrder,
                work_order=work_order,
                reason="cancelled",
            )

    def test_releases_holds(self, work_order):
        """Handler calls backend.release() with work_order UUID."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.released = []

        mock_backend = MagicMock()
        mock_backend.release.return_value = mock_result

        with patch(
            "craftsman.contrib.stockman.handlers._stockman_available",
            return_value=True,
        ):
            with patch(
                "craftsman.adapters.get_stock_backend",
                return_value=mock_backend,
            ):
                release_materials_on_cancel(
                    sender=WorkOrder,
                    work_order=work_order,
                    reason="no longer needed",
                )

                mock_backend.release.assert_called_once_with(
                    str(work_order.uuid),
                    reason="no longer needed",
                )
