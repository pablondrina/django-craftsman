# Django Craftsman

Production planning and work order management for Django.

## Installation

```bash
pip install django-craftsman
```

```python
INSTALLED_APPS = [
    ...
    'simple_history',  # required
    'craftsman',
    'craftsman.contrib.admin_unfold',  # optional, for Unfold admin
]
```

```bash
python manage.py migrate
```

## Core Concepts

### Recipe
Bill of materials (BOM) for producing a product.

```python
from craftsman.models import Recipe, RecipeItem
from offerman.models import Product

product = Product.objects.get(sku="CROISSANT")

recipe = Recipe.objects.create(
    code="croissant",
    name="Croissant",
    output_product=product,
    output_quantity=Decimal("10"),
    lead_time_days=1,
)

# Add ingredients
RecipeItem.objects.create(
    recipe=recipe,
    item_type=ContentType.objects.get_for_model(Product),
    item_id=flour.id,
    quantity=Decimal("1.5"),
    unit="kg",
)
```

### Plan
Daily production plan containing planned items.

```python
from craftsman.models import Plan, PlanItem, PlanStatus
from datetime import date

plan = Plan.objects.create(
    date=date.today(),
    status=PlanStatus.DRAFT,
)

PlanItem.objects.create(
    plan=plan,
    recipe=recipe,
    quantity=Decimal("50"),
)
```

### WorkOrder
Executable production task.

```python
from craftsman.models import WorkOrder, WorkOrderStatus

wo = WorkOrder.objects.create(
    recipe=recipe,
    planned_quantity=Decimal("50"),
    status=WorkOrderStatus.PENDING,
)

# Start production
wo.start()

# Record progress
wo.processed_quantity = Decimal("50")
wo.produced_quantity = Decimal("48")
wo.save()

# Complete
wo.complete(actual_quantity=Decimal("48"))
```

## Workflow

```
Recipe (BOM)
    ↓
Plan (daily planning)
    ↓
PlanItem (what to produce)
    ↓
WorkOrder (execution)
    ↓
Stock (via Stockman integration)
```

## Planning Flow

1. **Create Plan** for a date
2. **Add PlanItems** with recipes and quantities
3. **Approve Plan** when ready
4. **Generate WorkOrders** from PlanItems
5. **Execute WorkOrders** recording quantities
6. **Complete** and update stock

## WorkOrder Status

| Status | Description |
|--------|-------------|
| `pending` | Created, not started |
| `in_progress` | Production started |
| `paused` | Temporarily stopped |
| `completed` | Finished successfully |
| `cancelled` | Cancelled |

## Integration with Stockman

Craftsman can automatically:
- Check ingredient availability
- Reserve ingredients when scheduling
- Add produced items to stock on completion

```python
# When WorkOrder completes, add to stock
from stockman import stock

stock.add(
    product=work_order.recipe.output_product,
    position=work_order.destination,
    qty=work_order.actual_quantity,
    target_date=work_order.production_date,
    reason=f"WorkOrder {work_order.code}",
)
```

## Admin (Unfold)

The admin interface provides:
- Auto-redirect to today's date
- Auto-create PlanItems for products with active recipes
- List editable for quick updates
- Colored status badges

```python
INSTALLED_APPS = [
    'unfold',
    ...
    'craftsman',
    'craftsman.contrib.admin_unfold',
]
```

## History Tracking

Craftsman uses `django-simple-history` for audit trails on:
- Recipe
- Plan
- WorkOrder

```python
# View history
for record in work_order.history.all():
    print(f"{record.history_date}: {record.status}")
```

## Shopman Suite

Craftsman is part of the [Shopman suite](https://github.com/pablondrina). The admin UI uses shared utilities from [django-shopman-commons](https://github.com/pablondrina/django-shopman-commons):

- `BaseModelAdmin`, `BaseTabularInline`, `BaseStackedInline` — textarea-aware admin classes for Unfold
- `unfold_badge`, `unfold_badge_numeric` — colored badge helpers
- `format_quantity` — decimal formatting

```python
from shopman_commons.contrib.admin_unfold.base import BaseModelAdmin, BaseTabularInline, BaseStackedInline
from shopman_commons.contrib.admin_unfold.badges import unfold_badge, unfold_badge_numeric
from shopman_commons.formatting import format_quantity
```

## Requirements

- Python 3.11+
- Django 5.0+
- django-simple-history

## License

MIT
