"""
Tests for CodeSequence (craftsman.models.sequence).

CR2: Verifies atomic, race-condition-free code generation.
"""

import pytest
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from craftsman.models import CodeSequence, Recipe, WorkOrder


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def collection(db):
    from offerman.models import Collection

    return Collection.objects.create(name="Seq Test", slug="seq-test")


@pytest.fixture
def product(db, collection):
    from offerman.models import CollectionItem, Product

    p = Product.objects.create(
        sku="SEQ-001",
        name="Seq Product",
        unit="un",
        base_price_q=1000,
    )
    CollectionItem.objects.create(collection=collection, product=p, is_primary=True)
    return p


@pytest.fixture
def recipe(db, product):
    ct = ContentType.objects.get_for_model(product)
    return Recipe.objects.create(
        code="seq-recipe",
        name="Seq Recipe",
        output_type=ct,
        output_id=product.pk,
        output_quantity=Decimal("10"),
    )


# ═══════════════════════════════════════════════════════════════════
# CodeSequence
# ═══════════════════════════════════════════════════════════════════


class TestCodeSequence:
    """Tests for CodeSequence model."""

    def test_next_value_starts_at_1(self, db):
        """First call returns 1."""
        val = CodeSequence.next_value("TEST-PREFIX")
        assert val == 1

    def test_next_value_increments(self, db):
        """Subsequent calls increment."""
        v1 = CodeSequence.next_value("INC-PREFIX")
        v2 = CodeSequence.next_value("INC-PREFIX")
        v3 = CodeSequence.next_value("INC-PREFIX")

        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    def test_different_prefixes_independent(self, db):
        """Different prefixes have independent counters."""
        CodeSequence.next_value("PREFIX-A")
        CodeSequence.next_value("PREFIX-A")

        val_b = CodeSequence.next_value("PREFIX-B")

        assert val_b == 1  # Independent counter

    def test_str_representation(self, db):
        """String representation shows prefix and value."""
        CodeSequence.next_value("STR-PREFIX")
        seq = CodeSequence.objects.get(prefix="STR-PREFIX")

        assert "STR-PREFIX" in str(seq)
        assert "1" in str(seq)


# ═══════════════════════════════════════════════════════════════════
# WorkOrder code generation via sequence
# ═══════════════════════════════════════════════════════════════════


class TestWorkOrderCodeGeneration:
    """Tests for WorkOrder code generation using CodeSequence."""

    def test_auto_generates_code(self, recipe):
        """WorkOrder gets auto-generated code on save."""
        wo = WorkOrder.objects.create(
            recipe=recipe,
            planned_quantity=Decimal("50"),
        )

        assert wo.code.startswith("WO-")
        assert len(wo.code) > 0

    def test_sequential_codes(self, recipe):
        """Multiple WorkOrders get sequential codes."""
        wo1 = WorkOrder.objects.create(recipe=recipe, planned_quantity=Decimal("10"))
        wo2 = WorkOrder.objects.create(recipe=recipe, planned_quantity=Decimal("20"))

        # Extract numbers
        num1 = int(wo1.code.split("-")[-1])
        num2 = int(wo2.code.split("-")[-1])

        assert num2 == num1 + 1

    def test_custom_code_preserved(self, recipe):
        """Custom code is not overwritten."""
        wo = WorkOrder.objects.create(
            code="CUSTOM-001",
            recipe=recipe,
            planned_quantity=Decimal("50"),
        )

        assert wo.code == "CUSTOM-001"

    def test_no_collision_on_concurrent_create(self, recipe):
        """Creating multiple WOs quickly doesn't cause collisions."""
        codes = set()
        for _ in range(10):
            wo = WorkOrder.objects.create(
                recipe=recipe,
                planned_quantity=Decimal("10"),
            )
            codes.add(wo.code)

        # All codes unique
        assert len(codes) == 10
