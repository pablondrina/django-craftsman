"""
Craftsman API URLs.

Include this in your project's urlpatterns:

    path('api/craftsman/', include('craftsman.api.urls')),
"""

from rest_framework.routers import DefaultRouter

from .views import RecipeViewSet, PlanViewSet, WorkOrderViewSet

router = DefaultRouter()
router.register("recipes", RecipeViewSet)
router.register("plans", PlanViewSet)
router.register("work-orders", WorkOrderViewSet)

urlpatterns = router.urls
