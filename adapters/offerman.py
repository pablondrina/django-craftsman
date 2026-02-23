"""
Craftsman Offerman Adapter — Product information via Offerman.

This adapter loads the configured ProductInfoBackend from settings.

Usage:
    from craftsman.adapters import get_product_info_backend

    backend = get_product_info_backend()
    info = backend.get_product_info("SKU-001")

Settings:
    CRAFTSMAN = {
        "PRODUCT_INFO_BACKEND": "offerman.adapters.product_info.OffermanProductInfoBackend",
    }

If PRODUCT_INFO_BACKEND is not configured, get_product_info_backend() raises ImproperlyConfigured.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from craftsman.protocols.product import ProductInfoBackend

if TYPE_CHECKING:
    from craftsman.protocols.product import ProductInfo, SkuValidationResult

logger = logging.getLogger(__name__)


# Cached backend instance
_lock = threading.Lock()
_product_info_backend: ProductInfoBackend | None = None


def get_product_info_backend() -> ProductInfoBackend:
    """
    Return the configured product info backend.

    Returns:
        ProductInfoBackend instance

    Raises:
        ImproperlyConfigured: If PRODUCT_INFO_BACKEND is not configured or import fails
    """
    global _product_info_backend

    if _product_info_backend is None:
        with _lock:
            if _product_info_backend is None:  # double-checked
                craftsman_settings = getattr(settings, "CRAFTSMAN", {})
                backend_path = craftsman_settings.get("PRODUCT_INFO_BACKEND")

                if not backend_path:
                    raise ImproperlyConfigured(
                        "CRAFTSMAN['PRODUCT_INFO_BACKEND'] must be configured. "
                        "Example: 'offerman.adapters.product_info.OffermanProductInfoBackend'"
                    )

                try:
                    backend_class = import_string(backend_path)
                    _product_info_backend = backend_class()
                    logger.debug("Loaded product info backend: %s", backend_path)
                except ImportError as e:
                    raise ImproperlyConfigured(
                        f"Failed to import product info backend '{backend_path}': {e}"
                    ) from e

    return _product_info_backend


def reset_product_info_backend() -> None:
    """Reset the cached backend. Useful for testing."""
    global _product_info_backend
    _product_info_backend = None
