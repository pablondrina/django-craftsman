"""
Craftsman API ViewSets.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from craftsman.models import Recipe, Plan, WorkOrder
from .serializers import (
    RecipeSerializer,
    PlanSerializer,
    WorkOrderSerializer,
    WorkOrderStepSerializer,
    WorkOrderCompleteSerializer,
)


class RecipeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Recipe (read-only).

    list: List all active recipes
    retrieve: Get a specific recipe by UUID
    """

    permission_classes = [IsAuthenticated]
    queryset = Recipe.objects.filter(is_active=True)
    serializer_class = RecipeSerializer
    lookup_field = "uuid"


class PlanViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Plan.

    list: List all plans
    create: Create a new plan
    retrieve: Get a specific plan
    update: Update a plan
    destroy: Delete a plan
    approve: Approve a draft plan
    schedule: Schedule an approved plan (creates WorkOrders)
    """

    permission_classes = [IsAuthenticated]
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Approve a draft plan.

        POST /api/craftsman/plans/{pk}/approve/
        """
        plan = self.get_object()
        try:
            plan.approve(user=request.user)
            return Response(
                {
                    "status": "approved",
                    "date": plan.date,
                    "approved_at": plan.approved_at,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """
        Schedule an approved plan (creates WorkOrders).

        POST /api/craftsman/plans/{pk}/schedule/
        """
        plan = self.get_object()
        try:
            work_orders = plan.schedule(user=request.user)
            return Response(
                {
                    "status": "scheduled",
                    "work_orders_created": len(work_orders),
                    "work_order_codes": [wo.code for wo in work_orders],
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class WorkOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for WorkOrder.

    list: List all work orders
    create: Create a new work order
    retrieve: Get a specific work order by UUID
    update: Update a work order
    destroy: Delete a work order
    step: Record a production step
    complete: Complete the work order
    """

    permission_classes = [IsAuthenticated]
    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    lookup_field = "uuid"

    @action(detail=True, methods=["post"])
    def step(self, request, uuid=None):
        """
        Record a production step.

        POST /api/craftsman/work-orders/{uuid}/step/
        {
            "step": "Mixing",
            "quantity": 70
        }
        """
        wo = self.get_object()
        serializer = WorkOrderStepSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            wo.step(
                step_name=serializer.validated_data["step"],
                quantity=serializer.validated_data["quantity"],
                user=request.user,
            )
            return Response(
                {
                    "status": wo.status,
                    "progress": wo.progress,
                    "step_log": wo.step_log,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def complete(self, request, uuid=None):
        """
        Complete the work order.

        POST /api/craftsman/work-orders/{uuid}/complete/
        {
            "actual_quantity": 68  // optional
        }
        """
        wo = self.get_object()
        serializer = WorkOrderCompleteSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            actual_quantity = serializer.validated_data.get("actual_quantity")
            wo.complete(actual_quantity=actual_quantity, user=request.user)
            return Response(
                {
                    "status": wo.status,
                    "actual_quantity": float(wo.actual_quantity),
                    "completed_at": wo.completed_at,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def pause(self, request, uuid=None):
        """
        Pause the work order.

        POST /api/craftsman/work-orders/{uuid}/pause/
        {
            "reason": "Equipamento quebrado"  // optional
        }
        """
        wo = self.get_object()
        reason = request.data.get("reason", "")

        try:
            wo.pause(reason=reason, user=request.user)
            return Response({"status": wo.status})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def resume(self, request, uuid=None):
        """
        Resume a paused work order.

        POST /api/craftsman/work-orders/{uuid}/resume/
        """
        wo = self.get_object()

        try:
            wo.resume(user=request.user)
            return Response({"status": wo.status})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def cancel(self, request, uuid=None):
        """
        Cancel the work order.

        POST /api/craftsman/work-orders/{uuid}/cancel/
        {
            "reason": "Pedido cancelado"  // optional
        }
        """
        wo = self.get_object()
        reason = request.data.get("reason", "")

        try:
            wo.cancel(reason=reason, user=request.user)
            return Response({"status": wo.status})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
