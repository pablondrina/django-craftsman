"""
Django Craftsman app configuration.
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CraftsmanConfig(AppConfig):
    """Craftsman application configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "craftsman"
    verbose_name = _("Produção")

    def ready(self):
        """Import signal handlers when app is ready."""
        # Import handlers to register them
        from craftsman.signals import handlers  # noqa: F401
