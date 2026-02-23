"""
Stockman Signal Handlers for Craftsman.

Connects Craftsman signals to Stockman for:
- Material consumption on production start
- Product receipt on production completion
- Material release on order cancellation

Registered by CraftsmanStockmanConfig.ready().
"""

import logging

from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from craftsman.exceptions import CraftError
from craftsman.signals import materials_needed, order_cancelled, production_completed

logger = logging.getLogger(__name__)


def _stockman_available() -> bool:
    """Check if Stockman is available."""
    try:
        from stockman.models import Position

        return Position.objects.filter(is_default=True).exists()
    except Exception:
        return False


@receiver(materials_needed)
def consume_materials_from_stockman(sender, work_order, requirements, **kwargs):
    """
    When Craftsman needs materials, consume from Stockman.

    Called when a WorkOrder starts (first step).
    Consumes materials from Stockman based on recipe inputs.
    """
    if not _stockman_available():
        logger.info(
            f"Stockman not available, skipping material consumption for WO-{work_order.code}"
        )
        return

    if not requirements:
        logger.info(f"No material requirements for WO-{work_order.code}")
        return

    try:
        from stockman import StockError, stock

        with transaction.atomic():
            for item in requirements:
                product = item["product"]
                quantity = item["quantity"]
                position = item.get("position")

                quant = stock.get_quant(product, position=position)

                if not quant:
                    quants = stock.list_quants(product=product, include_empty=False)
                    quant = quants.first()

                if not quant or quant.available < quantity:
                    available = quant.available if quant else 0
                    raise CraftError(
                        "INSUFFICIENT_MATERIALS",
                        product=str(product),
                        required=float(quantity),
                        available=float(available),
                    )

                stock.issue(
                    quantity,
                    quant,
                    reference=work_order,
                    reason=f"Consumo WO-{work_order.code}",
                )

                logger.info(
                    f"Consumed {quantity} of {product} for WO-{work_order.code}",
                    extra={
                        "work_order": work_order.code,
                        "product": str(product),
                        "quantity": float(quantity),
                    },
                )

    except CraftError:
        raise
    except Exception as e:
        logger.error(f"Failed to consume materials for WO-{work_order.code}: {e}")
        raise CraftError("MATERIAL_CONSUMPTION_FAILED", error=str(e))


@receiver(production_completed)
def receive_production_in_stockman(
    sender, work_order, actual_quantity, destination, user, **kwargs
):
    """
    When Craftsman completes production, receive in Stockman.

    Called when a WorkOrder is completed.
    Receives the produced quantity at the destination position.
    """
    if not _stockman_available():
        logger.info(
            f"Stockman not available, skipping production receipt for WO-{work_order.code}"
        )
        return

    try:
        from stockman import stock

        product = work_order.recipe.output_product

        stock.receive(
            actual_quantity,
            product,
            position=destination,
            reference=work_order,
            user=user,
            reason=f"Produção WO-{work_order.code}",
        )

        logger.info(
            f"Received {actual_quantity} of {product} from WO-{work_order.code}",
            extra={
                "work_order": work_order.code,
                "product": str(product),
                "quantity": float(actual_quantity),
                "destination": str(destination),
            },
        )

    except Exception as e:
        logger.error(f"Failed to receive production for WO-{work_order.code}: {e}")
        work_order.metadata["stock_receive_error"] = {
            "error": str(e),
            "timestamp": timezone.now().isoformat(),
            "quantity": float(actual_quantity),
        }
        work_order.save(update_fields=["metadata", "updated_at"])


@receiver(order_cancelled)
def release_materials_on_cancel(sender, work_order, reason, **kwargs):
    """
    When WorkOrder is cancelled, release any held materials.

    Called when a WorkOrder is cancelled.
    Releases holds stored in work_order.metadata['holds'].
    """
    if not _stockman_available():
        return

    from craftsman.adapters import get_stock_backend

    backend = get_stock_backend()
    result = backend.release(str(work_order.uuid), reason=reason)

    if result.success:
        logger.info(
            f"Released {len(result.released)} holds for WO-{work_order.code}",
            extra={"work_order": work_order.code, "released": len(result.released)},
        )
    else:
        logger.error(
            f"Failed to release holds for WO-{work_order.code}: {result.message}",
            extra={"work_order": work_order.code},
        )
