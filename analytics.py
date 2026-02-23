"""
Craftsman Analytics.

Provides production analytics and reporting.
Uses aggregate()/annotate() for O(1) memory SQL queries wherever possible.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import (
    Avg,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from craftsman.models import WorkOrder, WorkOrderStatus


class ProductionAnalytics:
    """Analytics for production data."""

    @classmethod
    def loss_by_step(
        cls, recipe, date_from: date = None, date_to: date = None
    ) -> dict[str, dict]:
        """
        Calculate losses per step for a recipe.

        Note: Step data lives in metadata JSONField (step_log), so full SQL
        aggregation isn't possible. We minimize DB load by using values_list
        to fetch only the needed columns.

        Returns:
            {
                'Mixing': {
                    'avg_planned': 50.0,
                    'avg_actual': 48.0,
                    'avg_loss': 2.0,
                    'avg_loss_pct': 4.0,
                    'sample_size': 42
                },
                ...
            }
        """
        qs = WorkOrder.objects.filter(
            recipe=recipe, status=WorkOrderStatus.COMPLETED
        )

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        step_names = recipe.steps or []
        if not step_names:
            return {}

        # Fetch only the columns we need (not full model instances)
        rows = qs.values_list("planned_quantity", "metadata")

        # Accumulate per step
        accum: dict[str, dict] = {
            name: {"planned_sum": 0.0, "actual_sum": 0.0, "count": 0}
            for name in step_names
        }

        for planned_qty, metadata in rows:
            step_log = metadata.get("step_log", []) if metadata else []
            step_map = {entry["step"]: entry for entry in step_log}

            for step_name in step_names:
                entry = step_map.get(step_name)
                if entry:
                    accum[step_name]["planned_sum"] += float(planned_qty)
                    accum[step_name]["actual_sum"] += entry.get("quantity", 0)
                    accum[step_name]["count"] += 1

        # Build results
        results = {}
        for step_name in step_names:
            data = accum[step_name]
            n = data["count"]
            if n > 0:
                avg_planned = data["planned_sum"] / n
                avg_actual = data["actual_sum"] / n
                avg_loss = avg_planned - avg_actual
                avg_loss_pct = (avg_loss / avg_planned * 100) if avg_planned > 0 else 0
                results[step_name] = {
                    "avg_planned": round(avg_planned, 2),
                    "avg_actual": round(avg_actual, 2),
                    "avg_loss": round(avg_loss, 2),
                    "avg_loss_pct": round(avg_loss_pct, 2),
                    "sample_size": n,
                }
            else:
                results[step_name] = {
                    "avg_planned": 0,
                    "avg_actual": 0,
                    "avg_loss": 0,
                    "avg_loss_pct": 0,
                    "sample_size": 0,
                }

        return results

    @classmethod
    def efficiency_by_user(
        cls, user, step_name: str = None, date_from: date = None
    ) -> dict[str, Any]:
        """
        Calculate efficiency for a user using SQL aggregation.

        Returns:
            {
                'user': 'Maria',
                'efficiency_pct': 96.5,
                'total_work_orders': 42,
                'avg_loss_pct': 3.5
            }
        """
        qs = WorkOrder.objects.filter(
            assigned_to=user, status=WorkOrderStatus.COMPLETED
        )

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)

        stats = qs.aggregate(
            total_planned=Coalesce(
                Sum("planned_quantity"), Decimal("0"), output_field=DecimalField()
            ),
            total_actual=Coalesce(
                Sum("actual_quantity"), Decimal("0"), output_field=DecimalField()
            ),
            total_orders=Count("id"),
        )

        total_planned = stats["total_planned"]
        total_actual = stats["total_actual"]
        total_orders = stats["total_orders"]

        if total_planned > 0:
            efficiency = (total_actual / total_planned) * 100
            avg_loss_pct = 100 - float(efficiency)
        else:
            efficiency = Decimal("100")
            avg_loss_pct = 0

        return {
            "user": user.username if user else "Unknown",
            "efficiency_pct": round(float(efficiency), 2),
            "total_work_orders": total_orders,
            "avg_loss_pct": round(avg_loss_pct, 2),
        }

    @classmethod
    def throughput_by_location(
        cls, location, date_from: date = None, date_to: date = None
    ) -> dict[str, Any]:
        """
        Calculate throughput for a workstation using SQL aggregation.

        Returns:
            {
                'location': 'Forno 1',
                'total_orders': 42,
                'total_quantity': 2100.0,
                'avg_quantity_per_order': 50.0,
                'avg_duration_minutes': 180.0,
            }
        """
        qs = WorkOrder.objects.filter(
            location=location, status=WorkOrderStatus.COMPLETED
        )

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        stats = qs.aggregate(
            total_orders=Count("id"),
            total_quantity=Coalesce(
                Sum("actual_quantity"), Decimal("0"), output_field=DecimalField()
            ),
            avg_quantity=Coalesce(
                Avg("actual_quantity"), Decimal("0"), output_field=DecimalField()
            ),
        )

        # Duration requires Python — interval arithmetic in annotations
        # is DB-specific and overly complex for this use case.
        duration_qs = qs.filter(
            started_at__isnull=False, completed_at__isnull=False
        ).values_list("started_at", "completed_at")

        durations = [
            (completed - started).total_seconds() / 60
            for started, completed in duration_qs
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "location": str(location) if location else "Unknown",
            "total_orders": stats["total_orders"],
            "total_quantity": float(stats["total_quantity"]),
            "avg_quantity_per_order": round(float(stats["avg_quantity"]), 2),
            "avg_duration_minutes": round(avg_duration, 1),
        }

    @classmethod
    def summary(cls, date_from: date = None, date_to: date = None) -> dict[str, Any]:
        """
        Get overall production summary in a single query.

        Returns:
            {
                'total_orders': 150,
                'completed_orders': 120,
                'pending_orders': 20,
                'in_progress_orders': 10,
                'total_planned': 5000.0,
                'total_produced': 4800.0,
                'overall_efficiency': 96.0,
            }
        """
        qs = WorkOrder.objects.all()

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        stats = qs.aggregate(
            total_orders=Count("id"),
            completed_orders=Count("id", filter=Q(status=WorkOrderStatus.COMPLETED)),
            pending_orders=Count("id", filter=Q(status=WorkOrderStatus.PENDING)),
            in_progress_orders=Count(
                "id", filter=Q(status=WorkOrderStatus.IN_PROGRESS)
            ),
            total_planned=Coalesce(
                Sum(
                    "planned_quantity",
                    filter=Q(status=WorkOrderStatus.COMPLETED),
                ),
                Decimal("0"),
                output_field=DecimalField(),
            ),
            total_produced=Coalesce(
                Sum(
                    "actual_quantity",
                    filter=Q(status=WorkOrderStatus.COMPLETED),
                ),
                Decimal("0"),
                output_field=DecimalField(),
            ),
        )

        total_planned = stats["total_planned"]
        total_produced = stats["total_produced"]

        efficiency = (
            (total_produced / total_planned * 100) if total_planned > 0 else 100
        )

        return {
            "total_orders": stats["total_orders"],
            "completed_orders": stats["completed_orders"],
            "pending_orders": stats["pending_orders"],
            "in_progress_orders": stats["in_progress_orders"],
            "total_planned": float(total_planned),
            "total_produced": float(total_produced),
            "overall_efficiency": round(float(efficiency), 2),
        }
