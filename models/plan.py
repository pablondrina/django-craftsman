"""
Plan and PlanItem models.

Plan = MPS (Master Production Schedule) - daily production plan.
PlanItem = Individual item in the plan (1 product).
"""

import logging
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Avg, Count, Sum
from django.db.models.functions import ExtractIsoWeekDay
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from craftsman.conf import get_position_model_string

logger = logging.getLogger(__name__)


class PlanStatus(models.TextChoices):
    """Plan lifecycle status."""

    DRAFT = "draft", _("Rascunho")
    APPROVED = "approved", _("Aprovado")
    SCHEDULED = "scheduled", _("Agendado")
    COMPLETED = "completed", _("Concluído")


class Plan(models.Model):
    """
    Plano diário de produção (MPS - Master Production Schedule).

    Status: DRAFT → APPROVED → SCHEDULED → COMPLETED
    """

    # UUID for external references
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )

    date = models.DateField(
        unique=True,
        verbose_name=_("Data de Produção"),
        help_text=_("Data em que a produção acontecerá"),
    )

    status = models.CharField(
        max_length=20,
        choices=PlanStatus.choices,
        default=PlanStatus.DRAFT,
        verbose_name=_("Status"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Observações"),
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("criado em"))
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("aprovado em"))
    scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name=_("agendado em"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("concluído em"))

    # History
    history = HistoricalRecords()

    class Meta:
        db_table = "craftsman_plan"
        verbose_name = _("Planejamento")
        verbose_name_plural = _("Planejamentos")
        ordering = ["-date"]

    def __str__(self) -> str:
        # Format: 'Plan. SEX 12/12/25'
        weekdays = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
        weekday = weekdays[self.date.weekday()]
        return f"Plan. {weekday} {self.date.strftime('%d/%m/%y')}"

    def approve(self, user=None):
        """Aprova plano."""
        if self.status != PlanStatus.DRAFT:
            raise ValidationError(_("Apenas planos em rascunho podem ser aprovados."))

        self.status = PlanStatus.APPROVED
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_at"])

        logger.info(
            f"Plan {self.date} approved",
            extra={
                "plan_date": str(self.date),
                "user": user.username if user else None,
            },
        )

    def schedule(self, user=None, reserve_inputs=None, start_time=None, location=None):
        """
        Agenda plano (cria WorkOrders).

        Args:
            user: User who scheduled
            reserve_inputs: If True, reserve materials via StockBackend.
                If None, uses CRAFTSMAN['RESERVE_INPUTS'] setting.
            start_time: Override start time for all WorkOrders
            location: Override location for all WorkOrders
        """
        if self.status != PlanStatus.APPROVED:
            raise ValidationError(_("Apenas planos aprovados podem ser agendados."))

        from craftsman.conf import get_setting

        if reserve_inputs is None:
            reserve_inputs = get_setting("RESERVE_INPUTS", False)

        from craftsman.models.work_order import WorkOrder, WorkOrderStatus

        with transaction.atomic():
            work_orders = []

            for item in self.items.select_related("recipe").all():
                if item.quantity <= 0:
                    continue

                # Determine scheduled_start
                if start_time:
                    scheduled_start = datetime.combine(self.date, start_time)
                    if timezone.is_naive(scheduled_start):
                        scheduled_start = timezone.make_aware(scheduled_start)
                else:
                    lead_time = item.recipe.lead_time_days or 0
                    scheduled_start = None
                    if lead_time > 0:
                        start_date = self.date - timedelta(days=lead_time)
                        scheduled_start = datetime.combine(start_date, time(6, 0))

                wo = WorkOrder.objects.create(
                    plan_item=item,
                    recipe=item.recipe,
                    planned_quantity=item.quantity,
                    status=WorkOrderStatus.PENDING,
                    destination=item.destination,
                    location=location or item.recipe.work_center,
                    scheduled_start=scheduled_start,
                    created_by=f"user:{user.username}" if user else "system:scheduler",
                    metadata={
                        "scheduled_by": user.username if user else None,
                        "reservation_mode": "enabled" if reserve_inputs else "disabled",
                    },
                )
                work_orders.append(wo)

            self.status = PlanStatus.SCHEDULED
            self.scheduled_at = timezone.now()
            self.save(update_fields=["status", "scheduled_at"])

        logger.info(
            f"Plan {self.date} scheduled with {len(work_orders)} work orders",
            extra={"plan_date": str(self.date), "work_orders": len(work_orders)},
        )

        return work_orders

    def complete(self, user=None):
        """Marca plano como concluído."""
        if self.status != PlanStatus.SCHEDULED:
            raise ValidationError(_("Apenas planos agendados podem ser concluídos."))

        self.status = PlanStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

        logger.info(f"Plan {self.date} completed")

    @property
    def total_items(self) -> int:
        """Total de itens no plano."""
        return self.items.count()

    @property
    def total_quantity(self) -> Decimal:
        """Quantidade total planejada."""
        return self.items.aggregate(total=Sum("quantity"))["total"] or Decimal("0")


class PlanItem(models.Model):
    """
    Item individual do plano (1 produto por receita).

    Representa a quantidade planejada de um produto para uma data específica.
    """

    # UUID for external references
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Plano"),
    )

    recipe = models.ForeignKey(
        "craftsman.Recipe",
        on_delete=models.PROTECT,
        related_name="plan_items",
        verbose_name=_("Receita"),
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=Decimal("0"),
        verbose_name=_("Aprovado"),
        help_text=_("Quantidade aprovada para produzir"),
    )

    # Destination (where product will be delivered)
    destination = models.ForeignKey(
        get_position_model_string(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plan_items",
        verbose_name=_("Destino"),
        help_text=_("Onde entregar o produto final"),
    )

    priority = models.PositiveSmallIntegerField(
        default=50,
        verbose_name=_("Prioridade"),
        help_text=_("Maior = mais prioritário"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Observações"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("criado em"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("atualizado em"))

    class Meta:
        db_table = "craftsman_plan_item"
        verbose_name = _("Item do Plano")
        verbose_name_plural = _("Itens do Plano")
        ordering = ["-priority", "created_at"]
        unique_together = [["plan", "recipe"]]

    def __str__(self) -> str:
        product_name = (
            str(self.recipe.output_product)
            if self.recipe.output_product
            else self.recipe.name
        )
        return f"{product_name} - {self.quantity}"

    @property
    def product(self):
        """Get output product from recipe."""
        return self.recipe.output_product

    @property
    def product_name(self) -> str:
        """Get product name."""
        product = self.recipe.output_product
        return str(product) if product else self.recipe.name

    @property
    def production_date(self):
        """Get production date from plan."""
        return self.plan.date

    @property
    def work_orders(self):
        """WorkOrders for this item."""
        from craftsman.models.work_order import WorkOrder

        return WorkOrder.objects.filter(plan_item=self)

    @property
    def active_work_order(self):
        """Get active work order (pending or in_progress)."""
        from craftsman.models.work_order import WorkOrderStatus

        return self.work_orders.filter(
            status__in=[WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS]
        ).first()

    @property
    def total_produced(self) -> Decimal:
        """Total produced (sum of completed WorkOrders)."""
        from craftsman.models.work_order import WorkOrderStatus

        result = self.work_orders.filter(status=WorkOrderStatus.COMPLETED).aggregate(
            total=Sum("actual_quantity")
        )
        return result["total"] or Decimal("0")

    @property
    def is_complete(self) -> bool:
        """Check if production is complete (produced >= quantity)."""
        return self.total_produced >= self.quantity

    def get_step_quantity(self, step_name: str) -> Decimal | None:
        """Get quantity for a specific step from active work order."""
        wo = (
            self.active_work_order
            or self.work_orders.filter(status="completed").first()
        )

        if not wo:
            return None

        step_log = wo.metadata.get("step_log", [])

        for entry in reversed(step_log):
            if entry.get("step") == step_name:
                return Decimal(str(entry.get("quantity", 0)))

        return None

    def get_suggested_quantity(self) -> Decimal:
        """
        Calculate suggested quantity based on:
        1. Historical average (production from past N days)
        2. Committed demand (via DemandBackend, if configured)
        3. Safety stock percentage

        Formula: (historical_avg + committed) * (1 + safety%)
        """
        from craftsman.conf import get_demand_backend, get_setting

        try:
            product = self.recipe.output_product
            if not product:
                return Decimal("0")

            safety_percent = get_setting("SAFETY_STOCK_PERCENT", Decimal("0.20"))
            historical_days = get_setting("HISTORICAL_DAYS", 28)
            same_weekday = get_setting("SAME_WEEKDAY_ONLY", True)

            # 1. Calculate historical average
            historical_avg = self._get_historical_average(
                days=historical_days, same_weekday=same_weekday
            )

            # 2. Get committed demand (holds/reservations)
            committed = Decimal("0")
            demand_backend = get_demand_backend()
            if demand_backend:
                committed = demand_backend.committed(product, self.plan.date)

            # 3. Base = historical + committed
            base_quantity = historical_avg + committed

            # 4. Apply safety stock
            suggested = base_quantity * (1 + safety_percent)

            return suggested.quantize(Decimal("0.01"))

        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("get_suggested_quantity failed for PlanItem %s: %s", self.pk, exc)
            return Decimal("0")

    def _get_historical_average(
        self, days: int = 28, same_weekday: bool = True
    ) -> Decimal:
        """
        Calculate historical production average.

        Args:
            days: Number of days to look back
            same_weekday: If True, only consider same weekday (e.g., all Fridays)

        Returns:
            Average actual_quantity from completed WorkOrders
        """
        from datetime import timedelta

        from craftsman.models import WorkOrder, WorkOrderStatus

        target_date = self.plan.date
        start_date = target_date - timedelta(days=days)

        # Base query: completed WorkOrders for this recipe
        qs = WorkOrder.objects.filter(
            recipe=self.recipe,
            status=WorkOrderStatus.COMPLETED,
            actual_quantity__isnull=False,
        )

        # Filter by date range
        if same_weekday:
            # ISO weekday: Mon=1..Sun=7 (matches date.isoweekday())
            target_iso_weekday = target_date.isoweekday()
            qs = qs.annotate(
                plan_iso_weekday=ExtractIsoWeekDay("plan_item__plan__date")
            ).filter(
                plan_item__plan__date__gte=start_date,
                plan_item__plan__date__lt=target_date,
                plan_iso_weekday=target_iso_weekday,
            )
        else:
            qs = qs.filter(
                plan_item__plan__date__gte=start_date,
                plan_item__plan__date__lt=target_date,
            )

        # Calculate average
        result = qs.aggregate(
            avg_qty=Avg("actual_quantity"),
            count=Count("id"),
        )

        avg = result.get("avg_qty")
        if avg is None:
            return Decimal("0")

        return Decimal(str(avg))

    def get_reserved_quantity(self) -> Decimal:
        """Get reserved/committed quantity (via DemandBackend)."""
        from craftsman.conf import get_demand_backend

        try:
            product = self.recipe.output_product
            if not product:
                return Decimal("0")

            demand_backend = get_demand_backend()
            if not demand_backend:
                return Decimal("0")

            return demand_backend.committed(product, self.plan.date)

        except (AttributeError, TypeError) as exc:
            logger.debug("get_reserved_quantity unavailable for PlanItem %s: %s", self.pk, exc)
            return Decimal("0")

    def get_available_quantity(self) -> Decimal:
        """Get available quantity (produced - reserved)."""
        produced = self.total_produced
        reserved = self.get_reserved_quantity()
        return produced - reserved
