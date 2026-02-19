"""
WorkOrder model.

WorkOrder = Atomic unit of production work with step tracking.

✅ BUSINESS LOGIC ENCAPSULATED IN MODEL (SIREL principle)
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

logger = logging.getLogger(__name__)
User = get_user_model()


class WorkOrderStatus(models.TextChoices):
    """WorkOrder lifecycle status."""

    PENDING = "pending", _("Pendente")
    IN_PROGRESS = "in_progress", _("Em Produção")
    PAUSED = "paused", _("Pausado")
    COMPLETED = "completed", _("Concluído")
    CANCELLED = "cancelled", _("Cancelado")


class WorkOrder(models.Model):
    """
    Ordem de produção com tracking de etapas.

    ✅ LÓGICA DE NEGÓCIO ENCAPSULADA NO MODELO!

    Status: PENDING → IN_PROGRESS → COMPLETED → CANCELLED

    Metadata structure:
        {
            'step_log': [
                {
                    'step': 'Mixing',
                    'quantity': 70.0,
                    'timestamp': '2025-12-11T05:00:00+00:00',
                    'user': 'joao'
                },
                ...
            ],
            'completed_by': 'supervisor'
        }
    """

    # UUID for external references
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )

    # Link to PlanItem (v2.3)
    plan_item = models.ForeignKey(
        "craftsman.PlanItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="work_orders_set",
        verbose_name=_("Item do Plano"),
    )

    # Identification
    code = models.CharField(
        unique=True,
        max_length=50,
        blank=True,
        verbose_name=_("Código"),
        help_text=_("Identificador único (auto-gerado se vazio)"),
    )

    recipe = models.ForeignKey(
        "craftsman.Recipe",
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name=_("Receita"),
    )

    # Quantities
    planned_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        verbose_name=_("Planejado"),
        help_text=_("Quantidade planejada a produzir"),
    )
    actual_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name=_("Quantidade Real"),
        help_text=_("Quantidade efetivamente produzida"),
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=WorkOrderStatus.choices,
        default=WorkOrderStatus.PENDING,
        db_index=True,
        verbose_name=_("Status"),
    )

    # Where product goes (DELIVERY) - kept for backward compatibility
    destination = models.ForeignKey(
        "stockman.Position",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders_delivered",
        verbose_name=_("Destino"),
        help_text=_("Onde entregar o produto final"),
    )

    # Where work happens (EXECUTION)
    location = models.ForeignKey(
        "stockman.Position",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders_executed",
        verbose_name=_("Local de Produção"),
        help_text=_("Onde o trabalho acontece (workstation)"),
    )

    # Scheduling (OPTIONAL) - kept for backward compatibility
    scheduled_start = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Início Agendado"),
    )
    scheduled_end = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fim Agendado"),
    )

    # Execution tracking
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Início Real"),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fim Real"),
    )

    # Assignment (OPTIONAL)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name=_("Responsável"),
    )

    # Source tracking (Hold, Forecast, Manual...) - kept for backward compatibility
    source_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Tipo de Origem"),
    )
    source_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("ID da Origem"),
    )
    source = GenericForeignKey("source_type", "source_id")

    # Step quantities (editable in admin list)
    mixing = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name=_("Massa para"),
        help_text=_("Quantidade de massa preparada"),
    )
    processed_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name=_("Processado"),
        help_text=_("Quantidade após processamento/modelagem"),
    )
    produced_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name=_("Produzido"),
        help_text=_("Quantidade final produzida"),
    )

    # Flexibility
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadados"),
        help_text=_("Dados adicionais: step_log, completed_by, etc."),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Observações"),
    )

    # B.I. / Auditoria
    created_by = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Criado por"),
        help_text=_("Ex: 'user:joao', 'system:scheduler', 'api:pdv-001'"),
    )
    external_ref = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Referência Externa"),
        help_text=_("ID no sistema de origem, quando aplicável"),
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Criado em"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Atualizado em"),
    )

    # History
    history = HistoricalRecords()

    class Meta:
        db_table = "craftsman_work_order"
        verbose_name = _("Ordem de Produção")
        verbose_name_plural = _("Ordens de Produção")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_start"]),
            models.Index(fields=["recipe", "status"]),
            models.Index(fields=["location", "status"]),
            models.Index(fields=["scheduled_start"]),
            models.Index(fields=["plan_item"]),
        ]

    def __str__(self) -> str:
        if self.code:
            return f"{self.code} - {self.recipe.name}"
        return f"WO-{self.pk} - {self.recipe.name}"

    def save(self, *args, **kwargs):
        """Override save to auto-generate code."""
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self) -> str:
        """Generate unique WorkOrder code in format WO-YYYY-NNNNN."""
        year = timezone.now().year
        prefix = f"WO-{year}-"

        last = (
            WorkOrder.objects.filter(code__startswith=prefix).order_by("-code").first()
        )

        if last:
            try:
                last_num = int(last.code.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}{next_num:05d}"

    # ══════════════════════════════════════════════════════════════
    # BUSINESS LOGIC (encapsulated in model!)
    # ══════════════════════════════════════════════════════════════

    def step(self, step_name: str, quantity: Decimal | int | float, user=None):
        """
        Registra etapa de produção.

        ✅ Método principal SIREL - chamado de qualquer lugar:
        - Admin inline edit
        - API REST endpoint
        - Mobile app
        - Celery task

        Args:
            step_name: Nome da etapa (ex: "Mixing", "Shaping", "Baking")
            quantity: Quantidade produzida nesta etapa
            user: Usuário que registrou (opcional)

        Behavior:
            - Inicia WorkOrder se status='pending'
            - Registra no metadata['step_log']
            - Auto-completa se for última etapa

        Example:
            work.step("Mixing", 70, user=operador)
            work.step("Shaping", 74, user=operador)
            work.step("Baking", 72, user=operador)  # ← Auto-completa!
        """
        # Convert to Decimal
        if not isinstance(quantity, Decimal):
            quantity = Decimal(str(quantity))

        # Validations
        if quantity <= 0:
            raise ValidationError(_("Quantidade deve ser maior que zero"))

        if self.status not in [WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS]:
            raise ValidationError(
                _(f"Não é possível registrar etapa para ordem com status {self.status}")
            )

        # Start if needed (track for signal emission)
        is_first_step = self.status == WorkOrderStatus.PENDING

        if is_first_step:
            self.status = WorkOrderStatus.IN_PROGRESS
            self.started_at = timezone.now()

        # Initialize step_log if needed
        if "step_log" not in self.metadata:
            self.metadata["step_log"] = []

        # Record step in metadata
        self.metadata["step_log"].append(
            {
                "step": step_name,
                "quantity": float(quantity),
                "timestamp": timezone.now().isoformat(),
                "user": user.username if user else None,
            }
        )

        # Also save to dedicated fields if step name matches
        step_lower = step_name.lower()
        if step_lower in ("mixing", "mistura"):
            self.mixing = quantity
        elif step_lower in ("shaping", "modelagem", "processed"):
            self.processed_quantity = quantity
        elif step_lower in ("baking", "forneamento", "produced"):
            self.produced_quantity = quantity

        update_fields = ["status", "started_at", "metadata", "updated_at"]
        if self.mixing is not None:
            update_fields.append("mixing")
        if self.processed_quantity is not None:
            update_fields.append("processed_quantity")
        if self.produced_quantity is not None:
            update_fields.append("produced_quantity")

        self.save(update_fields=update_fields)

        logger.info(
            f"WorkOrder {self.code}: Step {step_name} completed with {quantity} units",
            extra={
                "work_order": self.pk,
                "code": self.code,
                "step": step_name,
                "quantity": float(quantity),
                "user": user.username if user else None,
            },
        )

        # Emit materials_needed on first step
        if is_first_step:
            self._emit_materials_needed()

        # Check auto-complete
        self._check_auto_complete(step_name, quantity, user)

    def _emit_materials_needed(self):
        """Emite signal de materiais necessários no início da produção."""
        from craftsman.signals import materials_needed

        # Calculate requirements from recipe
        requirements = self._calculate_requirements()

        if requirements:
            materials_needed.send(
                sender=self.__class__,
                work_order=self,
                requirements=requirements,
            )
            logger.info(
                f"WorkOrder {self.code}: materials_needed signal emitted",
                extra={
                    "work_order": self.pk,
                    "requirements_count": len(requirements),
                },
            )

    def _calculate_requirements(self) -> list[dict]:
        """
        Calcula insumos necessários baseado na receita e quantidade planejada.

        Returns:
            Lista de dicts: [{"product": ..., "quantity": ..., "position": ...}, ...]
        """
        requirements = []
        recipe = self.recipe

        # Coeficiente = quantidade planejada / quantidade base da receita
        if recipe.output_quantity and recipe.output_quantity > 0:
            coefficient = self.planned_quantity / recipe.output_quantity
        else:
            coefficient = Decimal("1")

        for item in recipe.items.filter(is_active=True):
            required_qty = item.quantity * coefficient
            requirements.append({
                "product": item.item,
                "sku": getattr(item.item, "sku", str(item.item)),
                "quantity": required_qty,
                "unit": item.unit,
                "position": item.position,
            })

        return requirements

    def _check_auto_complete(self, step_name: str, quantity: Decimal, user=None):
        """Verifica se é última etapa e auto-completa."""
        last_step = self.recipe.last_step

        if not last_step:
            return

        if step_name == last_step:
            logger.info(
                f"WorkOrder {self.code}: Last step '{step_name}' completed, auto-completing"
            )
            self.complete(quantity, user)

    def complete(self, actual_quantity: Decimal | int | float = None, user=None):
        """
        Finaliza produção.

        ✅ Chamado automaticamente na última etapa OU manualmente.

        Behavior:
            - Marca como 'completed'
            - Define actual_quantity
            - Emite signal 'production_completed'
        """
        # Convert to Decimal
        if actual_quantity is not None:
            if not isinstance(actual_quantity, Decimal):
                actual_quantity = Decimal(str(actual_quantity))
        else:
            # Use last step quantity or planned quantity
            step_log = self.metadata.get("step_log", [])
            if step_log:
                actual_quantity = Decimal(str(step_log[-1]["quantity"]))
            else:
                actual_quantity = self.planned_quantity

        if self.status == WorkOrderStatus.COMPLETED:
            logger.warning(f"WorkOrder {self.code} already completed")
            return

        self.status = WorkOrderStatus.COMPLETED
        self.actual_quantity = actual_quantity
        self.completed_at = timezone.now()

        if "completed_by" not in self.metadata:
            self.metadata["completed_by"] = user.username if user else None

        self.save(
            update_fields=[
                "status",
                "actual_quantity",
                "completed_at",
                "metadata",
                "updated_at",
            ]
        )

        logger.info(
            f"WorkOrder {self.code} completed: {actual_quantity} units produced",
            extra={
                "work_order": self.pk,
                "code": self.code,
                "actual_quantity": float(actual_quantity),
                "planned_quantity": float(self.planned_quantity),
            },
        )

        # Emit signal
        self._emit_production_completed(user)

    def _emit_production_completed(self, user=None):
        """Emite signal de produção completa."""
        from craftsman.signals import production_completed

        # Determine destination
        destination = self.destination
        if not destination and self.plan_item:
            destination = self.plan_item.destination

        production_completed.send(
            sender=self.__class__,
            work_order=self,
            actual_quantity=self.actual_quantity,
            destination=destination,
            user=user,
        )

    def pause(self, reason: str = "", user=None):
        """Pausa produção."""
        if self.status != WorkOrderStatus.IN_PROGRESS:
            raise ValidationError(_("Apenas ordens em produção podem ser pausadas"))

        self.status = WorkOrderStatus.PAUSED
        if reason:
            self.notes = f"{self.notes}\n[PAUSADO] {reason}".strip()

        self.save(update_fields=["status", "notes", "updated_at"])
        logger.info(f"WorkOrder {self.code} paused: {reason}")

    def resume(self, user=None):
        """Retoma produção pausada."""
        if self.status != WorkOrderStatus.PAUSED:
            raise ValidationError(_("Apenas ordens pausadas podem ser retomadas"))

        self.status = WorkOrderStatus.IN_PROGRESS
        self.save(update_fields=["status", "updated_at"])
        logger.info(f"WorkOrder {self.code} resumed")

    def cancel(self, reason: str = "", user=None):
        """Cancela ordem de produção."""
        if self.status in [WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED]:
            raise ValidationError(
                _("Não é possível cancelar ordem já concluída ou cancelada")
            )

        self.status = WorkOrderStatus.CANCELLED
        if reason:
            self.notes = f"{self.notes}\n[CANCELADO] {reason}".strip()

        self.save(update_fields=["status", "notes", "updated_at"])

        # Emit signal
        from craftsman.signals import order_cancelled

        order_cancelled.send(sender=self.__class__, work_order=self, reason=reason)

        logger.info(f"WorkOrder {self.code} cancelled: {reason}")

    # ══════════════════════════════════════════════════════════════
    # PROPERTIES
    # ══════════════════════════════════════════════════════════════

    @property
    def quantity(self) -> Decimal:
        """Alias for planned_quantity (backward compatibility)."""
        return self.planned_quantity

    @property
    def actual_start(self):
        """Alias for started_at (backward compatibility)."""
        return self.started_at

    @property
    def actual_end(self):
        """Alias for completed_at (backward compatibility)."""
        return self.completed_at

    @property
    def is_scheduled(self) -> bool:
        """Has scheduled date?"""
        return self.scheduled_start is not None

    @property
    def is_late(self) -> bool:
        """Is it late?"""
        if not self.scheduled_end or self.completed_at:
            return False
        return timezone.now() > self.scheduled_end

    @property
    def scheduled_date(self):
        """Get scheduled date (date part only)."""
        if self.scheduled_start:
            return self.scheduled_start.date()
        if self.plan_item:
            return self.plan_item.plan.date
        return None

    @property
    def production_date(self):
        """Get production date from plan_item or scheduled_start."""
        if self.plan_item:
            return self.plan_item.plan.date
        if self.scheduled_start:
            return self.scheduled_start.date()
        return None

    @property
    def step_log(self) -> list[dict]:
        """Get step log from metadata."""
        return self.metadata.get("step_log", [])

    @property
    def step_history(self) -> list[dict]:
        """Alias for step_log."""
        return self.step_log

    @property
    def completed_steps(self) -> list[str]:
        """Get list of completed step names."""
        return [entry["step"] for entry in self.step_log]

    @property
    def history(self) -> list[dict]:
        """
        Step history with parsed timestamps.

        Returns:
            [
                {
                    'step': 'Mixing',
                    'quantity': 50.0,
                    'completed_at': datetime(...),
                    'user': 'joao'
                },
                ...
            ]
        """
        result = []
        for entry in self.step_log:
            parsed = {**entry}
            if "timestamp" in parsed and isinstance(parsed["timestamp"], str):
                try:
                    parsed["completed_at"] = datetime.fromisoformat(parsed["timestamp"])
                except ValueError:
                    pass
            result.append(parsed)
        return result

    @property
    def progress(self) -> dict:
        """
        Progress based on completed steps.

        Returns:
            {'completed': 2, 'total': 3, 'percentage': 66}
        """
        recipe_steps = self.recipe.steps

        if not recipe_steps:
            # No steps defined, use simple status-based progress
            if self.status == WorkOrderStatus.COMPLETED:
                return {"completed": 1, "total": 1, "percentage": 100}
            elif self.status == WorkOrderStatus.IN_PROGRESS:
                return {"completed": 0, "total": 1, "percentage": 50}
            else:
                return {"completed": 0, "total": 1, "percentage": 0}

        completed = len(self.completed_steps)
        total = len(recipe_steps)

        return {
            "completed": completed,
            "total": total,
            "percentage": int(completed / total * 100) if total else 0,
        }

    @property
    def loss_quantity(self) -> Decimal | None:
        """Calculate quantity lost (planned - actual)."""
        if self.actual_quantity is not None:
            return self.planned_quantity - self.actual_quantity
        return None

    @property
    def loss_percentage(self) -> Decimal | None:
        """Calculate loss percentage."""
        if self.actual_quantity is not None and self.planned_quantity > 0:
            loss = self.planned_quantity - self.actual_quantity
            return (loss / self.planned_quantity) * 100
        return None

    @property
    def output_product(self):
        """Get output product from recipe."""
        return self.recipe.output_product

    def get_step_quantity(self, step_name: str) -> Decimal | None:
        """Get quantity for a specific step."""
        for entry in reversed(self.step_log):
            if entry.get("step") == step_name:
                return Decimal(str(entry.get("quantity", 0)))
        return None
