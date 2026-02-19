"""
Craftsman Models.

Core models for production management:
- Recipe: Bill of Materials (BOM) - defines HOW to make something
- RecipeItem: Insumo da receita (método do coeficiente francês)
- IngredientCategory: Categoria de insumos para agrupamento
- Plan: MPS (Master Production Schedule) - daily production plan
- PlanItem: Individual item in the plan (1 product)
- WorkOrder: Atomic unit of production work with step tracking
"""

from craftsman.models.plan import Plan, PlanItem, PlanStatus
from craftsman.models.recipe import IngredientCategory, Recipe, RecipeInput, RecipeItem
from craftsman.models.work_order import WorkOrder, WorkOrderStatus

__all__ = [
    "Recipe",
    "RecipeItem",
    "RecipeInput",  # Alias for backward compatibility
    "IngredientCategory",
    "Plan",
    "PlanItem",
    "PlanStatus",
    "WorkOrder",
    "WorkOrderStatus",
]
