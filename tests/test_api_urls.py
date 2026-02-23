"""
URL configuration for Craftsman API tests.

Used as ROOT_URLCONF in test settings via @pytest.mark.urls.
"""

from django.urls import include, path

urlpatterns = [
    path("api/craftsman/", include("craftsman.api.urls")),
]
