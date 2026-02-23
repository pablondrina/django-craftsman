"""
Craftsman Settings.

Supports two formats (dict takes priority):

    # Option 1: Dict
    CRAFTSMAN = {
        "POSITION_MODEL": "stockman.Position",
        "RESERVE_INPUTS": True,
    }

    # Option 2: Flat
    CRAFTSMAN_POSITION_MODEL = "stockman.Position"
    CRAFTSMAN_RESERVE_INPUTS = True

All settings have sensible defaults — zero configuration required.
"""

import threading
from decimal import Decimal

from django.conf import settings


# ── Defaults ──

DEFAULTS = {
    "POSITION_MODEL": "craftsman.Position",
    "RESERVE_INPUTS": False,
    "SAFETY_STOCK_PERCENT": Decimal("0.20"),
    "HISTORICAL_DAYS": 28,
    "SAME_WEEKDAY_ONLY": True,
    "DEMAND_BACKEND": None,
    "STOCK_BACKEND": None,
    "PRODUCT_INFO_BACKEND": None,
}


# ── Accessors ──

_sentinel = object()


def get_setting(name, default=_sentinel):
    """
    Get a craftsman setting.

    Looks up in order:
    1. CRAFTSMAN dict (e.g. CRAFTSMAN = {"POSITION_MODEL": "..."})
    2. Flat setting (e.g. CRAFTSMAN_POSITION_MODEL = "...")
    3. DEFAULTS
    """
    craftsman_dict = getattr(settings, "CRAFTSMAN", {})
    if name in craftsman_dict:
        return craftsman_dict[name]

    flat_value = getattr(settings, f"CRAFTSMAN_{name}", _sentinel)
    if flat_value is not _sentinel:
        return flat_value

    if default is not _sentinel:
        return default

    return DEFAULTS.get(name)


def get_position_model_string():
    """Return the string reference for the position model."""
    return get_setting("POSITION_MODEL", DEFAULTS["POSITION_MODEL"])


def get_position_model():
    """Return the position model class."""
    from django.apps import apps

    return apps.get_model(get_position_model_string())


_demand_backend_lock = threading.Lock()
_demand_backend_instance = None


def get_demand_backend():
    """
    Return the configured demand backend instance, or None.

    The demand backend provides committed quantities (holds/reservations)
    for production planning.
    """
    global _demand_backend_instance

    path = get_setting("DEMAND_BACKEND")
    if not path:
        return None

    if _demand_backend_instance is None:
        with _demand_backend_lock:
            if _demand_backend_instance is None:  # double-checked
                from django.utils.module_loading import import_string

                _demand_backend_instance = import_string(path)()

    return _demand_backend_instance


def reset_demand_backend() -> None:
    """Reset singleton (for tests)."""
    global _demand_backend_instance
    _demand_backend_instance = None
