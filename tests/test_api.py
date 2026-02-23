"""
Tests for Craftsman API ViewSets (craftsman.api.views).

CR4: Verifies DRF endpoints for Recipe, Plan, and WorkOrder.
"""

import pytest

pytestmark = pytest.mark.urls("craftsman.tests.test_api_urls")
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from rest_framework.test import APIClient

from craftsman.models import (
    Plan,
    PlanItem,
    PlanStatus,
    Recipe,
    WorkOrder,
    WorkOrderStatus,
)

User = get_user_model()


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def api_client(db):
    user = User.objects.create_user(username="api_user", password="test123")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="API Test", slug="api-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="API-001",
        name="API Product",
        unit="un",
        base_price_q=1000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="api-recipe",
        name="API Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
        steps=["Mixing", "Shaping", "Baking"],
    )


@pytest.fixture
def plan_date():
    return date.today() + timedelta(days=7)


@pytest.fixture
def draft_plan(db, plan_date, recipe):
    plan = Plan.objects.create(date=plan_date, status=PlanStatus.DRAFT)
    PlanItem.objects.create(plan=plan, recipe=recipe, quantity=Decimal("50"))
    return plan


@pytest.fixture
def work_order(db, recipe):
    return WorkOrder.objects.create(
        recipe=recipe,
        planned_quantity=Decimal("50"),
        status=WorkOrderStatus.PENDING,
        metadata={"step_log": []},
    )


# ═══════════════════════════════════════════════════════════════════
# RecipeViewSet
# ═══════════════════════════════════════════════════════════════════


class TestRecipeAPI:
    """Tests for Recipe read-only endpoints."""

    def test_list_recipes(self, api_client, recipe):
        """GET /api/craftsman/recipes/ returns active recipes."""
        response = api_client.get("/api/craftsman/recipes/")

        assert response.status_code == 200
        assert len(response.data) >= 1

    def test_retrieve_recipe(self, api_client, recipe):
        """GET /api/craftsman/recipes/{uuid}/ returns recipe detail."""
        response = api_client.get(f"/api/craftsman/recipes/{recipe.uuid}/")

        assert response.status_code == 200
        assert response.data["code"] == "api-recipe"
        assert response.data["steps"] == ["Mixing", "Shaping", "Baking"]

    def test_unauthenticated_returns_401(self, recipe):
        """Unauthenticated request returns 401/403."""
        client = APIClient()
        response = client.get("/api/craftsman/recipes/")

        assert response.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════
# PlanViewSet
# ═══════════════════════════════════════════════════════════════════


class TestPlanAPI:
    """Tests for Plan CRUD and actions."""

    def test_list_plans(self, api_client, draft_plan):
        """GET /api/craftsman/plans/ returns plans."""
        response = api_client.get("/api/craftsman/plans/")

        assert response.status_code == 200
        assert len(response.data) >= 1

    def test_approve_plan(self, api_client, draft_plan):
        """POST /api/craftsman/plans/{pk}/approve/ approves the plan."""
        response = api_client.post(f"/api/craftsman/plans/{draft_plan.pk}/approve/")

        assert response.status_code == 200
        assert response.data["status"] == "approved"

        draft_plan.refresh_from_db()
        assert draft_plan.status == PlanStatus.APPROVED

    def test_approve_non_draft_fails(self, api_client, draft_plan):
        """Approving a non-draft plan returns 400."""
        draft_plan.approve()  # Make it approved first

        response = api_client.post(f"/api/craftsman/plans/{draft_plan.pk}/approve/")

        assert response.status_code == 400

    def test_schedule_plan(self, api_client, draft_plan):
        """POST /api/craftsman/plans/{pk}/schedule/ creates work orders."""
        draft_plan.approve()

        response = api_client.post(f"/api/craftsman/plans/{draft_plan.pk}/schedule/")

        assert response.status_code == 200
        assert response.data["status"] == "scheduled"
        assert response.data["work_orders_created"] >= 1


# ═══════════════════════════════════════════════════════════════════
# WorkOrderViewSet
# ═══════════════════════════════════════════════════════════════════


class TestWorkOrderAPI:
    """Tests for WorkOrder CRUD and actions."""

    def test_list_work_orders(self, api_client, work_order):
        """GET /api/craftsman/work-orders/ returns work orders."""
        response = api_client.get("/api/craftsman/work-orders/")

        assert response.status_code == 200
        assert len(response.data) >= 1

    def test_retrieve_work_order(self, api_client, work_order):
        """GET /api/craftsman/work-orders/{uuid}/ returns detail."""
        response = api_client.get(f"/api/craftsman/work-orders/{work_order.uuid}/")

        assert response.status_code == 200
        assert response.data["status"] == "pending"
        assert response.data["planned_quantity"] == "50"

    def test_step_action(self, api_client, work_order):
        """POST /api/craftsman/work-orders/{uuid}/step/ records a step."""
        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/step/",
            {"step": "Mixing", "quantity": 50},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "in_progress"
        assert len(response.data["step_log"]) == 1

    def test_step_invalid_data(self, api_client, work_order):
        """POST step/ with missing data returns 400."""
        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/step/",
            {},
            format="json",
        )

        assert response.status_code == 400

    def test_complete_action(self, api_client, work_order):
        """POST /api/craftsman/work-orders/{uuid}/complete/ completes the order."""
        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/complete/",
            {"actual_quantity": 48},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "completed"
        assert response.data["actual_quantity"] == 48.0

    def test_complete_without_quantity(self, api_client, work_order):
        """Complete without actual_quantity uses planned_quantity."""
        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/complete/",
            {},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "completed"

    def test_pause_action(self, api_client, work_order):
        """POST pause/ pauses an in-progress order."""
        # First start it
        work_order.status = WorkOrderStatus.IN_PROGRESS
        work_order.save(update_fields=["status"])

        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/pause/",
            {"reason": "Falta de material"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "paused"

    def test_resume_action(self, api_client, work_order):
        """POST resume/ resumes a paused order."""
        work_order.status = WorkOrderStatus.IN_PROGRESS
        work_order.save(update_fields=["status"])
        work_order.pause(reason="test")

        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/resume/",
        )

        assert response.status_code == 200
        assert response.data["status"] == "in_progress"

    def test_cancel_action(self, api_client, work_order):
        """POST cancel/ cancels a pending order."""
        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/cancel/",
            {"reason": "No longer needed"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == "cancelled"

    def test_cancel_completed_fails(self, api_client, work_order):
        """Cancelling a completed order returns 400."""
        work_order.complete(actual_quantity=Decimal("48"))

        response = api_client.post(
            f"/api/craftsman/work-orders/{work_order.uuid}/cancel/",
            {"reason": "Too late"},
            format="json",
        )

        assert response.status_code == 400
