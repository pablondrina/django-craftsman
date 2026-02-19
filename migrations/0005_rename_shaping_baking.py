"""
Rename shaping → processed_quantity and baking → produced_quantity.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("craftsman", "0004_recipe_item_and_dough_weight"),
    ]

    operations = [
        migrations.RenameField(
            model_name="workorder",
            old_name="shaping",
            new_name="processed_quantity",
        ),
        migrations.RenameField(
            model_name="workorder",
            old_name="baking",
            new_name="produced_quantity",
        ),
    ]
