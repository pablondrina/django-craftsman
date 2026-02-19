"""
Craftsman Exceptions.

All craftsman errors are wrapped in CraftError for consistent handling.
"""

from typing import Any


class CraftError(Exception):
    """
    Base exception for all Craftsman errors.

    Usage:
        raise CraftError('INVALID_STATUS', current='pending', expected='in_progress')

    Attributes:
        code: Error code (INVALID_STATUS, INSUFFICIENT_MATERIALS, etc.)
        details: Additional context as keyword arguments
    """

    def __init__(self, code: str, **details: Any):
        self.code = code
        self.details = details
        message = f"{code}: {details}" if details else code
        super().__init__(message)

    def as_dict(self) -> dict:
        """Return error as dictionary for API responses."""
        return {"code": self.code, **self.details}

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"CraftError({self.code}: {details_str})"
        return f"CraftError({self.code})"


# Common error codes
# INVALID_STATUS: Status transition not allowed
# INVALID_STEP: Step name not defined in recipe
# STEP_DEPENDENCIES_NOT_MET: Required steps not completed
# STEP_ALREADY_COMPLETED: Step already registered
# INSUFFICIENT_MATERIALS: Not enough materials (from Stockman)
# WORK_ORDER_NOT_FOUND: WorkOrder does not exist
# RECIPE_NOT_FOUND: Recipe does not exist

