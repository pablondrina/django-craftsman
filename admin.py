"""
Craftsman Admin — Basic Django admin for Recipe, Plan, PlanItem, WorkOrder.

For the Unfold-themed admin, add 'craftsman.contrib.admin_unfold' to INSTALLED_APPS.
This module provides a fallback admin that works without Unfold.

If 'craftsman.contrib.admin_unfold' is in INSTALLED_APPS, this module
skips registration to avoid AlreadyRegistered errors.
"""

from django.apps import apps
from django.contrib import admin

from craftsman.models import Plan, PlanItem, Recipe, WorkOrder


# Only register basic admin if Unfold contrib is NOT installed
if not apps.is_installed("craftsman.contrib.admin_unfold"):

    # ── Recipe ──

    class RecipeItemInline(admin.TabularInline):
        """Inline for recipe ingredients."""

        from craftsman.models import RecipeItem

        model = RecipeItem
        extra = 1
        fields = ("item_type", "item_id", "quantity", "unit", "is_active")

    @admin.register(Recipe)
    class RecipeAdmin(admin.ModelAdmin):
        """Admin for production recipes."""

        list_display = ("code", "name", "output_quantity", "lead_time_days", "is_active")
        list_filter = ("is_active",)
        search_fields = ("code", "name")
        inlines = [RecipeItemInline]
        readonly_fields = ("uuid", "created_at", "updated_at")

    # ── Plan ──

    class PlanItemInline(admin.TabularInline):
        """Inline for plan items."""

        model = PlanItem
        extra = 1
        fields = ("recipe", "quantity", "destination")
        raw_id_fields = ("recipe",)

    @admin.register(Plan)
    class PlanAdmin(admin.ModelAdmin):
        """Admin for production plans (MPS)."""

        list_display = ("date", "status", "created_at")
        list_filter = ("status", "date")
        date_hierarchy = "date"
        inlines = [PlanItemInline]
        readonly_fields = ("uuid", "created_at", "updated_at", "scheduled_at")

    # ── PlanItem ──

    @admin.register(PlanItem)
    class PlanItemAdmin(admin.ModelAdmin):
        """Admin for individual plan items."""

        list_display = ("plan", "recipe", "quantity", "destination")
        list_filter = ("plan__date", "plan__status")
        raw_id_fields = ("plan", "recipe")

    # ── WorkOrder ──

    @admin.register(WorkOrder)
    class WorkOrderAdmin(admin.ModelAdmin):
        """Admin for work orders."""

        list_display = ("code", "recipe", "planned_quantity", "actual_quantity", "status", "scheduled_start")
        list_filter = ("status",)
        search_fields = ("code",)
        raw_id_fields = ("plan_item", "recipe")
        readonly_fields = ("uuid", "code", "created_at", "updated_at", "started_at", "completed_at")
