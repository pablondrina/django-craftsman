"""
Craftsman Signal Handlers.

Connects Craftsman signals to Stockman for material consumption and product receipt.

This module is imported in apps.py to register handlers.
"""

import logging

from django.dispatch import receiver

from craftsman.signals import materials_needed, production_completed, order_cancelled
from craftsman.exceptions import CraftError

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

    This handler is called when craft.start() is executed.
    It consumes materials from Stockman based on recipe inputs.
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
        from stockman import stock, StockError

        for item in requirements:
            product = item["product"]
            quantity = item["quantity"]
            position = item.get("position")

            # Find quant to consume from
            quant = stock.get_quant(product, position=position)

            if not quant:
                # Try to find any quant for this product
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

            # Issue (consume) the material
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

    This handler is called when craft.complete() is executed.
    It receives the produced quantity at the destination position.
    """
    if not _stockman_available():
        logger.info(
            f"Stockman not available, skipping production receipt for WO-{work_order.code}"
        )
        return

    try:
        from stockman import stock

        product = work_order.recipe.output_product

        # Receive the produced quantity
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
        # Don't raise - production is already completed, just log the error


@receiver(order_cancelled)
def release_materials_on_cancel(sender, work_order, reason, **kwargs):
    """
    When WorkOrder is cancelled, release any held materials.

    This handler is called when craft.cancel() is executed.
    Currently a placeholder - implement when material holds are added.
    """
    logger.info(
        f"WorkOrder {work_order.code} cancelled: {reason}",
        extra={
            "work_order": work_order.code,
            "reason": reason,
        },
    )
    # TODO: Release any material holds when that feature is implemented
