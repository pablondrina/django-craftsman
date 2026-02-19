"""
Stock Backend Protocol.

Defines the interface for Craftsman to interact with stock systems
(e.g., Stockman) for material reservation and consumption.

Vocabulary mapping (Craftsman → Stockman):
    available()  →  stock.available()
    reserve()    →  stock.hold()
    consume()    →  stock.fulfill()
    release()    →  stock.release()
    receive()    →  stock.receive()
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


# ══════════════════════════════════════════════════════════════
# DATA TYPES
# ══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MaterialNeed:
    """Material necessário para produção."""

    sku: str
    quantity: Decimal
    unit: str = "kg"
    position_code: str | None = None


@dataclass(frozen=True)
class MaterialUsed:
    """Material efetivamente consumido."""

    sku: str
    quantity: Decimal


@dataclass(frozen=True)
class MaterialStatus:
    """Status de disponibilidade de um material."""

    sku: str
    needed: Decimal
    available: Decimal

    @property
    def sufficient(self) -> bool:
        return self.available >= self.needed

    @property
    def shortage(self) -> Decimal:
        return max(Decimal("0"), self.needed - self.available)


@dataclass(frozen=True)
class AvailabilityResult:
    """Resultado de verificação de disponibilidade."""

    all_available: bool
    materials: list[MaterialStatus] = field(default_factory=list)


@dataclass(frozen=True)
class MaterialHold:
    """Reserva de material."""

    sku: str
    quantity: Decimal
    hold_id: str  # Formato: "hold:{pk}" (convenção Stockman)


@dataclass(frozen=True)
class ReserveResult:
    """Resultado de reserva de materiais."""

    success: bool
    holds: list[MaterialHold] = field(default_factory=list)
    failed: list[MaterialStatus] = field(default_factory=list)
    message: str | None = None


@dataclass(frozen=True)
class MaterialAdjustment:
    """Ajuste entre reservado e consumido."""

    sku: str
    reserved: Decimal
    consumed: Decimal

    @property
    def delta(self) -> Decimal:
        """Positivo = usou mais, negativo = sobrou."""
        return self.consumed - self.reserved


@dataclass(frozen=True)
class ConsumeResult:
    """Resultado de consumo de materiais."""

    success: bool
    consumed: list[MaterialUsed] = field(default_factory=list)
    adjustments: list[MaterialAdjustment] = field(default_factory=list)
    message: str | None = None


@dataclass(frozen=True)
class ReleaseResult:
    """Resultado de liberação de materiais."""

    success: bool
    released: list[MaterialHold] = field(default_factory=list)
    message: str | None = None


@dataclass(frozen=True)
class ReceiveResult:
    """Resultado de recebimento de produção."""

    success: bool
    quant_id: str | None = None  # Formato: "quant:{pk}"
    message: str | None = None


# ══════════════════════════════════════════════════════════════
# PROTOCOL
# ══════════════════════════════════════════════════════════════


@runtime_checkable
class StockBackend(Protocol):
    """
    Interface para Craftsman acessar estoque de materiais.

    Este protocol define como o Craftsman interage com o sistema de estoque
    para reservar, consumir e liberar materiais durante o ciclo de produção.

    Implementações:
        - StockmanBackend: Usa a API do Stockman (stock.*)
        - MockStockBackend: Para testes sem estoque real
    """

    def available(self, materials: list[MaterialNeed]) -> AvailabilityResult:
        """
        Verifica disponibilidade de materiais.

        Args:
            materials: Lista de materiais necessários

        Returns:
            Resultado com disponibilidade de cada material
        """
        ...

    def reserve(
        self,
        materials: list[MaterialNeed],
        work_order_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReserveResult:
        """
        Reserva materiais para uma ordem de produção.

        Mapeia para: stock.hold() no Stockman

        Args:
            materials: Lista de materiais a reservar
            work_order_id: UUID da WorkOrder
            metadata: Dados extras (opcional)

        Returns:
            Resultado com reservas criadas ou falhas
        """
        ...

    def consume(
        self,
        work_order_id: str,
        actual: list[MaterialUsed] | None = None,
    ) -> ConsumeResult:
        """
        Consome materiais reservados (baixa definitiva).

        Mapeia para: stock.fulfill() no Stockman

        Se `actual` não for fornecido, consome o total reservado.
        Se fornecido, pode haver ajustes (usou mais ou menos).

        Args:
            work_order_id: UUID da WorkOrder
            actual: Consumo real (opcional, para ajustes)

        Returns:
            Resultado do consumo
        """
        ...

    def release(
        self,
        work_order_id: str,
        reason: str = "cancelled",
    ) -> ReleaseResult:
        """
        Libera materiais reservados (produção cancelada).

        Mapeia para: stock.release() no Stockman

        Args:
            work_order_id: UUID da WorkOrder
            reason: Motivo da liberação

        Returns:
            Resultado da liberação
        """
        ...

    def receive(
        self,
        product_sku: str,
        quantity: Decimal,
        work_order_id: str,
        position_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReceiveResult:
        """
        Recebe produção no estoque.

        Mapeia para: stock.receive() no Stockman

        Args:
            product_sku: SKU do produto acabado
            quantity: Quantidade produzida
            work_order_id: UUID da WorkOrder
            position_code: Código da posição destino
            metadata: Dados extras (batch, validade, etc.)

        Returns:
            Resultado do recebimento
        """
        ...
