# Generated manually for CR2: WorkOrder.code via DB Sequence

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("craftsman", "0002_alter_historicalplan_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CodeSequence",
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
                    "prefix",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        verbose_name="Prefixo",
                    ),
                ),
                (
                    "last_value",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Último valor",
                    ),
                ),
            ],
            options={
                "verbose_name": "Sequência de Código",
                "verbose_name_plural": "Sequências de Código",
                "db_table": "craftsman_code_sequence",
            },
        ),
    ]
