"""
Execution service -- start, step, complete, pause, resume, cancel.

Extracted from Craft to follow the mixin pattern (like Stockman's
StockQueries, StockMovements, StockHolds, StockPlanning).

All methods are @classmethod so the mixin can be composed into Craft
without instantiation.
"""

import logging
from decimal import Decimal

from django.utils import timezone

from craftsman.exceptions import CraftError
from craftsman.models import WorkOrder, WorkOrderStatus

logger = logging.getLogger(__name__)


class CraftExecution:
    """
    Work order execution operations.

    Thin wrappers over WorkOrder model methods that add
    signal emission and refresh-from-db semantics.
    """

    @classmethod
    def start(cls, work_order: WorkOrder, user=None) -> WorkOrder:
        """
        Inicia produção.

        Delegates to the model via direct status update and
        emits the materials_needed signal.
        """
        if work_order.status != WorkOrderStatus.PENDING:
            raise CraftError(
                "INVALID_STATUS",
                current=work_order.status,
                expected=WorkOrderStatus.PENDING,
            )

        # Start without recording a step
        work_order.status = WorkOrderStatus.IN_PROGRESS
        work_order.started_at = timezone.now()
        work_order.save(update_fields=["status", "started_at", "updated_at"])

        # Emit materials_needed signal
        from craftsman.signals import materials_needed

        requirements = work_order._calculate_requirements()
        materials_needed.send(
            sender=cls, work_order=work_order, requirements=requirements
        )

        logger.info(f"Started WorkOrder {work_order.code}")

        return work_order

    @classmethod
    def complete(
        cls,
        work_order: WorkOrder,
        actual_quantity: Decimal | int | float = None,
        user=None,
    ) -> WorkOrder:
        """
        Completa ordem de produção.

        Delegates to WorkOrder.complete() which handles status
        transition and signal emission.
        """
        work_order.complete(actual_quantity, user)
        work_order.refresh_from_db()
        return work_order

    @classmethod
    def pause(cls, work_order: WorkOrder, reason: str = "", user=None) -> WorkOrder:
        """Pausa produção."""
        work_order.pause(reason, user)
        work_order.refresh_from_db()
        return work_order

    @classmethod
    def resume(cls, work_order: WorkOrder, user=None) -> WorkOrder:
        """Retoma produção pausada."""
        work_order.resume(user)
        work_order.refresh_from_db()
        return work_order

    @classmethod
    def cancel(cls, work_order: WorkOrder, reason: str = "", user=None) -> WorkOrder:
        """Cancela ordem de produção."""
        work_order.cancel(reason, user)
        work_order.refresh_from_db()
        return work_order
