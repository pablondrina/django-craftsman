"""
Craftsman Signals.

All communication with external systems happens via signals.
This ensures decoupling and allows for easy testing.

Signals:
    materials_needed: Production started, need to consume materials
    production_completed: Production finished, need to receive product
    order_cancelled: Order cancelled, need to release materials
"""

from django.dispatch import Signal

# Production started - need to consume materials
# Sent when craft.start() is called
# Args: work_order, requirements (list of dicts with product, quantity, position)
materials_needed = Signal()

# Production completed - need to receive product
# Sent when craft.complete() is called
# Args: work_order, actual_quantity, destination, user
production_completed = Signal()

# Order cancelled - need to release materials
# Sent when craft.cancel() is called
# Args: work_order, reason
order_cancelled = Signal()

__all__ = ["materials_needed", "production_completed", "order_cancelled"]
