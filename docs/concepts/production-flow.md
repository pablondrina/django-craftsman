# Production Flow

End-to-end guide to how django-craftsman manages the production lifecycle, from recipe definition through work order completion.

---

## Overview

Craftsman implements a simplified MRP (Material Requirements Planning) flow:

```
Recipe --> Plan --> Schedule --> WorkOrder --> Steps --> Complete
```

Each stage feeds the next. The full flow is optional -- you can create WorkOrders directly via `Craft.create()` to skip the planning phase.

---

## 1. Recipe (Bill of Materials)

A Recipe defines HOW to make something:

- **Output product** (GenericForeignKey -- any Django model)
- **Output quantity** per batch (e.g. 50 croissants)
- **Ingredients** (`RecipeItem`) with quantities using the French coefficient method
- **Steps** (JSON list of step names, e.g. `["Mixing", "Shaping", "Baking"]`)
- **Work center** (Position where production happens)
- **Lead time** (days before target date to start production)

```python
recipe = Recipe.objects.create(
    code="croissant-v1",
    name="Croissant Tradicional",
    output_type=ct,
    output_id=product.pk,
    output_quantity=Decimal("50"),
    steps=["Mixing", "Shaping", "Baking"],
    lead_time_days=1,
    work_center=forno_1,
)
```

---

## 2. Plan (Master Production Schedule)

A Plan is a daily production schedule. One Plan per date.

```python
from craftsman import craft

# Add items to the plan
item = craft.plan(50, croissant, date(2026, 2, 23), vitrine)
item = craft.plan(30, baguette, date(2026, 2, 23), vitrine)
```

`craft.plan()` creates or updates a PlanItem. If a Plan for that date does not exist, one is created in DRAFT status. If a PlanItem for that recipe already exists, its quantity is updated.

**Plan lifecycle:**

```
DRAFT --> APPROVED --> SCHEDULED --> COMPLETED
```

- DRAFT: Items can be added/removed/edited.
- APPROVED: Plan is locked. `craft.approve(date)` transitions it.
- SCHEDULED: WorkOrders have been created. `craft.schedule(date)` transitions it.
- COMPLETED: All work is done. `plan.complete()` transitions it.

---

## 3. Schedule (Plan to WorkOrders)

Scheduling converts an approved Plan into concrete WorkOrders:

```python
craft.approve(date(2026, 2, 23))
result = craft.schedule(date(2026, 2, 23))

if result.success:
    for wo in result.work_orders:
        print(f"Created: {wo.code}")
else:
    for error in result.errors:
        print(f"Shortage: {error.sku} needs {error.required}, has {error.available}")
```

**What happens during schedule():**

1. Each PlanItem with quantity > 0 becomes one WorkOrder.
2. All WorkOrders are created inside a single `transaction.atomic()`.
3. WorkOrder codes are auto-generated via `CodeSequence` (e.g. `WO-2026-00042`).
4. If `CRAFTSMAN["RESERVE_INPUTS"]` is enabled, materials are checked and reserved before WorkOrders are created. If any material is short, the entire schedule is rejected with detailed shortage information.

---

## 4. WorkOrder Lifecycle

```
                    +------------------+
                    |     PENDING      |
                    +--------+---------+
                             |
                  step() or start()
                             |
                             v
                    +------------------+
                    |   IN_PROGRESS    |<----+
                    +--------+---------+     |
                             |               |
                +------------+--------+      |
                |            |        |      |
           last step    pause()   cancel()   |
                |            |               |
                v            v               |
        +-------+--+ +------+------+        |
        | COMPLETED | |   PAUSED    |        |
        +----------+  +------+------+        |
                             |               |
                         resume()            |
                             |               |
                             +---------------+

                    +------------------+
                    |    CANCELLED     |
                    +------------------+
                    (from PENDING, IN_PROGRESS, or PAUSED)
```

### Starting a WorkOrder

Two ways to start:

1. **Explicit start**: `craft.start(wo)` -- transitions to IN_PROGRESS, emits `materials_needed` signal.
2. **Implicit start via step**: `wo.step("Mixing", 70)` -- if PENDING, auto-transitions to IN_PROGRESS on first step.

### Recording Steps

The `step()` method on WorkOrder is the core execution mechanism:

```python
wo.step("Mixing", 70, user=operador)    # Auto-starts if PENDING
wo.step("Shaping", 74, user=operador)
wo.step("Baking", 72, user=operador)    # Auto-completes (last step)
```

Each step:
- Records an entry in `metadata["step_log"]` with step name, quantity, timestamp, and user.
- Maps step quantities to dedicated fields (`process_quantity`, `output_quantity`) based on position in recipe steps.
- On the last step, automatically calls `complete()`.

### Completing a WorkOrder

Completion can happen:
- **Automatically**: when the last recipe step is recorded via `step()`.
- **Manually**: via `craft.complete(wo, actual_quantity)` or `wo.complete(qty)`.

On completion:
- Status becomes COMPLETED.
- `actual_quantity` is set (from step quantity, explicit argument, or planned quantity).
- `production_completed` signal is emitted (Stockman uses this to receive product into inventory).

### Idempotency

Calling `complete()` on an already-completed WorkOrder is safe -- it logs a warning and returns without error or side effects.

---

## 5. BOM Expansion (Recursive Ingredients)

Craftsman supports multilevel Bills of Materials. A RecipeItem can point to a product that itself has a Recipe, creating nested ingredient requirements.

**Example:**

```
Croissant Recipe (output: 50 croissants)
  |-- Butter: 2.5 kg
  |-- Croissant Dough: 10 kg  --> has its own Recipe!
        |-- Flour: 6 kg
        |-- Water: 3.2 L
        |-- Salt: 0.08 kg
```

**How expansion works:**

1. `calculate_daily_ingredients()` iterates over all PlanItems for a date.
2. For each PlanItem, it calculates the French coefficient: `plan_quantity / recipe.output_quantity`.
3. For each RecipeItem, it checks if the ingredient has its own Recipe (`_get_sub_recipe()`).
4. If yes, it recursively expands the sub-recipe with a chained coefficient.
5. If no (terminal ingredient), it yields the aggregated quantity.
6. A depth limit of 5 (`_MAX_BOM_DEPTH`) prevents infinite loops from circular references.

**Coefficient calculation:**

```
Croissant plan: 100 units, recipe yields 50
  -> coefficient = 100 / 50 = 2.0
  -> Butter needed: 2.5 * 2.0 = 5.0 kg
  -> Croissant Dough needed: 10 * 2.0 = 20.0 kg
       Sub-recipe yields 10 kg, so sub-coefficient = 20.0 / 10.0 = 2.0
       -> Flour needed: 6 * 2.0 = 12.0 kg
       -> Water needed: 3.2 * 2.0 = 6.4 L
       -> Salt needed: 0.08 * 2.0 = 0.16 kg
```

---

## 6. Stockman Integration (Optional)

Craftsman communicates with Stockman through two mechanisms:

### A. Signals (craftsman.contrib.stockman)

Add `"craftsman.contrib.stockman"` to `INSTALLED_APPS` to enable automatic signal handlers:

| Signal | Handler | Stockman Action |
|--------|---------|-----------------|
| `materials_needed` | `consume_materials_from_stockman` | `stock.issue()` -- consumes raw materials |
| `production_completed` | `receive_production_in_stockman` | `stock.receive()` -- adds finished product to inventory |
| `order_cancelled` | `release_materials_on_cancel` | `stock.release()` -- frees reserved materials |

**Flow with Stockman enabled:**

```
WorkOrder starts
  --> materials_needed signal
  --> Stockman handler: stock.issue() for each ingredient

WorkOrder completes
  --> production_completed signal
  --> Stockman handler: stock.receive() at destination position

WorkOrder cancelled
  --> order_cancelled signal
  --> Stockman handler: stock.release() for held materials
```

### B. Material Reservation (RESERVE_INPUTS)

When `CRAFTSMAN["RESERVE_INPUTS"] = True`, the `schedule()` method uses the `StockBackend` protocol to:

1. **Check availability**: Verify all materials are in stock before creating WorkOrders.
2. **Reserve materials**: Create holds via `stock.hold()` so materials are not double-allocated.
3. **Atomic rollback**: If any reservation fails, the entire schedule is rolled back.

This is separate from the signal-based consumption. Reservation happens at schedule time; consumption happens at execution time.

### C. Production Backend (Stockman to Craftsman)

`CraftsmanProductionBackend` implements Stockman's `ProductionBackend` protocol, allowing Stockman to request production when stock hits reorder points:

```python
# Stockman calls this when stock is low:
backend.request_production(ProductionRequest(
    sku="CROISSANT",
    quantity=Decimal("50"),
    target_date=date(2026, 2, 24),
))
# -> Creates a WorkOrder in Craftsman
```

---

## 7. Position Model Swappability

Craftsman uses a `Position` model for locations (work centers, delivery destinations, material sources). It ships with a minimal default:

```python
# Default: craftsman.Position
class Position(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict)
```

To use an external position system (e.g. Stockman's richer Position model):

```python
# settings.py
CRAFTSMAN = {
    "POSITION_MODEL": "stockman.Position",
}
```

The swap is handled via Django's `ForeignKey(get_position_model_string(), ...)` pattern. All models that reference positions (Recipe, PlanItem, WorkOrder, RecipeItem) use this function, so switching the model is a single configuration change.

---

## Complete Flow Diagram

```
  [Define Recipes]
         |
         v
  craft.plan(qty, product, date, destination)
         |  creates Plan (DRAFT) + PlanItem
         v
  craft.approve(date)
         |  Plan: DRAFT --> APPROVED
         v
  craft.schedule(date)
         |  Plan: APPROVED --> SCHEDULED
         |  Creates WorkOrders atomically
         |  (optional: reserves materials via StockBackend)
         v
  +------+-------+
  |  WorkOrder    |  status: PENDING
  |  WO-2026-001  |
  +--------------+
         |
    wo.step("Mixing", 70)       <-- auto-starts, emits materials_needed
         |
    wo.step("Shaping", 74)
         |
    wo.step("Baking", 72)       <-- last step, auto-completes
         |                           emits production_completed
         v
  +--------------+
  |  COMPLETED   |  actual_quantity = 72
  +--------------+
```
