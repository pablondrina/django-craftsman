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
        """App ready hook. Signal handlers registered by contrib apps."""
        pass
