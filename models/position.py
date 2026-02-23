"""
Craftsman Position model.

Minimal swappable position model for standalone usage.

Users with an external position system (e.g. stockman) should set:
    CRAFTSMAN_POSITION_MODEL = "stockman.Position"
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Position(models.Model):
    """
    Minimal position model.

    Represents a physical location (workstation, storage, delivery point).
    Swappable via CRAFTSMAN_POSITION_MODEL setting.
    """

    code = models.SlugField(
        unique=True,
        max_length=50,
        verbose_name=_("Código"),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("Nome"),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadados"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("criado em"))

    class Meta:
        db_table = "craftsman_position"
        verbose_name = _("Posição")
        verbose_name_plural = _("Posições")
        swappable = "CRAFTSMAN_POSITION_MODEL"

    def __str__(self) -> str:
        return self.name
