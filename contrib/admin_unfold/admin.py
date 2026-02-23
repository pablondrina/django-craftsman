"""
Craftsman Admin with Unfold theme.

This module provides Unfold-styled admin classes for Craftsman models.
To use, add 'craftsman.contrib.admin_unfold' to INSTALLED_APPS after 'craftsman'.

The admins will automatically register the Unfold versions.

Follows the UX patterns from batch app:
- Auto-redirect to today's date
- Auto-create PlanItems for products with active recipes
- List editable for quick updates
- Colored badges for status
"""

import logging
from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from unfold.decorators import display

from shopman_commons.contrib.admin_unfold.badges import unfold_badge, unfold_badge_numeric
from shopman_commons.contrib.admin_unfold.base import (
    BaseModelAdmin,
    BaseStackedInline,
    BaseTabularInline,
)
from shopman_commons.formatting import format_quantity

from craftsman.models import (
    IngredientCategory,
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    RecipeItem,
    WorkOrder,
    WorkOrderStatus,
)

logger = logging.getLogger(__name__)


def _position_model_has_admin():
    """Check if the configured Position model has a registered admin."""
    from craftsman.conf import get_position_model

    try:
        return admin.site.is_registered(get_position_model())
    except Exception:
        return False


class _SafeAutocompleteMixin:
    """
    Mixin that adds Position-FK fields to autocomplete_fields at runtime,
    only if the configured Position model has a registered ModelAdmin.

    Fields referencing Position must be listed in `_position_autocomplete_fields`
    instead of `autocomplete_fields` to avoid admin.E039 at check time.
    """

    _position_autocomplete_fields = ()

    def get_autocomplete_fields(self, request):
        fields = list(super().get_autocomplete_fields(request))
        if _position_model_has_admin():
            fields.extend(self._position_autocomplete_fields)
        return fields


# =============================================================================
# RECIPE ADMIN
# =============================================================================


class RecipeItemInline(_SafeAutocompleteMixin, BaseStackedInline):
    """Inline for recipe items (insumos).

    Usa StackedInline para melhor organização dos muitos campos.
    Unfold features: collapsible, fieldsets organizados.
    """

    model = RecipeItem
    extra = 0
    autocomplete_fields = ["category"]
    _position_autocomplete_fields = ("position",)

    # Unfold: inlines colapsáveis (cada item pode ser expandido/colapsado)
    tab = True

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("item_type", "item_id"),
                    ("category", "position"),
                ),
            },
        ),
        (
            _("Quantidade"),
            {
                "fields": (
                    ("quantity", "unit"),
                ),
            },
        ),
        (
            _("Alternativas"),
            {
                "classes": ["collapse"],
                "fields": (
                    ("is_alternative", "alternative_group"),
                    "is_active",
                ),
            },
        ),
    )


@admin.register(IngredientCategory)
class IngredientCategoryAdmin(BaseModelAdmin):
    """Admin for ingredient categories."""

    list_display = ["code", "name", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["code", "name"]
    ordering = ["sort_order", "name"]


@admin.register(Recipe)
class RecipeAdmin(_SafeAutocompleteMixin, BaseModelAdmin):
    """Admin interface for Recipe."""

    # Unfold options
    compressed_fields = True
    warn_unsaved_form = True

    list_display = [
        "code",
        "name",
        "get_product_display",
        "output_quantity",
        "lead_time_days",
        "is_active",
    ]
    list_filter = ["is_active", "output_type", "work_center"]
    search_fields = ["code", "name"]
    ordering = ["name"]
    prepopulated_fields = {"code": ("name",)}
    autocomplete_fields = []
    _position_autocomplete_fields = ("work_center",)

    inlines = [RecipeItemInline]

    fieldsets = (
        # Seção principal (sem tab)
        (
            _("Identificação"),
            {"fields": ("code", "name", "is_active")},
        ),
        # Tabs
        (
            _("Produto de Saída"),
            {
                "classes": ["tab"],
                "fields": ("output_type", "output_id", "output_quantity"),
            },
        ),
        (
            _("Produção"),
            {
                "classes": ["tab"],
                "fields": (
                    "work_center",
                    "lead_time_days",
                    "duration_minutes",
                ),
            },
        ),
        (
            _("Observações"),
            {
                "classes": ["tab"],
                "fields": ("notes",),
            },
        ),
        (
            _("Avançado"),
            {
                "classes": ["tab", "collapse"],
                "fields": ("metadata",),
            },
        ),
    )

    @display(description=_("Produto"))
    def get_product_display(self, obj):
        """Display output product name."""
        if obj.output_product:
            return str(obj.output_product)
        return "-"


# =============================================================================
# PLAN ADMIN
# =============================================================================


class PlanItemInline(_SafeAutocompleteMixin, BaseTabularInline):
    """Inline for plan items."""

    model = PlanItem
    extra = 0
    fields = ["recipe", "quantity", "destination", "priority"]
    autocomplete_fields = ["recipe"]
    _position_autocomplete_fields = ("destination",)
    readonly_fields = []


@admin.register(Plan)
class PlanAdmin(BaseModelAdmin):
    """Admin interface for Plan (hidden from menu, accessible via breadcrumbs)."""

    # Unfold options
    compressed_fields = True
    warn_unsaved_form = True

    list_display = [
        "date_display",
        "status_badge",
        "total_items",
        "total_quantity_display",
        "created_at",
    ]
    list_filter = ["status", "date"]
    date_hierarchy = "date"
    ordering = ["-date"]

    inlines = [PlanItemInline]

    fieldsets = (
        # Seção principal (sem tab)
        (
            _("Plano"),
            {"fields": ("date", "status")},
        ),
        # Tabs
        (
            _("Observações"),
            {
                "classes": ["tab"],
                "fields": ("notes",),
            },
        ),
        (
            _("Histórico"),
            {
                "classes": ["tab", "collapse"],
                "fields": ("approved_at", "scheduled_at", "completed_at"),
            },
        ),
    )

    readonly_fields = ["approved_at", "scheduled_at", "completed_at"]

    @display(description=_("Data"))
    def date_display(self, obj):
        """Display date in DD/MM/YY format."""
        return obj.date.strftime("%d/%m/%y")

    @display(description=_("Status"))
    def status_badge(self, obj):
        """Display colored status badge."""
        colors = {
            PlanStatus.DRAFT: "blue",
            PlanStatus.APPROVED: "yellow",
            PlanStatus.SCHEDULED: "yellow",
            PlanStatus.COMPLETED: "green",
        }
        color = colors.get(obj.status, "base")
        return unfold_badge(obj.get_status_display(), color)

    @display(description=_("Qtd Total"))
    def total_quantity_display(self, obj):
        """Display total quantity."""
        total = obj.total_quantity
        if total > 0:
            return unfold_badge_numeric(format_quantity(total), "base")
        return "-"


# =============================================================================
# PLAN ITEM ADMIN (Planejamento - Interface Principal)
# =============================================================================


@admin.register(PlanItem)
class PlanItemAdmin(_SafeAutocompleteMixin, BaseModelAdmin):
    """
    Admin de Planejamento (estilo Batch).

    - Visao agregada (1 linha = 1 produto/dia)
    - Auto-criacao ao acessar data
    - List editable inline
    """

    list_display = [
        "product_name_display",
        "date_display",
        "get_suggested",
        "quantity",
        "get_produced",
        "get_reserved",
        "get_available",
        "status_badge",
    ]

    list_filter = ["plan__date", "plan__status", "recipe"]
    search_fields = ["recipe__name"]
    list_editable = ["quantity"]
    date_hierarchy = "plan__date"
    ordering = ["-plan__date", "recipe__name"]
    autocomplete_fields = ["recipe"]
    _position_autocomplete_fields = ("destination",)

    # Unfold options
    compressed_fields = True
    warn_unsaved_form = True

    fieldsets = (
        # Seção principal (sem tab)
        (
            _("Plano"),
            {"fields": ("plan", "recipe", "destination")},
        ),
        # Tabs
        (
            _("Produção"),
            {
                "classes": ["tab"],
                "fields": ("quantity", "priority"),
            },
        ),
        (
            _("Observações"),
            {
                "classes": ["tab"],
                "fields": ("notes",),
            },
        ),
    )

    @display(description=_("Produto"))
    def product_name_display(self, obj):
        """Display product name."""
        return obj.product_name

    @display(description=_("Data"))
    def date_display(self, obj):
        """Display date in DD/MM/YY format."""
        return obj.plan.date.strftime("%d/%m/%y")

    @display(description=_("Sugerido"))
    def get_suggested(self, obj):
        """Display suggested quantity based on holds."""
        suggested = obj.get_suggested_quantity()
        if suggested > 0:
            return unfold_badge_numeric(format_quantity(suggested), "yellow")
        return "-"

    @display(description=_("Produzido"))
    def get_produced(self, obj):
        """Display produced quantity."""
        produced = obj.total_produced
        if produced > 0:
            return unfold_badge_numeric(format_quantity(produced), "green")
        return "-"

    @display(description=_("Reservado"))
    def get_reserved(self, obj):
        """Display reserved quantity (from Stockman holds)."""
        reserved = obj.get_reserved_quantity()
        if reserved > 0:
            return unfold_badge_numeric(format_quantity(reserved), "yellow")
        return "-"

    @display(description=_("Disponivel"))
    def get_available(self, obj):
        """Display available quantity (produced - reserved)."""
        available = obj.get_available_quantity()

        if available > 0:
            return unfold_badge_numeric(format_quantity(available), "green")
        elif available == 0:
            produced = obj.total_produced
            if produced > 0:
                return unfold_badge_numeric("0", "yellow")
            return "-"
        else:
            return unfold_badge_numeric(f"{format_quantity(available)}", "red")

    @display(description=_("Status"))
    def status_badge(self, obj):
        """Display status based on production progress."""
        produced = obj.total_produced
        quantity = obj.quantity

        if produced >= quantity and quantity > 0:
            return unfold_badge("Concluido", "green")
        elif produced > 0:
            return unfold_badge("Em Producao", "yellow")
        elif quantity > 0:
            return unfold_badge("Planejado", "blue")
        else:
            return unfold_badge("Pendente", "base")

    def changelist_view(self, request, extra_context=None):
        """
        Override changelist_view to:
        1. Auto-redirect to today if no date filter
        2. Auto-create PlanItems for products with active recipes
        """
        # Detect filtered date from request parameters
        date_year = request.GET.get("plan__date__year")
        date_month = request.GET.get("plan__date__month")
        date_day = request.GET.get("plan__date__day")

        # Check if ANY date parameter is present
        has_any_date_param = bool(date_year or date_month or date_day)

        # Check for other admin navigation indicators
        has_admin_nav = any(
            [
                "_changelist_filters" in request.GET,
                "p" in request.GET,  # pagination
                "o" in request.GET,  # ordering
                "q" in request.GET,  # search
                "plan__status__exact" in request.GET,
                "recipe__id__exact" in request.GET,
            ]
        )

        # Only redirect on TRUE initial access
        if not has_any_date_param and not has_admin_nav:
            today = timezone.localdate()
            changelist_url = reverse("admin:craftsman_planitem_changelist")
            return redirect(
                f"{changelist_url}?"
                f"plan__date__year={today.year}&"
                f"plan__date__month={today.month}&"
                f"plan__date__day={today.day}"
            )

        # Auto-create PlanItems for the filtered date
        if date_year and date_month and date_day:
            try:
                filtered_date = date(int(date_year), int(date_month), int(date_day))
                self._auto_create_plan_items(filtered_date)
            except (ValueError, TypeError):
                pass

        return super().changelist_view(request, extra_context)

    def _auto_create_plan_items(self, target_date: date):
        """Auto-create PlanItems for products with active recipes."""
        from craftsman.conf import get_position_model

        try:
            from offerman.models import Product
        except ImportError:
            logger.debug("offerman not installed, skipping auto-create PlanItems")
            return

        try:
            # Get or create Plan for this date
            plan, _ = Plan.objects.get_or_create(
                date=target_date, defaults={"status": PlanStatus.DRAFT}
            )

            # Get default destination
            PositionModel = get_position_model()
            destination = PositionModel.objects.filter(is_default=True).first()

            # Get active recipes for batch-produced products
            product_ct = ContentType.objects.get_for_model(Product)

            recipes_without_items = Recipe.objects.filter(
                is_active=True,
                output_type=product_ct,
            ).exclude(plan_items__plan=plan)

            # Filter to batch-produced products
            batch_produced_ids = Product.objects.filter(
                is_batch_produced=True, is_active=True
            ).values_list("id", flat=True)

            items_to_create = []
            for recipe in recipes_without_items:
                if recipe.output_id in batch_produced_ids:
                    items_to_create.append(
                        PlanItem(
                            plan=plan,
                            recipe=recipe,
                            quantity=Decimal("0"),
                            destination=destination,
                        )
                    )

            if items_to_create:
                PlanItem.objects.bulk_create(items_to_create)
                logger.info(
                    f"Created {len(items_to_create)} PlanItems for {target_date}",
                    extra={
                        "date": str(target_date),
                        "items_created": len(items_to_create),
                    },
                )

        except Exception as e:
            logger.error(f"Failed to auto-create PlanItems: {e}")

    def save_model(self, request, obj, form, change):
        """Override save to auto-create/update WorkOrder when quantity changes."""
        super().save_model(request, obj, form, change)

        # If quantity was set/changed and there's no active WorkOrder, create one
        if obj.quantity > 0 and not obj.active_work_order:
            # Only auto-create if plan is scheduled or we want auto-scheduling
            if obj.plan.status in [PlanStatus.SCHEDULED, PlanStatus.APPROVED]:
                destination = obj.destination or obj.recipe.work_center
                WorkOrder.objects.create(
                    plan_item=obj,
                    recipe=obj.recipe,
                    planned_quantity=obj.quantity,
                    status=WorkOrderStatus.PENDING,
                    destination=destination,
                )
                logger.info(f"Auto-created WorkOrder for PlanItem {obj.pk}")


# =============================================================================
# WORK ORDER ADMIN (Execucao - Estilo Batch)
# =============================================================================


@admin.register(WorkOrder)
class WorkOrderAdmin(_SafeAutocompleteMixin, BaseModelAdmin):
    """
    Admin de Execucao (estilo Batch).

    - Visao semelhante ao Batch com colunas editaveis
    - planned_quantity e actual_quantity editaveis
    - Auto-redirect para hoje
    """

    list_display = [
        "product_display",
        "date_display",
        "planned_quantity",
        "process_quantity",
        "output_quantity",
        "loss_display",
        "status_badge",
    ]

    list_filter = ["status", "recipe", "location"]
    search_fields = ["code", "recipe__name"]
    list_editable = [
        "planned_quantity",
        "process_quantity",
        "output_quantity",
    ]
    date_hierarchy = "scheduled_start"
    ordering = ["-created_at"]
    autocomplete_fields = [
        "recipe",
        "assigned_to",
        "plan_item",
    ]
    _position_autocomplete_fields = ("destination", "location")

    # Unfold options
    compressed_fields = True
    warn_unsaved_form = True

    fieldsets = (
        # Seção principal (sem tab)
        (
            _("Identificação"),
            {"fields": ("code", "recipe", "plan_item", "status")},
        ),
        # Tabs
        (
            _("Quantidades"),
            {
                "classes": ["tab"],
                "fields": (
                    "planned_quantity",
                    "process_quantity",
                    "output_quantity",
                    "actual_quantity",
                ),
            },
        ),
        (
            _("Localização"),
            {
                "classes": ["tab"],
                "fields": ("destination", "location"),
            },
        ),
        (
            _("Agendamento"),
            {
                "classes": ["tab"],
                "fields": ("scheduled_start", "scheduled_end", "assigned_to"),
            },
        ),
        (
            _("Execução"),
            {
                "classes": ["tab", "collapse"],
                "fields": ("started_at", "completed_at"),
            },
        ),
        (
            _("Observações"),
            {
                "classes": ["tab"],
                "fields": ("notes",),
            },
        ),
        (
            _("Metadados"),
            {
                "classes": ["tab", "collapse"],
                "fields": ("metadata",),
            },
        ),
    )

    readonly_fields = [
        "code",
        "started_at",
        "completed_at",
    ]

    @display(description=_("Produto"))
    def product_display(self, obj):
        """Display product name from recipe."""
        if obj.recipe and obj.recipe.output_product:
            return str(obj.recipe.output_product)
        return obj.recipe.name if obj.recipe else "-"

    @display(description=_("Data"))
    def date_display(self, obj):
        """Display date in DD/MM/YY format."""
        prod_date = obj.production_date
        if prod_date:
            return prod_date.strftime("%d/%m/%y")
        return "-"

    @display(description=_("Perda"))
    def loss_display(self, obj):
        """Display loss quantity and percentage."""
        if obj.actual_quantity is None:
            return "-"

        loss = obj.loss_quantity
        if loss is None or loss == 0:
            return unfold_badge_numeric("0", "green")

        pct = obj.loss_percentage
        loss_formatted = format_quantity(loss)
        if pct and pct > 10:
            return unfold_badge_numeric(f"{loss_formatted} ({pct:.1f}%)", "red")
        elif pct and pct > 5:
            return unfold_badge_numeric(f"{loss_formatted} ({pct:.1f}%)", "yellow")
        else:
            return unfold_badge_numeric(loss_formatted, "base")

    @display(description=_("Status"))
    def status_badge(self, obj):
        """Display colored status badge."""
        colors = {
            WorkOrderStatus.PENDING: "blue",
            WorkOrderStatus.IN_PROGRESS: "yellow",
            WorkOrderStatus.PAUSED: "yellow",
            WorkOrderStatus.COMPLETED: "green",
            WorkOrderStatus.CANCELLED: "red",
        }
        color = colors.get(obj.status, "base")
        return unfold_badge(obj.get_status_display(), color)

    def get_readonly_fields(self, request, obj=None):
        """Make code readonly only for existing objects."""
        readonly = list(super().get_readonly_fields(request, obj))
        if obj:
            if "code" not in readonly:
                readonly.append("code")
        return readonly

    def changelist_view(self, request, extra_context=None):
        """
        Override changelist_view to auto-redirect to today if no date filter.
        """
        # Detect filtered date from request parameters
        date_year = request.GET.get("scheduled_start__year")
        date_month = request.GET.get("scheduled_start__month")
        date_day = request.GET.get("scheduled_start__day")

        # Check if ANY date parameter is present
        has_any_date_param = bool(date_year or date_month or date_day)

        # Check for other admin navigation indicators
        has_admin_nav = any(
            [
                "_changelist_filters" in request.GET,
                "p" in request.GET,  # pagination
                "o" in request.GET,  # ordering
                "q" in request.GET,  # search
                "status__exact" in request.GET,
                "recipe__id__exact" in request.GET,
            ]
        )

        # Only redirect on TRUE initial access
        if not has_any_date_param and not has_admin_nav:
            today = timezone.localdate()
            changelist_url = reverse("admin:craftsman_workorder_changelist")
            return redirect(
                f"{changelist_url}?"
                f"scheduled_start__year={today.year}&"
                f"scheduled_start__month={today.month}&"
                f"scheduled_start__day={today.day}"
            )

        return super().changelist_view(request, extra_context)

    def save_model(self, request, obj, form, change):
        """Override save to handle status transitions when step fields are set."""
        if change:
            old_obj = WorkOrder.objects.get(pk=obj.pk)

            # Check if any step field was set (transition to IN_PROGRESS)
            step_fields_changed = any(
                [
                    obj.process_quantity is not None
                    and old_obj.process_quantity is None,
                    obj.output_quantity is not None
                    and old_obj.output_quantity is None,
                ]
            )

            if step_fields_changed and obj.status == WorkOrderStatus.PENDING:
                obj.status = WorkOrderStatus.IN_PROGRESS
                obj.started_at = timezone.now()
                logger.info(f"WorkOrder {obj.code} started via admin")

            # If actual_quantity was set, complete it
            if obj.actual_quantity is not None and old_obj.actual_quantity is None:
                if obj.status in [WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS]:
                    if obj.status == WorkOrderStatus.PENDING:
                        obj.status = WorkOrderStatus.IN_PROGRESS
                        obj.started_at = timezone.now()

                    obj.status = WorkOrderStatus.COMPLETED
                    obj.completed_at = timezone.now()

                    if "completed_by" not in obj.metadata:
                        obj.metadata["completed_by"] = request.user.username

                    logger.info(f"WorkOrder {obj.code} completed via admin")

            # Auto-complete if output_quantity (last step) was set and actual_quantity is empty
            if obj.output_quantity is not None and old_obj.output_quantity is None:
                if obj.actual_quantity is None:
                    obj.actual_quantity = obj.output_quantity
                    obj.status = WorkOrderStatus.COMPLETED
                    obj.completed_at = timezone.now()
                    if "completed_by" not in obj.metadata:
                        obj.metadata["completed_by"] = request.user.username
                    logger.info(
                        f"WorkOrder {obj.code} auto-completed via output_quantity"
                    )

        super().save_model(request, obj, form, change)
