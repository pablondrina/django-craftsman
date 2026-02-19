"""
Migration for Craftsman v2.3.

Changes:
- Add Plan and PlanItem models
- Add new fields to Recipe (production_stages, work_center, lead_time_days)
- Add new fields to WorkOrder (plan_item)
- Add history tracking to models
"""

import django.db.models.deletion
import simple_history.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("craftsman", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("stockman", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ══════════════════════════════════════════════════════════════
        # PLAN MODEL
        # ══════════════════════════════════════════════════════════════
        migrations.CreateModel(
            name="Plan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "date",
                    models.DateField(unique=True, verbose_name="Data de Produção"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("approved", "Aprovado"),
                            ("scheduled", "Agendado"),
                            ("completed", "Concluído"),
                        ],
                        default="draft",
                        max_length=20,
                        verbose_name="Status",
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Observações")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Plano de Produção",
                "verbose_name_plural": "Planos de Produção",
                "db_table": "craftsman_plan",
                "ordering": ["-date"],
            },
        ),
        # ══════════════════════════════════════════════════════════════
        # PLAN ITEM MODEL
        # ══════════════════════════════════════════════════════════════
        migrations.CreateModel(
            name="PlanItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0"),
                        max_digits=10,
                        verbose_name="Quantidade Aprovada",
                    ),
                ),
                (
                    "priority",
                    models.PositiveSmallIntegerField(
                        default=50, verbose_name="Prioridade"
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Observações")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "destination",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="plan_items",
                        to="stockman.position",
                        verbose_name="Destino",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="craftsman.plan",
                        verbose_name="Plano",
                    ),
                ),
                (
                    "recipe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="plan_items",
                        to="craftsman.recipe",
                        verbose_name="Receita",
                    ),
                ),
            ],
            options={
                "verbose_name": "Item do Plano",
                "verbose_name_plural": "Itens do Plano",
                "db_table": "craftsman_plan_item",
                "ordering": ["-priority", "created_at"],
                "unique_together": {("plan", "recipe")},
            },
        ),
        # ══════════════════════════════════════════════════════════════
        # RECIPE UPDATES
        # ══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name="recipe",
            name="production_stages",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Lista de etapas: ['Mixing', 'Shaping', 'Baking']",
                verbose_name="Etapas de Produção",
            ),
        ),
        migrations.AddField(
            model_name="recipe",
            name="work_center",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="recipes",
                to="stockman.position",
                verbose_name="Centro de Trabalho",
            ),
        ),
        migrations.AddField(
            model_name="recipe",
            name="lead_time_days",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Dias de antecedência para iniciar produção",
                verbose_name="Lead Time (dias)",
            ),
        ),
        migrations.AddField(
            model_name="recipe",
            name="notes",
            field=models.TextField(blank=True, verbose_name="Observações"),
        ),
        # ══════════════════════════════════════════════════════════════
        # RECIPE INPUT UPDATES
        # ══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name="recipeinput",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="Ativo"),
        ),
        migrations.AddField(
            model_name="recipeinput",
            name="notes",
            field=models.TextField(blank=True, verbose_name="Observações"),
        ),
        migrations.AlterUniqueTogether(
            name="recipeinput",
            unique_together={("recipe", "input_type", "input_id")},
        ),
        # ══════════════════════════════════════════════════════════════
        # WORK ORDER UPDATES
        # ══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name="workorder",
            name="plan_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="work_orders_set",
                to="craftsman.planitem",
                verbose_name="Item do Plano",
            ),
        ),
        # Rename fields to match v2.3 spec
        migrations.RenameField(
            model_name="workorder",
            old_name="quantity",
            new_name="planned_quantity",
        ),
        migrations.RenameField(
            model_name="workorder",
            old_name="actual_start",
            new_name="started_at",
        ),
        migrations.RenameField(
            model_name="workorder",
            old_name="actual_end",
            new_name="completed_at",
        ),
        # Make code optional (auto-generated)
        migrations.AlterField(
            model_name="workorder",
            name="code",
            field=models.CharField(
                blank=True,
                max_length=50,
                unique=True,
                verbose_name="Código",
            ),
        ),
        # Add index for plan_item
        migrations.AddIndex(
            model_name="workorder",
            index=models.Index(fields=["plan_item"], name="craftsman_w_plan_it_idx"),
        ),
        # ══════════════════════════════════════════════════════════════
        # HISTORICAL RECORDS
        # ══════════════════════════════════════════════════════════════
        migrations.CreateModel(
            name="HistoricalPlan",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("date", models.DateField(verbose_name="Data de Produção")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("approved", "Aprovado"),
                            ("scheduled", "Agendado"),
                            ("completed", "Concluído"),
                        ],
                        default="draft",
                        max_length=20,
                        verbose_name="Status",
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Observações")),
                ("created_at", models.DateTimeField(blank=True, editable=False)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical Plano de Produção",
                "verbose_name_plural": "historical Planos de Produção",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalRecipe",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "output_id",
                    models.PositiveIntegerField(verbose_name="ID do Produto"),
                ),
                ("code", models.SlugField(verbose_name="Código")),
                ("name", models.CharField(max_length=200, verbose_name="Nome")),
                (
                    "output_quantity",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("1"),
                        max_digits=10,
                        verbose_name="Quantidade de Saída",
                    ),
                ),
                (
                    "lead_time_days",
                    models.PositiveSmallIntegerField(
                        default=0, verbose_name="Lead Time (dias)"
                    ),
                ),
                (
                    "production_stages",
                    models.JSONField(
                        blank=True, default=list, verbose_name="Etapas de Produção"
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativa")),
                (
                    "duration_minutes",
                    models.PositiveIntegerField(
                        blank=True, null=True, verbose_name="Duração (minutos)"
                    ),
                ),
                ("notes", models.TextField(blank=True, verbose_name="Observações")),
                (
                    "metadata",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="Metadados"
                    ),
                ),
                ("created_at", models.DateTimeField(blank=True, editable=False)),
                ("updated_at", models.DateTimeField(blank=True, editable=False)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "output_type",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "work_center",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="stockman.position",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical Receita",
                "verbose_name_plural": "historical Receitas",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalWorkOrder",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        blank=True, db_index=True, max_length=50, verbose_name="Código"
                    ),
                ),
                (
                    "planned_quantity",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        verbose_name="Quantidade Planejada",
                    ),
                ),
                (
                    "actual_quantity",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        verbose_name="Quantidade Real",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("in_progress", "Em Produção"),
                            ("paused", "Pausado"),
                            ("completed", "Concluído"),
                            ("cancelled", "Cancelado"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                        verbose_name="Status",
                    ),
                ),
                (
                    "scheduled_start",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("scheduled_end", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("source_id", models.PositiveIntegerField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(blank=True, editable=False)),
                ("updated_at", models.DateTimeField(blank=True, editable=False)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "destination",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="stockman.position",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="stockman.position",
                    ),
                ),
                (
                    "plan_item",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="craftsman.planitem",
                    ),
                ),
                (
                    "recipe",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="craftsman.recipe",
                    ),
                ),
                (
                    "source_type",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical Ordem de Produção",
                "verbose_name_plural": "historical Ordens de Produção",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
