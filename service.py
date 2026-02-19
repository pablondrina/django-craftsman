"""
Craftsman Service (v2.3) - Thin wrapper over models.

✅ LÓGICA DE NEGÓCIO ESTÁ NOS MODELOS (SIREL principle)
Esta classe é um thin wrapper para conveniência e compatibilidade.

Usage:
    from craftsman import craft, CraftError

    # Planning
    item = craft.plan(50, croissant, date(2025, 12, 17), vitrine)
    craft.approve(date(2025, 12, 17))
    craft.schedule(date(2025, 12, 17))

    # Execution (delegated to WorkOrder model)
    wo = craft.get_work_order(item)
    wo.step("Mixing", 70, user=operador)
    wo.step("Shaping", 74, user=operador)
    wo.step("Baking", 72, user=operador)  # Auto-completes!

    # Or using craft API (deprecated)
    craft.step(70, wo, "Mixing", user=operador)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from craftsman.exceptions import CraftError
from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    WorkOrder,
    WorkOrderStatus,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# RESULT TYPES
# ══════════════════════════════════════════════════════════════


@dataclass
class InputShortage:
    """Informação sobre insumo insuficiente."""

    sku: str
    required: Decimal
    available: Decimal

    @property
    def shortage(self) -> Decimal:
        return self.required - self.available


@dataclass
class ScheduleResult:
    """
    Resultado do agendamento de produção.

    Se success=True: work_orders contém as ordens criadas
    Se success=False: errors contém os insumos faltantes
    """

    success: bool
    work_orders: list[WorkOrder] = field(default_factory=list)
    errors: list[InputShortage] = field(default_factory=list)
    message: str | None = None

    @property
    def has_shortages(self) -> bool:
        return len(self.errors) > 0


class Craft:
    """
    Main API for Craftsman (thin wrapper).

    ✅ Lógica de negócio está nos modelos!
    Esta classe apenas facilita o uso e mantém compatibilidade.
    """

    # ══════════════════════════════════════════════════════════════
    # PLANNING
    # ══════════════════════════════════════════════════════════════

    @classmethod
    def plan(
        cls,
        quantity: Decimal | int | float,
        product,
        production_date: date,
        destination=None,
        priority: int = 50,
    ) -> PlanItem:
        """
        Adiciona item ao plano.

        Args:
            quantity: Quantidade a produzir
            product: Produto a produzir
            production_date: Data de produção
            destination: Position destino (opcional)
            priority: Prioridade (maior = mais prioritário)

        Returns:
            PlanItem criado

        Example:
            craft.plan(50, croissant, date(2025, 12, 17), vitrine)
        """
        quantity = Decimal(str(quantity))

        if quantity <= 0:
            raise CraftError("INVALID_QUANTITY", quantity=float(quantity))

        recipe = cls.find_recipe(product)
        if not recipe:
            raise CraftError("RECIPE_NOT_FOUND", product=str(product))

        # Get or create plan for this date
        plan, _ = Plan.objects.get_or_create(
            date=production_date, defaults={"status": PlanStatus.DRAFT}
        )

        # Create or update plan item
        item, created = PlanItem.objects.get_or_create(
            plan=plan,
            recipe=recipe,
            defaults={
                "quantity": quantity,
                "destination": destination,
                "priority": priority,
            },
        )

        if not created:
            # Update existing item
            item.quantity = quantity
            if destination:
                item.destination = destination
            if priority != 50:
                item.priority = priority
            item.save()

        logger.info(
            f"Planned {quantity} of {product} for {production_date}",
            extra={
                "product": str(product),
                "quantity": float(quantity),
                "date": str(production_date),
            },
        )

        return item

    @classmethod
    def approve(cls, production_date: date, user=None) -> Plan:
        """
        Aprova plano para uma data.

        Args:
            production_date: Data do plano
            user: Usuário que aprovou

        Returns:
            Plan aprovado
        """
        try:
            plan = Plan.objects.get(date=production_date)
        except Plan.DoesNotExist:
            raise CraftError("PLAN_NOT_FOUND", date=str(production_date))

        plan.approve(user)
        return plan

    @classmethod
    def schedule(
        cls,
        production_date: date,
        start_time: time = None,
        location=None,
        user=None,
        skip_reservation: bool = False,
    ) -> ScheduleResult:
        """
        Transforma plano aprovado em WorkOrders.

        Se CRAFTSMAN_RESERVE_INPUTS estiver habilitado (e skip_reservation=False),
        verifica disponibilidade e reserva os insumos antes de criar as WorkOrders.

        Args:
            production_date: Data do plano
            start_time: Horário de início (opcional)
            location: Local de produção (opcional)
            user: Usuário que agendou
            skip_reservation: Se True, ignora reserva de insumos (comportamento legado)

        Returns:
            ScheduleResult com work_orders ou errors
        """
        try:
            plan = Plan.objects.get(date=production_date, status=PlanStatus.APPROVED)
        except Plan.DoesNotExist:
            raise CraftError(
                "PLAN_NOT_FOUND_OR_NOT_APPROVED", date=str(production_date)
            )

        # Verificar se reserva está habilitada
        reserve_inputs = getattr(settings, "CRAFTSMAN_RESERVE_INPUTS", False)

        if reserve_inputs and not skip_reservation:
            return cls._schedule_with_reservation(
                plan, production_date, start_time, location, user
            )
        else:
            return cls._schedule_without_reservation(
                plan, production_date, start_time, location, user
            )

    @classmethod
    def _schedule_without_reservation(
        cls,
        plan: Plan,
        production_date: date,
        start_time: time = None,
        location=None,
        user=None,
    ) -> ScheduleResult:
        """Agendamento sem reserva de insumos (comportamento legado)."""
        work_orders = []

        with transaction.atomic():
            for item in plan.items.all():
                if item.quantity <= 0:
                    continue

                scheduled_start = None
                if start_time:
                    scheduled_start = datetime.combine(production_date, start_time)
                    if timezone.is_naive(scheduled_start):
                        scheduled_start = timezone.make_aware(scheduled_start)

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
                        "reservation_mode": "disabled",
                    },
                )
                work_orders.append(wo)

            plan.status = PlanStatus.SCHEDULED
            plan.scheduled_at = timezone.now()
            plan.save(update_fields=["status", "scheduled_at"])

        logger.info(
            f"Scheduled {len(work_orders)} work orders for {production_date} (no reservation)",
            extra={
                "date": str(production_date),
                "work_orders": len(work_orders),
            },
        )

        return ScheduleResult(success=True, work_orders=work_orders)

    @classmethod
    def _schedule_with_reservation(
        cls,
        plan: Plan,
        production_date: date,
        start_time: time = None,
        location=None,
        user=None,
    ) -> ScheduleResult:
        """Agendamento com reserva de materiais."""
        from craftsman.adapters import get_stock_backend
        from craftsman.protocols.stock import MaterialNeed

        backend = get_stock_backend()

        # 1. Calcular TODOS os materiais necessários
        all_materials: dict[str, Decimal] = {}

        for item in plan.items.all():
            if item.quantity <= 0:
                continue

            recipe = item.recipe
            coefficient = (
                item.quantity / recipe.output_quantity
                if recipe.output_quantity > 0
                else Decimal("1")
            )

            for recipe_item in recipe.items.filter(is_active=True):
                sku = getattr(recipe_item.item, "sku", str(recipe_item.item))
                required_qty = recipe_item.quantity * coefficient

                if sku in all_materials:
                    all_materials[sku] += required_qty
                else:
                    all_materials[sku] = required_qty

        # 2. Verificar disponibilidade
        materials_list = [
            MaterialNeed(sku=sku, quantity=qty)
            for sku, qty in all_materials.items()
        ]

        availability = backend.available(materials_list)

        if not availability.all_available:
            # Retornar erros detalhados
            errors = [
                InputShortage(
                    sku=mat.sku,
                    required=mat.needed,
                    available=mat.available,
                )
                for mat in availability.materials
                if not mat.sufficient
            ]

            logger.warning(
                f"Schedule failed for {production_date}: insufficient materials",
                extra={
                    "date": str(production_date),
                    "shortages": [
                        {"sku": e.sku, "required": float(e.required), "available": float(e.available)}
                        for e in errors
                    ],
                },
            )

            return ScheduleResult(
                success=False,
                errors=errors,
                message="Estoque insuficiente para alguns materiais",
            )

        # 3. Reservar tudo (dentro de transação)
        with transaction.atomic():
            work_orders = []
            all_holds = []

            for item in plan.items.all():
                if item.quantity <= 0:
                    continue

                scheduled_start = None
                if start_time:
                    scheduled_start = datetime.combine(production_date, start_time)
                    if timezone.is_naive(scheduled_start):
                        scheduled_start = timezone.make_aware(scheduled_start)

                # Criar WorkOrder primeiro (para ter o UUID)
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
                        "reservation_mode": "enabled",
                    },
                )

                # Calcular materiais para esta WO específica
                wo_materials = cls._calculate_wo_materials(wo)

                # Reservar materiais
                reserve_result = backend.reserve(
                    materials=wo_materials,
                    work_order_id=str(wo.uuid),
                    metadata={"plan_date": str(production_date)},
                )

                if not reserve_result.success:
                    # Rollback acontece automaticamente pela transação
                    logger.error(
                        f"Failed to reserve materials for WO {wo.code}",
                        extra={"work_order": wo.code, "message": reserve_result.message},
                    )
                    raise CraftError(
                        "RESERVATION_FAILED",
                        work_order=wo.code,
                        message=reserve_result.message,
                    )

                # Salvar referência aos holds no metadata
                wo.metadata["holds"] = [
                    {"sku": h.sku, "quantity": float(h.quantity), "hold_id": h.hold_id}
                    for h in reserve_result.holds
                ]
                wo.save(update_fields=["metadata"])

                all_holds.extend(reserve_result.holds)
                work_orders.append(wo)

            # Atualizar status do plano
            plan.status = PlanStatus.SCHEDULED
            plan.scheduled_at = timezone.now()
            plan.save(update_fields=["status", "scheduled_at"])

        logger.info(
            f"Scheduled {len(work_orders)} work orders for {production_date} (with reservation)",
            extra={
                "date": str(production_date),
                "work_orders": len(work_orders),
                "holds_created": len(all_holds),
            },
        )

        return ScheduleResult(success=True, work_orders=work_orders)

    @classmethod
    def _calculate_wo_materials(cls, work_order: WorkOrder) -> list:
        """Calcula materiais necessários para uma WorkOrder."""
        from craftsman.protocols.stock import MaterialNeed

        recipe = work_order.recipe
        coefficient = (
            work_order.planned_quantity / recipe.output_quantity
            if recipe.output_quantity > 0
            else Decimal("1")
        )

        materials = []
        for item in recipe.items.filter(is_active=True):
            sku = getattr(item.item, "sku", str(item.item))
            required_qty = item.quantity * coefficient

            materials.append(
                MaterialNeed(
                    sku=sku,
                    quantity=required_qty,
                    unit=item.unit,
                    position_code=item.position.code if item.position else None,
                )
            )

        return materials

    # ══════════════════════════════════════════════════════════════
    # EXECUTION (thin wrappers over WorkOrder methods)
    # ══════════════════════════════════════════════════════════════

    @classmethod
    def step(
        cls,
        quantity: Decimal | int | float,
        work_order: WorkOrder,
        step_name: str,
        user=None,
    ) -> WorkOrder:
        """
        ⚠️ DEPRECATED: Use work.step() diretamente.

        Registra etapa de produção.
        Mantido apenas para compatibilidade com código legado.

        Prefira:
            work.step("Mixing", 70, user=operador)

        Em vez de:
            craft.step(70, work, "Mixing", user=operador)
        """
        import warnings

        warnings.warn(
            "craft.step() is deprecated. Use work.step() directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        work_order.step(step_name, quantity, user)
        work_order.refresh_from_db()
        return work_order

    @classmethod
    def complete(
        cls,
        work_order: WorkOrder,
        actual_quantity: Decimal | int | float = None,
        user=None,
    ) -> WorkOrder:
        """
        ✅ Delega ao modelo.

        Completa ordem de produção.
        """
        work_order.complete(actual_quantity, user)
        work_order.refresh_from_db()
        return work_order

    @classmethod
    def start(cls, work_order: WorkOrder, user=None) -> WorkOrder:
        """
        Inicia produção.

        ✅ Delega ao modelo via record_step com step vazio ou primeiro step.
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

        requirements = cls._calculate_material_requirements(work_order)
        materials_needed.send(
            sender=cls, work_order=work_order, requirements=requirements
        )

        logger.info(f"Started WorkOrder {work_order.code}")

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

    # ══════════════════════════════════════════════════════════════
    # LEGACY METHODS (backward compatibility)
    # ══════════════════════════════════════════════════════════════

    @classmethod
    def create(
        cls,
        quantity: Decimal | int | float,
        recipe: Recipe,
        destination,
        scheduled_start: datetime = None,
        location=None,
        assigned_to=None,
        source=None,
        code: str = None,
        notes: str = "",
    ) -> WorkOrder:
        """
        Create work order (legacy API).

        ⚠️ Prefer using plan() + schedule() for proper MPS flow.
        """
        quantity = Decimal(str(quantity))

        if quantity <= 0:
            raise CraftError("INVALID_QUANTITY", quantity=float(quantity))

        # Calculate scheduled_end if scheduled_start and duration provided
        scheduled_end = None
        if scheduled_start and recipe.duration_minutes:
            from datetime import timedelta

            scheduled_end = scheduled_start + timedelta(minutes=recipe.duration_minutes)

        # Handle source GenericForeignKey
        source_type = None
        source_id = None
        if source is not None:
            source_type = ContentType.objects.get_for_model(source)
            source_id = source.pk

        wo = WorkOrder.objects.create(
            code=code or "",  # Will be auto-generated if empty
            recipe=recipe,
            planned_quantity=quantity,
            status=WorkOrderStatus.PENDING,
            destination=destination,
            location=location,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            assigned_to=assigned_to,
            source_type=source_type,
            source_id=source_id,
            notes=notes,
            metadata={"step_log": []},
        )

        logger.info(
            f"Created WorkOrder {wo.code}",
            extra={
                "work_order": wo.code,
                "recipe": recipe.code,
                "quantity": float(quantity),
            },
        )

        return wo

    @classmethod
    def create_batch(
        cls,
        production_date: date,
        items: list[dict],
        start_time: time = None,
        location=None,
        assigned_to=None,
    ) -> list[WorkOrder]:
        """
        Create multiple WorkOrders for a production day (legacy API).

        ⚠️ Prefer using plan() + schedule() for proper MPS flow.
        """
        if start_time is None:
            start_time = time(6, 0)

        scheduled_start = datetime.combine(production_date, start_time)
        if timezone.is_naive(scheduled_start):
            scheduled_start = timezone.make_aware(scheduled_start)

        work_orders = []

        for item in items:
            recipe = item["recipe"]
            quantity = item["quantity"]
            destination = item["destination"]

            item_location = item.get("location", location)
            item_assigned_to = item.get("assigned_to", assigned_to)

            wo = cls.create(
                quantity=quantity,
                recipe=recipe,
                destination=destination,
                scheduled_start=scheduled_start,
                location=item_location,
                assigned_to=item_assigned_to,
            )
            work_orders.append(wo)

            if recipe.duration_minutes:
                from datetime import timedelta

                scheduled_start = scheduled_start + timedelta(
                    minutes=recipe.duration_minutes
                )

        return work_orders

    # ══════════════════════════════════════════════════════════════
    # QUERIES
    # ══════════════════════════════════════════════════════════════

    @classmethod
    def find_recipe(cls, product) -> Recipe | None:
        """Find active recipe for a product."""
        ct = ContentType.objects.get_for_model(product)
        return Recipe.objects.filter(
            output_type=ct, output_id=product.pk, is_active=True
        ).first()

    @classmethod
    def get_plan(cls, production_date: date) -> Plan | None:
        """Get plan for a date."""
        return Plan.objects.filter(date=production_date).first()

    @classmethod
    def get_plan_item(cls, product, production_date: date) -> PlanItem | None:
        """Get plan item for a product/date."""
        recipe = cls.find_recipe(product)
        if not recipe:
            return None

        return PlanItem.objects.filter(
            plan__date=production_date, recipe=recipe
        ).first()

    @classmethod
    def get_work_order(cls, plan_item: PlanItem) -> WorkOrder | None:
        """Get active work order for a plan item."""
        return plan_item.active_work_order

    @classmethod
    def get_pending(
        cls, production_date: date = None, location=None
    ) -> list[WorkOrder]:
        """Get pending work orders."""
        qs = WorkOrder.objects.filter(status=WorkOrderStatus.PENDING)

        if production_date:
            qs = qs.filter(plan_item__plan__date=production_date) | qs.filter(
                scheduled_start__date=production_date
            )

        if location:
            qs = qs.filter(location=location)

        return list(qs.order_by("scheduled_start", "created_at"))

    @classmethod
    def get_in_progress(cls, location=None) -> list[WorkOrder]:
        """Get in-progress work orders."""
        qs = WorkOrder.objects.filter(status=WorkOrderStatus.IN_PROGRESS)

        if location:
            qs = qs.filter(location=location)

        return list(qs.order_by("started_at"))

    # ══════════════════════════════════════════════════════════════
    # INTERNALS
    # ══════════════════════════════════════════════════════════════

    @classmethod
    def _calculate_material_requirements(cls, work_order: WorkOrder) -> list[dict]:
        """Calculate material requirements for a work order."""
        recipe = work_order.recipe
        multiplier = work_order.planned_quantity / recipe.output_quantity

        requirements = []

        for inp in recipe.items.filter(is_active=True):
            requirements.append(
                {
                    "product": inp.input_product,
                    "quantity": inp.quantity * multiplier,
                    "position": inp.position,
                }
            )

        return requirements
