"""
Craftsman Service (v2.4) - Thin facade over focused service modules.

Implementation is split into modules under craftsman/services/:
    scheduling.py  -- plan, approve, schedule, create, create_batch, queries
    execution.py   -- start, complete, pause, resume, cancel

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
"""

from craftsman.services.execution import CraftExecution
from craftsman.services.scheduling import CraftScheduling


class Craft(CraftScheduling, CraftExecution):
    """
    Single interface for all Craftsman operations.

    Follows Stockman's mixin pattern:
        Stock = StockQueries + StockMovements + StockHolds + StockPlanning
        Craft = CraftScheduling + CraftExecution

    Business logic lives in the models (SIREL principle).
    This class is a thin facade for convenience and discoverability.
    """
