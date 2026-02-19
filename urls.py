"""
Craftsman URL Configuration.
"""

from django.urls import path

from craftsman.views import daily_ingredients_view

app_name = "craftsman"

urlpatterns = [
    path("ingredients/", daily_ingredients_view, name="daily_ingredients"),
]
