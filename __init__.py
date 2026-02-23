"""
Django Craftsman - Headless Micro-MRP Framework.

A simple, robust, elegant production management system.

Usage:
    from craftsman import craft, CraftError

    # Planning
    item = craft.plan(50, croissant, date(2025, 1, 24), vitrine)
    craft.approve(date(2025, 1, 24))
    result = craft.schedule(date(2025, 1, 24))

    if result.success:
        for wo in result.work_orders:
            print(f"Created: {wo.code}")
    else:
        for error in result.errors:
            print(f"Falta: {error.sku} - precisa {error.required}, tem {error.available}")

    # Execution (directly on model - SIREL!)
    wo.step("Mixing", 70, user=operador)
    wo.step("Shaping", 74, user=operador)
    wo.step("Baking", 72, user=operador)  # Auto-completes!

Philosophy: SIREL (Simples, Robusto, Elegante)
"""

from craftsman.exceptions import CraftError


def __getattr__(name):
    """Lazy import to avoid AppRegistryNotReady errors."""
    if name in ("craft", "Craft"):
        from craftsman.service import Craft

        return Craft
    if name == "ScheduleResult":
        from craftsman.results import ScheduleResult

        return ScheduleResult
    if name == "InputShortage":
        from craftsman.results import InputShortage

        return InputShortage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["craft", "Craft", "CraftError", "ScheduleResult", "InputShortage"]
__version__ = "0.1.0"

