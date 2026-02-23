"""
Recipe and RecipeItem models.

Recipe = BOM (Bill of Materials) - defines HOW to make something.
RecipeItem = Insumo da receita (método do coeficiente francês).

Referência: http://techno.boulangerie.free.fr/
"""

import uuid
from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from craftsman.conf import get_position_model_string


class IngredientCategory(models.Model):
    """
    Categoria de insumos para agrupamento e filtros.

    Exemplos: Massa, Farinha, Líquido, Gordura, Fermento, Chocolate...
    """

    code = models.SlugField(
        unique=True,
        max_length=50,
        verbose_name=_("Código"),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("Nome"),
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Ordem"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Ativa"),
    )

    class Meta:
        db_table = "craftsman_ingredient_category"
        verbose_name = _("Categoria de Ingrediente")
        verbose_name_plural = _("Categorias de Ingredientes")
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Recipe(models.Model):
    """
    Receita de produção (BOM - Bill of Materials).

    Define:
    - Produto de saída (GenericForeignKey)
    - Quantidade produzida por lote
    - Centro de trabalho (Position)
    - Lead time (dias antes da target_date)
    - Etapas de produção (steps)
    """

    # UUID for external references
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )

    # Output product (generic)
    output_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Tipo de Produto"),
        help_text=_("Tipo do produto de saída"),
    )
    output_id = models.PositiveIntegerField(
        verbose_name=_("ID do Produto"),
        help_text=_("ID do produto de saída"),
    )
    output_product = GenericForeignKey("output_type", "output_id")

    # Identification
    code = models.SlugField(
        unique=True,
        max_length=50,
        verbose_name=_("Código"),
        help_text=_("Identificador único (ex: croissant-v1)"),
    )
    name = models.CharField(
        max_length=200,
        verbose_name=_("Nome"),
        help_text=_("Nome legível da receita"),
    )

    output_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1"),
        verbose_name=_("Quantidade de Saída"),
        help_text=_("Quantidade produzida por execução da receita"),
    )

    # Work center (Position)
    work_center = models.ForeignKey(
        get_position_model_string(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recipes",
        verbose_name=_("Centro de Trabalho"),
        help_text=_("Posição onde a produção acontece"),
    )

    # Lead time (days before target_date to start production)
    lead_time_days = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Lead Time (dias)"),
        help_text=_("Dias de antecedência para iniciar produção"),
    )

    # Production steps
    steps = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Etapas de Produção"),
        help_text=_("Lista de etapas: ['Mixing', 'Shaping', 'Baking']"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Ativa"),
        help_text=_("Receita pode ser usada para novas ordens"),
    )

    # Estimated time
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Duração (minutos)"),
        help_text=_("Tempo estimado de produção total"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Observações"),
    )

    # Flexibility
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadados"),
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("criado em"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("atualizado em"))

    # History
    history = HistoricalRecords()

    class Meta:
        db_table = "craftsman_recipe"
        verbose_name = _("Receita")
        verbose_name_plural = _("Receitas")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["output_type", "output_id"]),
        ]

    def clean(self):
        super().clean()
        if self.output_quantity is not None and self.output_quantity <= 0:
            raise ValidationError({
                "output_quantity": _("Deve ser maior que zero.")
            })
        if self.steps and not isinstance(self.steps, list):
            raise ValidationError({
                "steps": _("Deve ser uma lista de nomes de etapas.")
            })
        if self.steps:
            for i, s in enumerate(self.steps):
                if not isinstance(s, str) or not s.strip():
                    raise ValidationError({
                        "steps": _(f"Etapa {i+1} deve ser uma string não-vazia.")
                    })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.output_quantity}x)"

    def get_steps(self) -> list[str]:
        """Get step names as a list of strings."""
        if self.steps:
            return list(self.steps)
        return []

    def get_step(self, name: str) -> dict | None:
        """Get step configuration by name."""
        if name in (self.steps or []):
            return {"name": name, "required": True}
        return None

    @property
    def last_step(self) -> str | None:
        """Get last step name."""
        steps = self.steps or []
        return steps[-1] if steps else None


class RecipeItem(models.Model):
    """
    Insumo de uma receita (método do coeficiente francês).

    Armazena a quantidade para a RECEITA BASE.
    O coeficiente é calculado dinamicamente com base na demanda.

    Referência: http://techno.boulangerie.free.fr/
    """

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("Receita"),
    )

    # Insumo (GenericForeignKey - agnostic!)
    # Pode ser: Product, outra Recipe (BOM multinível), MatériaPrima...
    item_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Tipo de Insumo"),
        help_text=_("Tipo do material de entrada"),
    )
    item_id = models.PositiveIntegerField(
        verbose_name=_("ID do Insumo"),
        help_text=_("ID do material de entrada"),
    )
    item = GenericForeignKey("item_type", "item_id")

    # Categoria para agrupamento e filtros
    category = models.ForeignKey(
        IngredientCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recipe_items",
        verbose_name=_("Categoria"),
        help_text=_("Categoria para agrupamento (ex: Massa, Farinha)"),
    )

    # Quantidade para RECEITA BASE (método do coeficiente)
    # Ex: 0.680 L de água para receita que rende 1.955 kg
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        verbose_name=_("Quantidade"),
        help_text=_("Quantidade para receita base"),
    )
    unit = models.CharField(
        max_length=10,
        default="kg",
        verbose_name=_("Unidade"),
        help_text=_("kg, L, un, g..."),
    )

    # Where to get this material from
    position = models.ForeignKey(
        get_position_model_string(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Posição"),
        help_text=_("De onde buscar o material (opcional)"),
    )

    # Alternatives (e.g., butter OR margarine)
    is_alternative = models.BooleanField(
        default=False,
        verbose_name=_("É Alternativa"),
        help_text=_("Pode ser substituído por outro no grupo"),
    )
    alternative_group = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Grupo de Alternativas"),
        help_text=_("Nome do grupo (ex: gordura)"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Ativo"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Observações"),
    )

    class Meta:
        db_table = "craftsman_recipe_item"
        verbose_name = _("Ingrediente")
        verbose_name_plural = _("Ingredientes")
        ordering = ["recipe", "category", "id"]
        indexes = [
            models.Index(fields=["recipe"]),
            models.Index(fields=["item_type", "item_id"]),
            models.Index(fields=["category"]),
        ]
        unique_together = [["recipe", "item_type", "item_id"]]

    def __str__(self) -> str:
        unit_str = f" {self.unit}" if self.unit else ""
        return f"{self.item} ({self.quantity}{unit_str})"
