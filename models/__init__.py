"""
Craftsman Models.

Core models for production management:
- Position: Swappable position model (CRAFTSMAN_POSITION_MODEL)
- Recipe: Bill of Materials (BOM) - defines HOW to make something
- RecipeItem: Insumo da receita (método do coeficiente francês)
- IngredientCategory: Categoria de insumos para agrupamento
- Plan: MPS (Master Production Schedule) - daily production plan
- PlanItem: Individual item in the plan (1 product)
- WorkOrder: Atomic unit of production work with step tracking
"""

from craftsman.models.plan import Plan, PlanItem, PlanStatus
from craftsman.models.position import Position
from craftsman.models.recipe import IngredientCategory, Recipe, RecipeItem
from craftsman.models.sequence import CodeSequence
from craftsman.models.work_order import WorkOrder, WorkOrderStatus

__all__ = [
    "Position",
    "Recipe",
    "RecipeItem",
    "IngredientCategory",
    "Plan",
    "PlanItem",
    "PlanStatus",
    "WorkOrder",
    "WorkOrderStatus",
    "CodeSequence",
]


