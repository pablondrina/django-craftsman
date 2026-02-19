"""
Set decimal_places=0 for quantity fields.
Quantities display as integers (60) not decimals (60,00).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("craftsman", "0006_revert_decimal_places"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workorder",
            name="planned_quantity",
            field=models.DecimalField(
                decimal_places=0,
                help_text="Quantidade planejada a produzir",
                max_digits=10,
                verbose_name="Planejado",
            ),
        ),
        migrations.AlterField(
            model_name="workorder",
            name="actual_quantity",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                help_text="Quantidade efetivamente produzida",
                max_digits=10,
                null=True,
                verbose_name="Quantidade Real",
            ),
        ),
        migrations.AlterField(
            model_name="workorder",
            name="mixing",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                help_text="Quantidade de massa preparada",
                max_digits=10,
                null=True,
                verbose_name="Massa para",
            ),
        ),
        migrations.AlterField(
            model_name="workorder",
            name="processed_quantity",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                help_text="Quantidade após processamento/modelagem",
                max_digits=10,
                null=True,
                verbose_name="Processado",
            ),
        ),
        migrations.AlterField(
            model_name="workorder",
            name="produced_quantity",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                help_text="Quantidade final produzida",
                max_digits=10,
                null=True,
                verbose_name="Produzido",
            ),
        ),
        migrations.AlterField(
            model_name="planitem",
            name="quantity",
            field=models.DecimalField(
                decimal_places=0,
                default=0,
                help_text="Quantidade aprovada para produzir",
                max_digits=10,
                verbose_name="Aprovado",
            ),
        ),
    ]
