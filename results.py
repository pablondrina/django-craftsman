"""
Craftsman Result Types.

Structured results for production scheduling operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from craftsman.models import WorkOrder


@dataclass
class InputShortage:
    """Informação sobre insumo insuficiente."""

    sku: str
    required: Decimal
    available: Decimal

    @property
    def shortage(self) -> Decimal:
        return self.required - self.available


@dataclass
class ScheduleResult:
    """
    Resultado do agendamento de produção.

    Se success=True: work_orders contém as ordens criadas
    Se success=False: errors contém os insumos faltantes
    """

    success: bool
    work_orders: list[WorkOrder] = field(default_factory=list)
    errors: list[InputShortage] = field(default_factory=list)
    message: str | None = None

    @property
    def has_shortages(self) -> bool:
        return len(self.errors) > 0
