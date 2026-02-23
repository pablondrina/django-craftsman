"""
Stockman Backend.

Implements StockBackend using Stockman's API (stock.*).

Vocabulary mapping:
    Craftsman           →  Stockman
    ─────────────────────────────────
    available()         →  stock.available()
    reserve()           →  stock.hold()
    consume()           →  stock.fulfill()
    release()           →  stock.release()
    receive()           →  stock.receive()
"""

import logging
import threading
from decimal import Decimal
from typing import Any, Callable

from django.db import transaction

from craftsman.protocols.stock import (
    AvailabilityResult,
    ConsumeResult,
    MaterialAdjustment,
    MaterialHold,
    MaterialNeed,
    MaterialStatus,
    MaterialUsed,
    ReceiveResult,
    ReleaseResult,
    ReserveResult,
)

logger = logging.getLogger(__name__)


def _stockman_available() -> bool:
    """Check if Stockman is available."""
    try:
        from stockman.service import stock

        return True
    except ImportError:
        return False


class StockmanBackend:
    """
    Implementação do StockBackend usando a API do Stockman.

    Exemplo de uso:
        from craftsman.adapters import get_stock_backend

        backend = get_stock_backend()
        result = backend.available([
            MaterialNeed(sku="FARINHA", quantity=Decimal("10")),
        ])
    """

    def __init__(self, product_resolver: Callable[[str], Any] | None = None):
        """
        Args:
            product_resolver: Função que resolve SKU → produto (model).
                             Se não fornecido, usa resolver padrão.
        """
        self._product_resolver = product_resolver

    def _get_product(self, sku: str):
        """Resolve SKU to product."""
        if self._product_resolver:
            return self._product_resolver(sku)

        # Use ProductInfoBackend if configured
        try:
            from craftsman.adapters.offerman import get_product_info_backend

            backend = get_product_info_backend()
            info = backend.get_product_info(sku)
            if info:
                return info
        except Exception:
            pass

        logger.warning("Could not resolve product for SKU: %s", sku)
        return None

    def _get_stock(self):
        """Get Stockman service."""
        from stockman.service import stock

        return stock

    def _get_position(self, code: str | None):
        """Get Position by code."""
        if not code:
            return None

        try:
            from stockman.models import Position

            return Position.objects.filter(code=code).first()
        except ImportError:
            return None

    def available(self, materials: list[MaterialNeed]) -> AvailabilityResult:
        """Verifica disponibilidade usando stock.available()."""
        if not _stockman_available():
            # Sem Stockman, assume tudo disponível
            return AvailabilityResult(
                all_available=True,
                materials=[
                    MaterialStatus(
                        sku=mat.sku,
                        needed=mat.quantity,
                        available=mat.quantity,
                    )
                    for mat in materials
                ],
            )

        stock = self._get_stock()
        items = []
        all_available = True

        for mat in materials:
            product = self._get_product(mat.sku)
            if not product:
                items.append(
                    MaterialStatus(
                        sku=mat.sku,
                        needed=mat.quantity,
                        available=Decimal("0"),
                    )
                )
                all_available = False
                continue

            avail = stock.available(product)
            is_sufficient = avail >= mat.quantity

            if not is_sufficient:
                all_available = False

            items.append(
                MaterialStatus(
                    sku=mat.sku,
                    needed=mat.quantity,
                    available=avail,
                )
            )

        return AvailabilityResult(
            all_available=all_available,
            materials=items,
        )

    @transaction.atomic
    def reserve(
        self,
        materials: list[MaterialNeed],
        work_order_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReserveResult:
        """Reserva materiais usando stock.hold()."""
        if not _stockman_available():
            # Sem Stockman, simula sucesso
            return ReserveResult(
                success=True,
                holds=[
                    MaterialHold(sku=mat.sku, quantity=mat.quantity, hold_id="mock:0")
                    for mat in materials
                ],
            )

        stock = self._get_stock()
        holds = []
        failed_items = []

        for mat in materials:
            product = self._get_product(mat.sku)
            if not product:
                failed_items.append(
                    MaterialStatus(
                        sku=mat.sku,
                        needed=mat.quantity,
                        available=Decimal("0"),
                    )
                )
                continue

            # Verificar disponibilidade
            avail = stock.available(product)
            if avail < mat.quantity:
                failed_items.append(
                    MaterialStatus(
                        sku=mat.sku,
                        needed=mat.quantity,
                        available=avail,
                    )
                )
                continue

            # Criar hold
            try:
                from datetime import date

                hold_id = stock.hold(
                    quantity=mat.quantity,
                    product=product,
                    target_date=date.today(),
                    metadata={
                        "work_order_id": work_order_id,
                        "reference_type": "craftsman.workorder",
                        **(metadata or {}),
                    },
                )

                holds.append(
                    MaterialHold(
                        sku=mat.sku,
                        quantity=mat.quantity,
                        hold_id=hold_id,
                    )
                )

            except Exception as e:
                logger.error(f"Failed to create hold for {mat.sku}: {e}")
                failed_items.append(
                    MaterialStatus(
                        sku=mat.sku,
                        needed=mat.quantity,
                        available=avail,
                    )
                )

        # Se houve falhas, libera holds já criados (rollback)
        if failed_items:
            for hold in holds:
                try:
                    stock.release(hold.hold_id, reason="rollback")
                except Exception as e:
                    logger.error(f"Failed to release hold {hold.hold_id}: {e}")

            return ReserveResult(
                success=False,
                holds=[],
                failed=failed_items,
                message="Estoque insuficiente para alguns materiais",
            )

        return ReserveResult(
            success=True,
            holds=holds,
            failed=[],
        )

    @transaction.atomic
    def consume(
        self,
        work_order_id: str,
        actual: list[MaterialUsed] | None = None,
    ) -> ConsumeResult:
        """Consome materiais reservados usando stock.fulfill()."""
        if not _stockman_available():
            return ConsumeResult(success=True)

        stock = self._get_stock()

        # Buscar holds para este work_order
        try:
            from stockman.models import Hold, HoldStatus

            holds = Hold.objects.filter(
                metadata__work_order_id=work_order_id,
                status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED],
            )
        except ImportError:
            return ConsumeResult(
                success=False, message="Stockman not available"
            )

        consumed = []
        adjustments = []

        for hold in holds:
            # Determinar quantidade a consumir
            sku = getattr(hold.product, "sku", str(hold.product))

            if actual:
                actual_item = next(
                    (c for c in actual if c.sku == sku),
                    None,
                )
                consume_qty = actual_item.quantity if actual_item else hold.quantity
            else:
                consume_qty = hold.quantity

            # Fulfill usando API do Stockman
            try:
                stock.fulfill(hold.hold_id, qty=consume_qty)

                consumed.append(
                    MaterialUsed(
                        sku=sku,
                        quantity=consume_qty,
                    )
                )

                # Registrar ajuste se diferente
                if consume_qty != hold.quantity:
                    adjustments.append(
                        MaterialAdjustment(
                            sku=sku,
                            reserved=hold.quantity,
                            consumed=consume_qty,
                        )
                    )

            except Exception as e:
                logger.error(f"Failed to fulfill hold {hold.hold_id}: {e}")
                return ConsumeResult(
                    success=False,
                    consumed=consumed,
                    message=f"Falha ao consumir {sku}: {e}",
                )

        return ConsumeResult(
            success=True,
            consumed=consumed,
            adjustments=adjustments,
        )

    @transaction.atomic
    def release(
        self,
        work_order_id: str,
        reason: str = "cancelled",
    ) -> ReleaseResult:
        """Libera materiais reservados usando stock.release()."""
        if not _stockman_available():
            return ReleaseResult(success=True)

        stock = self._get_stock()

        try:
            from stockman.models import Hold, HoldStatus

            holds = Hold.objects.filter(
                metadata__work_order_id=work_order_id,
                status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED],
            )
        except ImportError:
            return ReleaseResult(
                success=False, message="Stockman not available"
            )

        released = []
        failed = []
        for hold in holds:
            try:
                sku = getattr(hold.product, "sku", str(hold.product))
                stock.release(hold.hold_id, reason=reason)
                released.append(
                    MaterialHold(
                        sku=sku,
                        quantity=hold.quantity,
                        hold_id=hold.hold_id,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to release hold {hold.hold_id}: {e}")
                failed.append(hold.hold_id)

        success = len(failed) == 0
        return ReleaseResult(
            success=success,
            released=released,
            message=f"Failed to release holds: {failed}" if failed else None,
        )

    @transaction.atomic
    def receive(
        self,
        product_sku: str,
        quantity: Decimal,
        work_order_id: str,
        position_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReceiveResult:
        """Registra output de produção usando stock.receive()."""
        if not _stockman_available():
            return ReceiveResult(success=True, quant_id="mock:0")

        stock = self._get_stock()
        product = self._get_product(product_sku)

        if not product:
            return ReceiveResult(
                success=False,
                message=f"Produto não encontrado: {product_sku}",
            )

        position = self._get_position(position_code)

        try:
            quant = stock.receive(
                quantity=quantity,
                product=product,
                position=position,
                reference=work_order_id,
                metadata={
                    "work_order_id": work_order_id,
                    "source": "craftsman",
                    **(metadata or {}),
                },
            )

            return ReceiveResult(
                success=True,
                quant_id=f"quant:{quant.pk}",
            )

        except Exception as e:
            logger.error(f"Failed to register output for {product_sku}: {e}")
            return ReceiveResult(
                success=False,
                message=f"Falha ao registrar saída: {e}",
            )


# ══════════════════════════════════════════════════════════════
# Factory function
# ══════════════════════════════════════════════════════════════


_lock = threading.Lock()
_backend_instance: StockmanBackend | None = None


def get_stock_backend(
    product_resolver: Callable[[str], Any] | None = None,
) -> StockmanBackend:
    """
    Get or create the stock backend instance.

    Args:
        product_resolver: Optional custom product resolver

    Returns:
        StockmanBackend instance
    """
    global _backend_instance

    if product_resolver:
        # Se passou resolver customizado, cria nova instância
        return StockmanBackend(product_resolver=product_resolver)

    if _backend_instance is None:
        with _lock:
            if _backend_instance is None:  # double-checked
                _backend_instance = StockmanBackend()

    return _backend_instance


def reset_stock_backend() -> None:
    """Reset singleton (for tests)."""
    global _backend_instance
    _backend_instance = None
