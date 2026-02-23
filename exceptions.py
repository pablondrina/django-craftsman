"""
Craftsman Exceptions.

All craftsman errors are wrapped in CraftError for consistent handling.
"""

from commons.exceptions import BaseError


class CraftError(BaseError):
    """
    Base exception for all Craftsman errors.

    Usage:
        raise CraftError('INVALID_STATUS', current='pending', expected='in_progress')

    Attributes:
        code: Error code (INVALID_STATUS, INSUFFICIENT_MATERIALS, etc.)
        message: Human-readable description
        data: Additional context as keyword arguments
    """

    _default_messages = {
        "INVALID_STATUS": "Status transition not allowed",
        "INVALID_STEP": "Step not defined in recipe",
        "INSUFFICIENT_MATERIALS": "Not enough materials",
        "WORK_ORDER_NOT_FOUND": "Work order not found",
        "RECIPE_NOT_FOUND": "Recipe not found",
        "STEP_ALREADY_COMPLETED": "Step already registered",
        "STEP_DEPENDENCIES_NOT_MET": "Required steps not completed",
        "INVALID_QUANTITY": "Invalid quantity",
        "PLAN_NOT_FOUND": "Plan not found",
        "PLAN_NOT_FOUND_OR_NOT_APPROVED": "Plan not found or not approved",
        "RESERVATION_FAILED": "Material reservation failed",
        "MATERIAL_CONSUMPTION_FAILED": "Material consumption failed",
    }
