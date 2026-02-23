"""
Tests for Recipe validation, coefficient calculation, and loss properties.

QC2: Validates data integrity and the French bakery coefficient method.
"""

import pytest
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from craftsman.models import (
    IngredientCategory,
    Recipe,
    RecipeItem,
    WorkOrder,
    WorkOrderStatus,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Recipe Val Test", slug="recipe-val-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RV-001",
        name="Pão Francês",
        unit="un",
        base_price_q=100,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def farinha(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RV-FARINHA",
        name="Farinha de Trigo",
        unit="kg",
        base_price_q=500,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def fermento(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="RV-FERMENTO",
        name="Fermento",
        unit="kg",
        base_price_q=2000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="pao-frances-rv",
        name="Pão Francês",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("100"),
        steps=["Mixing", "Fermentation", "Baking"],
    )


@pytest.fixture
def recipe_with_items(db, recipe, farinha, fermento):
    far_ct = ContentType.objects.get_for_model(farinha)
    RecipeItem.objects.create(
        recipe=recipe,
        item_type=far_ct,
        item_id=farinha.pk,
        quantity=Decimal("5.000"),
        unit="kg",
    )

    fer_ct = ContentType.objects.get_for_model(fermento)
    RecipeItem.objects.create(
        recipe=recipe,
        item_type=fer_ct,
        item_id=fermento.pk,
        quantity=Decimal("0.100"),
        unit="kg",
    )

    return recipe


# ═══════════════════════════════════════════════════════════════════
# Recipe.clean() Validation
# ═══════════════════════════════════════════════════════════════════


class TestRecipeClean:
    """Tests for Recipe.clean() model validation."""

    def test_valid_recipe(self, recipe):
        """A well-formed recipe passes validation."""
        recipe.full_clean()  # Should not raise

    def test_output_quantity_zero_raises(self, db, product):
        """output_quantity <= 0 is rejected."""
        ct = ContentType.objects.get_for_model(product)
        with pytest.raises(ValidationError) as exc:
            Recipe.objects.create(
                code="zero-output",
                name="Zero Output",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal("0"),
            )

        assert "output_quantity" in exc.value.message_dict

    def test_output_quantity_negative_raises(self, db, product):
        """Negative output_quantity is rejected."""
        ct = ContentType.objects.get_for_model(product)
        with pytest.raises(ValidationError) as exc:
            Recipe.objects.create(
                code="neg-output",
                name="Neg Output",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal("-5"),
            )

        assert "output_quantity" in exc.value.message_dict

    def test_steps_not_list_raises(self, db, product):
        """steps must be a list, not a string."""
        ct = ContentType.objects.get_for_model(product)
        with pytest.raises(ValidationError) as exc:
            Recipe.objects.create(
                code="bad-steps-str",
                name="Bad Steps",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal("10"),
                steps="Mixing, Baking",  # String, not list
            )

        assert "steps" in exc.value.message_dict

    def test_steps_empty_string_raises(self, db, product):
        """Steps with empty strings are rejected."""
        ct = ContentType.objects.get_for_model(product)
        with pytest.raises(ValidationError) as exc:
            Recipe.objects.create(
                code="empty-step",
                name="Empty Step",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal("10"),
                steps=["Mixing", "", "Baking"],
            )

        assert "steps" in exc.value.message_dict

    def test_steps_non_string_raises(self, db, product):
        """Steps with non-string items are rejected."""
        ct = ContentType.objects.get_for_model(product)
        with pytest.raises(ValidationError) as exc:
            Recipe.objects.create(
                code="int-step",
                name="Int Step",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal("10"),
                steps=["Mixing", 42, "Baking"],
            )

        assert "steps" in exc.value.message_dict

    def test_empty_steps_list_ok(self, db, product):
        """Empty steps list is valid (recipe without defined steps)."""
        ct = ContentType.objects.get_for_model(product)
        r = Recipe.objects.create(
            code="no-steps",
            name="No Steps",
            output_type=ct,
            output_id=product.pk,
            output_quantity=Decimal("10"),
            steps=[],
        )
        assert r.steps == []


# ═══════════════════════════════════════════════════════════════════
# Recipe Properties
# ═══════════════════════════════════════════════════════════════════


class TestRecipeProperties:
    """Tests for Recipe model properties and methods."""

    def test_str_representation(self, recipe):
        """__str__ includes name and output_quantity."""
        s = str(recipe)
        assert "Pão Francês" in s
        assert "100" in s

    def test_last_step(self, recipe):
        """last_step returns the final step name."""
        assert recipe.last_step == "Baking"

    def test_last_step_no_steps(self, db, product):
        """last_step is None when no steps defined."""
        ct = ContentType.objects.get_for_model(product)
        r = Recipe.objects.create(
            code="no-steps-2",
            name="No Steps",
            output_type=ct,
            output_id=product.pk,
            output_quantity=Decimal("10"),
            steps=[],
        )
        assert r.last_step is None

    def test_get_steps(self, recipe):
        """get_steps() returns a list copy."""
        steps = recipe.get_steps()
        assert steps == ["Mixing", "Fermentation", "Baking"]
        # Should be a copy, not the same object
        steps.append("Extra")
        assert len(recipe.get_steps()) == 3

    def test_get_step_existing(self, recipe):
        """get_step() returns dict for existing step."""
        result = recipe.get_step("Mixing")
        assert result is not None
        assert result["name"] == "Mixing"

    def test_get_step_nonexistent(self, recipe):
        """get_step() returns None for unknown step."""
        result = recipe.get_step("Frying")
        assert result is None

    def test_output_product(self, recipe, product):
        """output_product returns the linked product."""
        assert recipe.output_product == product


# ═══════════════════════════════════════════════════════════════════
# French Coefficient Calculation (_calculate_requirements)
# ═══════════════════════════════════════════════════════════════════


class TestCoefficientCalculation:
    """Tests for WorkOrder._calculate_requirements() (French coefficient method)."""

    def test_basic_coefficient(self, recipe_with_items):
        """Coefficient scales ingredient quantities correctly."""
        wo = WorkOrder.objects.create(
            recipe=recipe_with_items,
            planned_quantity=Decimal("200"),  # 2x the recipe base (100)
        )

        reqs = wo._calculate_requirements()

        assert len(reqs) == 2

        # Farinha: 5.000 kg * (200/100) = 10.000 kg
        farinha_req = next(r for r in reqs if r["sku"] == "RV-FARINHA")
        assert farinha_req["quantity"] == Decimal("10.000")

        # Fermento: 0.100 kg * (200/100) = 0.200 kg
        fermento_req = next(r for r in reqs if r["sku"] == "RV-FERMENTO")
        assert fermento_req["quantity"] == Decimal("0.200")

    def test_coefficient_fractional(self, recipe_with_items):
        """Fractional coefficient (produce less than one batch)."""
        wo = WorkOrder.objects.create(
            recipe=recipe_with_items,
            planned_quantity=Decimal("50"),  # 0.5x base
        )

        reqs = wo._calculate_requirements()

        farinha_req = next(r for r in reqs if r["sku"] == "RV-FARINHA")
        assert farinha_req["quantity"] == Decimal("2.500")

    def test_coefficient_zero_output_quantity(self, db, product):
        """output_quantity=0 falls back to coefficient=1."""
        ct = ContentType.objects.get_for_model(product)
        # Can't use Recipe.objects.create because clean() rejects qty=0
        # so we use the fallback path with output_quantity set after creation
        r = Recipe.objects.create(
            code="zero-base-rv",
            name="Zero Base",
            output_type=ct,
            output_id=product.pk,
            output_quantity=Decimal("1"),  # valid for save
        )
        # Bypass validation to test the fallback
        Recipe.objects.filter(pk=r.pk).update(output_quantity=Decimal("0"))
        r.refresh_from_db()

        wo = WorkOrder.objects.create(
            recipe=r,
            planned_quantity=Decimal("50"),
        )

        reqs = wo._calculate_requirements()
        # With coefficient=1, no items → empty list
        assert reqs == []

    def test_inactive_items_excluded(self, recipe_with_items):
        """Inactive RecipeItems are excluded from requirements."""
        RecipeItem.objects.filter(recipe=recipe_with_items).update(is_active=False)

        wo = WorkOrder.objects.create(
            recipe=recipe_with_items,
            planned_quantity=Decimal("100"),
        )

        reqs = wo._calculate_requirements()
        assert reqs == []

    def test_no_items(self, recipe):
        """Recipe with no items returns empty requirements."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )

        reqs = wo._calculate_requirements()
        assert reqs == []


# ═══════════════════════════════════════════════════════════════════
# WorkOrder Loss Properties (Yield Tracking)
# ═══════════════════════════════════════════════════════════════════


class TestLossProperties:
    """Tests for WorkOrder.loss_quantity and loss_percentage."""

    def test_loss_quantity_normal(self, recipe):
        """Normal loss: planned=100, actual=95 → loss=5."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            actual_quantity=Decimal("95"),
            status=WorkOrderStatus.COMPLETED,
        )

        assert wo.loss_quantity == Decimal("5")

    def test_loss_quantity_overproduction(self, recipe):
        """Overproduction: planned=100, actual=105 → loss=-5."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            actual_quantity=Decimal("105"),
            status=WorkOrderStatus.COMPLETED,
        )

        assert wo.loss_quantity == Decimal("-5")

    def test_loss_quantity_none_when_not_completed(self, recipe):
        """loss_quantity is None when actual_quantity is not set."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            status=WorkOrderStatus.PENDING,
        )

        assert wo.loss_quantity is None

    def test_loss_percentage_normal(self, recipe):
        """5% loss: planned=100, actual=95."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            actual_quantity=Decimal("95"),
            status=WorkOrderStatus.COMPLETED,
        )

        assert wo.loss_percentage == Decimal("5")

    def test_loss_percentage_zero(self, recipe):
        """No loss: planned=actual."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            actual_quantity=Decimal("100"),
            status=WorkOrderStatus.COMPLETED,
        )

        assert wo.loss_percentage == Decimal("0")

    def test_loss_percentage_none_when_not_completed(self, recipe):
        """loss_percentage is None when actual_quantity is not set."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            status=WorkOrderStatus.PENDING,
        )

        assert wo.loss_percentage is None

    def test_loss_percentage_high(self, recipe):
        """50% loss: planned=100, actual=50."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
            actual_quantity=Decimal("50"),
            status=WorkOrderStatus.COMPLETED,
        )

        assert wo.loss_percentage == Decimal("50")


# ═══════════════════════════════════════════════════════════════════
# WorkOrder Step Quantity Tracking
# ═══════════════════════════════════════════════════════════════════


class TestStepQuantityTracking:
    """Tests for WorkOrder.get_step_quantity() and step_log property."""

    def test_step_log_empty(self, recipe):
        """Empty step_log when no steps recorded."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )
        assert wo.step_log == []

    def test_step_log_after_steps(self, recipe):
        """step_log tracks all recorded steps."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )
        wo.step("Mixing", Decimal("95"))
        wo.step("Fermentation", Decimal("93"))

        assert len(wo.step_log) == 2
        assert wo.step_log[0]["step"] == "Mixing"
        assert wo.step_log[1]["step"] == "Fermentation"

    def test_get_step_quantity(self, recipe):
        """get_step_quantity() returns the quantity for a specific step."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )
        wo.step("Mixing", Decimal("95"))

        assert wo.get_step_quantity("Mixing") == Decimal("95")

    def test_get_step_quantity_nonexistent(self, recipe):
        """get_step_quantity() returns None for unrecorded step."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )

        assert wo.get_step_quantity("Mixing") is None

    def test_completed_steps_list(self, recipe):
        """completed_steps returns list of step names."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )
        wo.step("Mixing", Decimal("95"))
        wo.step("Fermentation", Decimal("93"))

        assert wo.completed_steps == ["Mixing", "Fermentation"]

    def test_progress_with_steps(self, recipe):
        """progress dict shows completion percentage."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("100"),
        )
        wo.step("Mixing", Decimal("95"))

        progress = wo.progress
        assert progress["completed"] == 1
        assert progress["total"] == 3
        assert progress["percentage"] == 33

    def test_progress_no_steps_defined(self, db, product):
        """progress without recipe steps uses status-based fallback."""
        ct = ContentType.objects.get_for_model(product)
        r = Recipe.objects.create(
            code="no-steps-progress",
            name="No Steps Progress",
            output_type=ct,
            output_id=product.pk,
            output_quantity=Decimal("10"),
            steps=[],
        )
        wo = WorkOrder.objects.create(
            recipe=r,
            planned_quantity=Decimal("100"),
            status=WorkOrderStatus.IN_PROGRESS,
        )

        progress = wo.progress
        assert progress["percentage"] == 50
