# Craftsman Contracts

Single-page reference for django-craftsman's public API, invariants, and integration boundaries.

---

## Public API

The `Craft` class (`craftsman.service.Craft`) is the single entry point. All methods are `@classmethod`.

### Planning

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `plan` | `(quantity, product, production_date, destination=None, priority=50)` | `PlanItem` | Add/update item in daily plan. Creates Plan (DRAFT) if needed. |
| `approve` | `(production_date, user=None)` | `Plan` | Transition plan DRAFT -> APPROVED. |
| `schedule` | `(production_date, start_time=None, location=None, user=None, skip_reservation=False)` | `ScheduleResult` | Convert approved plan into WorkOrders atomically. Optionally reserves materials. |

### Execution

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `create` | `(quantity, recipe, destination, scheduled_start=None, ...)` | `WorkOrder` | Create a standalone WorkOrder (bypasses MPS plan flow). |
| `create_batch` | `(production_date, items, start_time=None, ...)` | `list[WorkOrder]` | Create multiple WorkOrders for a production day. |
| `start` | `(work_order, user=None)` | `WorkOrder` | Begin execution; emits `materials_needed` signal. |
| `complete` | `(work_order, actual_quantity=None, user=None)` | `WorkOrder` | Finalize production; emits `production_completed` signal. |
| `pause` | `(work_order, reason="", user=None)` | `WorkOrder` | Pause an in-progress order. |
| `resume` | `(work_order, user=None)` | `WorkOrder` | Resume a paused order. |
| `cancel` | `(work_order, reason="", user=None)` | `WorkOrder` | Cancel order; emits `order_cancelled` signal. |

### Queries

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `find_recipe` | `(product)` | `Recipe \| None` | Find active recipe for a product (via GenericFK). |
| `get_plan` | `(production_date)` | `Plan \| None` | Get plan for a date. |
| `get_plan_item` | `(product, production_date)` | `PlanItem \| None` | Get plan item for product/date. |
| `get_work_order` | `(plan_item)` | `WorkOrder \| None` | Get active work order for a plan item. |
| `get_pending` | `(production_date=None, location=None)` | `list[WorkOrder]` | List pending work orders. |
| `get_in_progress` | `(location=None)` | `list[WorkOrder]` | List in-progress work orders. |

### WorkOrder Model Methods (SIREL -- business logic on the model)

The WorkOrder model encapsulates core execution logic directly:

- `wo.step(step_name, quantity, user=None)` -- Record a production step. Auto-starts if PENDING, auto-completes on last step.
- `wo.complete(actual_quantity, user=None)` -- Finalize production.
- `wo.pause(reason, user=None)` / `wo.resume(user=None)` -- Pause/resume.
- `wo.cancel(reason, user=None)` -- Cancel order.

---

## Invariants

### Recipe Validation

- `output_quantity` must be > 0 (enforced in `Recipe.clean()`).
- `steps` must be a list of non-empty strings when provided.
- BOM cycle detection: recursive ingredient expansion is capped at depth 5 (`_MAX_BOM_DEPTH`). If exceeded, expansion stops and logs a warning. A recipe item whose target has its own recipe triggers recursive expansion.

### WorkOrder Lifecycle

Valid state transitions:

```
PENDING --> IN_PROGRESS --> COMPLETED
  |              |
  |              +--> PAUSED --> IN_PROGRESS  (resume)
  |              |
  |              +--> CANCELLED
  |
  +--> COMPLETED  (direct complete without steps)
  |
  +--> CANCELLED
```

- `step()` only allowed when PENDING or IN_PROGRESS.
- `pause()` only from IN_PROGRESS.
- `resume()` only from PAUSED.
- `cancel()` blocked if already COMPLETED or CANCELLED.
- `complete()` allowed from PENDING, IN_PROGRESS, or PAUSED.

### CodeSequence

- Atomic gap-free counters per prefix (e.g. `WO-2026`).
- Uses `SELECT FOR UPDATE` to prevent race conditions.
- One row per prefix; `next_value()` increments atomically within a transaction.
- WorkOrder codes follow format `WO-YYYY-NNNNN`.

### Plan Lifecycle

```
DRAFT --> APPROVED --> SCHEDULED --> COMPLETED
```

- `approve()` only from DRAFT.
- `schedule()` only from APPROVED; creates WorkOrders atomically inside `transaction.atomic()`.
- `complete()` only from SCHEDULED.
- One Plan per date (unique constraint on `Plan.date`).
- One PlanItem per (plan, recipe) pair (unique_together).

### Plan to WorkOrder (schedule)

- `schedule()` creates all WorkOrders in a single atomic transaction.
- If `RESERVE_INPUTS` is enabled, materials are checked for availability first. If any material is short, no WorkOrders are created and `ScheduleResult.success=False` with detailed `InputShortage` errors.
- Each PlanItem with quantity > 0 produces exactly one WorkOrder.

---

## Idempotency

- `complete()` on an already-completed WorkOrder is a no-op (logs a warning, returns without error).
- `plan()` with an existing (plan, recipe) pair updates the quantity rather than creating a duplicate.
- `Plan.objects.get_or_create(date=...)` ensures exactly one plan per date.

---

## Integration Points

### DemandBackend (Protocol)

Defined in `craftsman.protocols.demand`. A single method:

```python
class DemandBackend(Protocol):
    def committed(self, product, target_date: date) -> Decimal: ...
```

- Configured via `CRAFTSMAN["DEMAND_BACKEND"]` (dotted path to class).
- Used by `PlanItem.get_suggested_quantity()` to include committed demand in production suggestions.
- Optional: if not configured, committed demand is treated as zero.

### StockBackend (Protocol)

Defined in `craftsman.protocols.stock`. Methods: `available()`, `reserve()`, `consume()`, `release()`, `receive()`.

- Configured via `CRAFTSMAN["STOCK_BACKEND"]`.
- Used during `schedule()` when `RESERVE_INPUTS=True` to check availability and reserve materials.
- The `StockmanBackend` adapter (`craftsman.adapters.stockman`) maps these to Stockman's API.

### Position Model (Swappable)

- Default: `craftsman.Position` (minimal: code, name, metadata).
- Swappable via `CRAFTSMAN["POSITION_MODEL"]` (e.g. `"stockman.Position"`).
- Referenced by Recipe (work_center), PlanItem (destination), WorkOrder (destination, location), RecipeItem (position).

### Signals (Decoupled Integration)

| Signal | Sent when | Kwargs |
|--------|-----------|--------|
| `materials_needed` | WorkOrder starts (first step or `Craft.start()`) | `work_order`, `requirements` |
| `production_completed` | WorkOrder completes | `work_order`, `actual_quantity`, `destination`, `user` |
| `order_cancelled` | WorkOrder cancelled | `work_order`, `reason` |

### Stockman Contrib (Optional)

`craftsman.contrib.stockman` (add to `INSTALLED_APPS` to enable):

- **Signal handlers**: auto-consume materials on start, auto-receive product on complete, auto-release holds on cancel.
- **CraftsmanProductionBackend**: allows Stockman to request production when stock hits reorder point.

### ProductInfoBackend (Protocol)

- Configured via `CRAFTSMAN["PRODUCT_INFO_BACKEND"]`.
- Used by adapters to resolve SKU strings to product model instances.

---

## What is NOT Craftsman's Job

- **Inventory tracking**: Craftsman does not track stock levels, quantities on hand, or warehouse locations. That is Stockman's responsibility. Craftsman only emits signals; Stockman's handlers (or other subscribers) perform actual stock mutations.
- **Pricing**: Craftsman has no concept of cost, price, or monetary value. Recipes define quantities, not costs.
- **Order management**: Customer orders, sales orders, and fulfillment are outside scope. Craftsman receives demand data through the DemandBackend protocol but does not manage orders.
- **Purchasing / Procurement**: Craftsman does not create purchase orders for raw materials. It reports shortages via `ScheduleResult.errors` but does not act on them.
- **User authentication / Permissions**: Craftsman accepts an optional `user` parameter for audit trails but does not enforce permissions.
