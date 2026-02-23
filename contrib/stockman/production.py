"""
Production Backend Adapter.

Implements Stockman's ProductionBackend protocol for Craftsman.
This allows Stockman to request production when stock reaches reorder point.

Vocabulary mapping (Stockman → Craftsman):
    request_production()  →  Creates WorkOrder directly
    check_status()        →  WorkOrder.status
    cancel_request()      →  WorkOrder.cancel()
    list_pending()        →  WorkOrder.objects.filter()
"""

import logging
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)

# Singleton instance
_lock = threading.Lock()
_production_backend = None


class CraftsmanProductionBackend:
    """
    Implements ProductionBackend for Stockman to request production.

    This adapter is used when:
    - Stock reaches reorder point and needs replenishment
    - Holds are created with availability_policy='demand_ok' but no stock exists
    - External systems need to trigger production

    Usage (Protocol-compliant):
        from craftsman.adapters.production import get_production_backend
        from stockman.protocols.production import ProductionRequest

        backend = get_production_backend()
        result = backend.request_production(ProductionRequest(
            sku="CROISSANT",
            quantity=Decimal("50"),
            target_date=date(2025, 1, 24),
            priority=ProductionPriority.HIGH,
            metadata={"reorder_id": "RO-001"}
        ))

    Usage (Simplified API):
        backend = get_production_backend()
        result = backend.request_production_simple(
            sku="CROISSANT",
            qty=Decimal("50"),
            needed_by=datetime(2025, 1, 24, 12, 0),
        )
    """

    def request_production(self, request) -> "ProductionResult":
        """
        Request production of a product (Protocol-compliant signature).

        Args:
            request: ProductionRequest dataclass from stockman.protocols.production

        Returns:
            ProductionResult with success status and work order info
        """
        from stockman.protocols.production import ProductionResult, ProductionStatusEnum

        # Extract fields from ProductionRequest
        sku = request.sku
        qty = request.quantity
        target_date = request.target_date
        metadata = dict(request.metadata) if request.metadata else {}

        # Convert target_date to datetime for needed_by
        needed_by = datetime.combine(target_date, datetime.min.time()) if target_date else None

        # Add priority to metadata
        if hasattr(request, 'priority'):
            metadata['priority'] = request.priority.value if hasattr(request.priority, 'value') else str(request.priority)

        # Add reference to metadata
        if request.reference:
            metadata['reference'] = request.reference

        return self._create_work_order(sku, qty, needed_by, metadata)

    def request_production_simple(
        self,
        sku: str,
        qty: Decimal,
        needed_by: datetime | None = None,
        priority: int = 50,
        metadata: dict | None = None,
    ) -> "ProductionResult":
        """
        Request production of a product (Simplified API).

        Args:
            sku: Product SKU to produce
            qty: Quantity to produce
            needed_by: When the product is needed (optional)
            priority: Priority (0-100, higher = more urgent)
            metadata: Additional data (e.g., reorder_id)

        Returns:
            ProductionResult with success status and work order info
        """
        combined_metadata = metadata or {}
        combined_metadata['priority'] = priority

        return self._create_work_order(sku, qty, needed_by, combined_metadata)

    def _create_work_order(
        self,
        sku: str,
        qty: Decimal,
        needed_by: datetime | None,
        metadata: dict | None,
    ) -> "ProductionResult":
        """Internal method to create WorkOrder."""
        from craftsman.models import Recipe, WorkOrder, WorkOrderStatus
        from stockman.protocols.production import ProductionResult, ProductionStatusEnum

        try:
            # Find active recipe for this SKU
            product = self._get_product_by_sku(sku)
            if not product:
                return ProductionResult(
                    success=False,
                    message=f"Product not found for SKU {sku}",
                )

            ct = ContentType.objects.get_for_model(product)

            recipe = Recipe.objects.filter(
                output_type=ct,
                output_id=product.pk,
                is_active=True,
            ).first()

            if not recipe:
                return ProductionResult(
                    success=False,
                    message=f"No active recipe found for SKU {sku}",
                )

            # Calculate scheduled_start based on lead_time
            scheduled_start = None
            if needed_by and recipe.lead_time_days:
                scheduled_start = needed_by - timedelta(days=recipe.lead_time_days)

            # Build created_by string
            created_by = "system:stockman-reorder"

            # Build external_ref from metadata
            external_ref = ""
            if metadata:
                external_ref = metadata.get("reorder_id", "")

            # Create WorkOrder directly (not through Plan)
            wo = WorkOrder.objects.create(
                recipe=recipe,
                planned_quantity=qty,
                status=WorkOrderStatus.PENDING,
                scheduled_start=scheduled_start,
                created_by=created_by,
                external_ref=external_ref,
                destination=recipe.work_center,  # Deliver to work center
                metadata={
                    "source": "stockman-reorder",
                    "requested_at": datetime.now().isoformat(),
                    "needed_by": needed_by.isoformat() if needed_by else None,
                    **(metadata or {}),
                },
            )

            logger.info(
                f"Production requested for SKU {sku}: WorkOrder {wo.code} created",
                extra={
                    "sku": sku,
                    "quantity": float(qty),
                    "work_order": wo.code,
                    "needed_by": needed_by.isoformat() if needed_by else None,
                },
            )

            return ProductionResult(
                success=True,
                work_order_id=str(wo.uuid),
                status=ProductionStatusEnum.SCHEDULED,
                request_id=f"production:{wo.pk}",
            )

        except Exception as e:
            logger.error(f"Failed to request production for SKU {sku}: {e}")
            return ProductionResult(
                success=False,
                message=str(e),
            )

    def check_status(self, request_id: str) -> "ProductionStatus | None":
        """
        Check status of a production request (Protocol-compliant).

        Args:
            request_id: ID of the production request (format: "production:{pk}" or UUID)

        Returns:
            ProductionStatus or None if not found
        """
        from craftsman.models import WorkOrder, WorkOrderStatus
        from stockman.protocols.production import ProductionStatus, ProductionStatusEnum

        try:
            # Parse request_id - can be "production:{pk}" or UUID
            if request_id.startswith("production:"):
                pk = int(request_id.split(":")[1])
                wo = WorkOrder.objects.get(pk=pk)
            else:
                wo = WorkOrder.objects.get(uuid=request_id)

            # Map WorkOrder status to ProductionStatusEnum
            status_map = {
                WorkOrderStatus.PENDING: ProductionStatusEnum.SCHEDULED,
                WorkOrderStatus.IN_PROGRESS: ProductionStatusEnum.IN_PROGRESS,
                WorkOrderStatus.PAUSED: ProductionStatusEnum.IN_PROGRESS,
                WorkOrderStatus.COMPLETED: ProductionStatusEnum.COMPLETED,
                WorkOrderStatus.CANCELLED: ProductionStatusEnum.CANCELLED,
            }

            product = wo.recipe.output_product
            sku = getattr(product, "sku", str(product))

            return ProductionStatus(
                request_id=f"production:{wo.pk}",
                sku=sku,
                quantity=wo.planned_quantity,
                status=status_map.get(wo.status, ProductionStatusEnum.REQUESTED),
                target_date=wo.scheduled_start.date() if wo.scheduled_start else wo.production_date,
                estimated_completion=wo.scheduled_end.date() if wo.scheduled_end else None,
                work_order_id=str(wo.uuid),
            )
        except WorkOrder.DoesNotExist:
            return None

    def cancel_request(self, request_id: str, reason: str = "cancelled") -> "ProductionResult":
        """
        Cancel a production request (Protocol-compliant).

        Args:
            request_id: ID of the production request
            reason: Cancellation reason

        Returns:
            ProductionResult with cancellation status
        """
        from craftsman.models import WorkOrder
        from stockman.protocols.production import ProductionResult, ProductionStatusEnum

        try:
            # Parse request_id
            if request_id.startswith("production:"):
                pk = int(request_id.split(":")[1])
                wo = WorkOrder.objects.get(pk=pk)
            else:
                wo = WorkOrder.objects.get(uuid=request_id)

            wo.cancel(reason=reason)
            logger.info(f"Production request {wo.code} cancelled: {reason}")

            return ProductionResult(
                success=True,
                request_id=request_id,
                status=ProductionStatusEnum.CANCELLED,
                work_order_id=str(wo.uuid),
            )
        except WorkOrder.DoesNotExist:
            logger.warning(f"WorkOrder {request_id} not found for cancellation")
            return ProductionResult(
                success=False,
                message=f"WorkOrder {request_id} not found",
            )
        except Exception as e:
            logger.error(f"Failed to cancel WorkOrder {request_id}: {e}")
            return ProductionResult(
                success=False,
                message=str(e),
            )

    def list_pending(
        self,
        sku: str | None = None,
        target_date: date | None = None,
    ) -> list["ProductionStatus"]:
        """
        List pending production requests (Protocol-compliant).

        Args:
            sku: Filter by SKU (optional)
            target_date: Filter by production date (optional)

        Returns:
            List of ProductionStatus for pending work orders
        """
        from craftsman.models import WorkOrder, WorkOrderStatus
        from stockman.protocols.production import ProductionStatus, ProductionStatusEnum

        qs = WorkOrder.objects.filter(
            status__in=[WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS],
            created_by__startswith="system:stockman",
        )

        if sku:
            product = self._get_product_by_sku(sku)
            if product:
                ct = ContentType.objects.get_for_model(product)
                qs = qs.filter(
                    recipe__output_type=ct,
                    recipe__output_id=product.pk,
                )

        if target_date:
            qs = qs.filter(scheduled_start__date=target_date)

        # Map WorkOrder status to ProductionStatusEnum
        status_map = {
            WorkOrderStatus.PENDING: ProductionStatusEnum.SCHEDULED,
            WorkOrderStatus.IN_PROGRESS: ProductionStatusEnum.IN_PROGRESS,
            WorkOrderStatus.PAUSED: ProductionStatusEnum.IN_PROGRESS,
        }

        results = []
        for wo in qs:
            product = wo.recipe.output_product
            wo_sku = getattr(product, "sku", str(product))

            results.append(ProductionStatus(
                request_id=f"production:{wo.pk}",
                sku=wo_sku,
                quantity=wo.planned_quantity,
                status=status_map.get(wo.status, ProductionStatusEnum.REQUESTED),
                target_date=wo.scheduled_start.date() if wo.scheduled_start else wo.production_date,
                estimated_completion=wo.scheduled_end.date() if wo.scheduled_end else None,
                work_order_id=str(wo.uuid),
            ))

        return results

    def _get_product_by_sku(self, sku: str):
        """Get product by SKU via ProductInfoBackend."""
        try:
            from craftsman.adapters.offerman import get_product_info_backend

            backend = get_product_info_backend()
            return backend.get_product_info(sku)
        except Exception:
            return None


def get_production_backend() -> CraftsmanProductionBackend:
    """
    Get the production backend instance (singleton).

    Usage:
        from craftsman.adapters.production import get_production_backend

        backend = get_production_backend()
        result = backend.request_production(...)
    """
    global _production_backend
    if _production_backend is None:
        with _lock:
            if _production_backend is None:  # double-checked
                _production_backend = CraftsmanProductionBackend()
    return _production_backend


def reset_production_backend():
    """Reset the singleton (useful for testing)."""
    global _production_backend
    _production_backend = None
