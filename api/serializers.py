"""
Craftsman API Serializers.
"""

from rest_framework import serializers

from craftsman.models import Recipe, Plan, PlanItem, WorkOrder


class RecipeSerializer(serializers.ModelSerializer):
    """Serializer for Recipe model."""

    class Meta:
        model = Recipe
        fields = [
            "uuid",
            "code",
            "name",
            "output_quantity",
            "lead_time_days",
            "steps",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uuid", "created_at", "updated_at"]


class PlanItemSerializer(serializers.ModelSerializer):
    """Serializer for PlanItem model."""

    recipe_code = serializers.CharField(source="recipe.code", read_only=True)
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)
    product_name = serializers.SerializerMethodField()

    class Meta:
        model = PlanItem
        fields = [
            "id",
            "uuid",
            "recipe",
            "recipe_code",
            "recipe_name",
            "product_name",
            "quantity",
            "priority",
            "destination",
            "notes",
            "total_produced",
            "is_complete",
        ]
        read_only_fields = [
            "uuid",
            "recipe_code",
            "recipe_name",
            "product_name",
            "total_produced",
            "is_complete",
        ]

    def get_product_name(self, obj) -> str:
        return obj.product_name


class PlanSerializer(serializers.ModelSerializer):
    """Serializer for Plan model."""

    items = PlanItemSerializer(many=True, read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    total_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=0, read_only=True
    )

    class Meta:
        model = Plan
        fields = [
            "id",
            "uuid",
            "date",
            "status",
            "notes",
            "items",
            "total_items",
            "total_quantity",
            "created_at",
            "approved_at",
            "scheduled_at",
            "completed_at",
        ]
        read_only_fields = [
            "uuid",
            "status",
            "items",
            "total_items",
            "total_quantity",
            "created_at",
            "approved_at",
            "scheduled_at",
            "completed_at",
        ]


class WorkOrderSerializer(serializers.ModelSerializer):
    """Serializer for WorkOrder model."""

    recipe_code = serializers.CharField(source="recipe.code", read_only=True)
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)
    progress = serializers.DictField(read_only=True)
    step_log = serializers.ListField(read_only=True)
    production_date = serializers.DateField(read_only=True)

    class Meta:
        model = WorkOrder
        fields = [
            "uuid",
            "code",
            "recipe",
            "recipe_code",
            "recipe_name",
            "planned_quantity",
            "actual_quantity",
            "status",
            "progress",
            "step_log",
            "scheduled_start",
            "scheduled_end",
            "started_at",
            "completed_at",
            "destination",
            "location",
            "production_date",
            "process_quantity",
            "output_quantity",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uuid",
            "code",
            "recipe_code",
            "recipe_name",
            "progress",
            "step_log",
            "started_at",
            "completed_at",
            "production_date",
            "created_at",
            "updated_at",
        ]


class WorkOrderStepSerializer(serializers.Serializer):
    """Serializer for WorkOrder step action."""

    step = serializers.CharField(required=True, help_text="Step name (e.g., 'Mixing')")
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=0, required=True, help_text="Quantity produced"
    )


class WorkOrderCompleteSerializer(serializers.Serializer):
    """Serializer for WorkOrder complete action."""

    actual_quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=0,
        required=False,
        help_text="Actual quantity (optional, defaults to last step quantity)",
    )
