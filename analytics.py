"""
Craftsman Analytics.

Provides production analytics and reporting.
"""

from decimal import Decimal
from datetime import date
from typing import Any

from django.db.models import Avg, Count, Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import Coalesce

from craftsman.models import WorkOrder, WorkOrderStatus, Recipe


class ProductionAnalytics:
    """Analytics for production data."""

    @classmethod
    def loss_by_step(
        cls, recipe: Recipe, date_from: date = None, date_to: date = None
    ) -> dict[str, dict]:
        """
        Calculate losses per step for a recipe.

        Args:
            recipe: Recipe to analyze
            date_from: Start date filter (optional)
            date_to: End date filter (optional)

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
        # Get completed work orders for this recipe
        qs = WorkOrder.objects.filter(recipe=recipe, status=WorkOrderStatus.COMPLETED)

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        # Get step definitions from recipe
        steps = recipe.metadata.get("steps", [])
        step_names = [s["name"] for s in steps]

        # Aggregate step data from metadata
        results = {}

        for step_name in step_names:
            step_data = []

            for wo in qs:
                step_log = wo.metadata.get("step_log", [])
                for entry in step_log:
                    if entry.get("step") == step_name:
                        step_data.append(
                            {
                                "quantity": entry.get("quantity", 0),
                                "planned": float(wo.quantity),
                            }
                        )
                        break

            if step_data:
                planned_total = sum(d["planned"] for d in step_data)
                actual_total = sum(d["quantity"] for d in step_data)
                sample_size = len(step_data)

                avg_planned = planned_total / sample_size
                avg_actual = actual_total / sample_size
                avg_loss = avg_planned - avg_actual
                avg_loss_pct = (avg_loss / avg_planned * 100) if avg_planned > 0 else 0

                results[step_name] = {
                    "avg_planned": round(avg_planned, 2),
                    "avg_actual": round(avg_actual, 2),
                    "avg_loss": round(avg_loss, 2),
                    "avg_loss_pct": round(avg_loss_pct, 2),
                    "sample_size": sample_size,
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
        Calculate efficiency for a user.

        Args:
            user: User to analyze
            step_name: Specific step to filter (optional)
            date_from: Start date filter (optional)

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

        # Calculate overall efficiency
        total_planned = Decimal("0")
        total_actual = Decimal("0")

        for wo in qs:
            total_planned += wo.quantity
            if wo.actual_quantity:
                total_actual += wo.actual_quantity

        total_orders = qs.count()

        if total_planned > 0:
            efficiency = (total_actual / total_planned) * 100
            avg_loss_pct = 100 - float(efficiency)
        else:
            efficiency = 100
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
        Calculate throughput for a workstation.

        Args:
            location: Position (workstation) to analyze
            date_from: Start date filter (optional)
            date_to: End date filter (optional)

        Returns:
            {
                'location': 'Forno 1',
                'total_orders': 42,
                'total_quantity': 2100,
                'avg_duration_minutes': 180,
                'utilization_pct': 75.5
            }
        """
        qs = WorkOrder.objects.filter(
            location=location, status=WorkOrderStatus.COMPLETED
        )

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        # Calculate metrics
        total_orders = qs.count()
        total_quantity = sum(wo.actual_quantity or wo.quantity for wo in qs)

        # Calculate average duration
        durations = []
        for wo in qs:
            if wo.actual_start and wo.actual_end:
                duration = (wo.actual_end - wo.actual_start).total_seconds() / 60
                durations.append(duration)

        avg_duration = sum(durations) / len(durations) if durations else 0

        # TODO: Calculate utilization based on capacity
        utilization_pct = 0
        if location and location.metadata.get("capacity_per_hour"):
            # Basic utilization calculation
            pass

        return {
            "location": str(location) if location else "Unknown",
            "total_orders": total_orders,
            "total_quantity": float(total_quantity),
            "avg_duration_minutes": round(avg_duration, 1),
            "utilization_pct": utilization_pct,
        }

    @classmethod
    def summary(cls, date_from: date = None, date_to: date = None) -> dict[str, Any]:
        """
        Get overall production summary.

        Args:
            date_from: Start date filter (optional)
            date_to: End date filter (optional)

        Returns:
            {
                'total_orders': 150,
                'completed_orders': 120,
                'pending_orders': 20,
                'in_progress_orders': 10,
                'total_planned': 5000,
                'total_produced': 4800,
                'overall_efficiency': 96.0,
            }
        """
        qs = WorkOrder.objects.all()

        if date_from:
            qs = qs.filter(scheduled_start__date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_start__date__lte=date_to)

        total_orders = qs.count()
        completed = qs.filter(status=WorkOrderStatus.COMPLETED)
        pending = qs.filter(status=WorkOrderStatus.PENDING)
        in_progress = qs.filter(status=WorkOrderStatus.IN_PROGRESS)

        total_planned = sum(wo.quantity for wo in completed)
        total_produced = sum(wo.actual_quantity or 0 for wo in completed)

        efficiency = (
            (total_produced / total_planned * 100) if total_planned > 0 else 100
        )

        return {
            "total_orders": total_orders,
            "completed_orders": completed.count(),
            "pending_orders": pending.count(),
            "in_progress_orders": in_progress.count(),
            "total_planned": float(total_planned),
            "total_produced": float(total_produced),
            "overall_efficiency": round(float(efficiency), 2),
        }

