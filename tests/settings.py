"""
Django settings for Craftsman tests.

Includes all apps needed to run the full Craftsman test suite.
"""

SECRET_KEY = "test-secret-key-for-craftsman-tests"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "taggit",
    "simple_history",
    "rest_framework",
    "offerman",
    "stockman",
    "craftsman",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROOT_URLCONF = "craftsman.tests.test_api_urls"

USE_TZ = True
TIME_ZONE = "America/Sao_Paulo"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

# Craftsman uses stockman.Position as default position model
CRAFTSMAN = {
    "POSITION_MODEL": "stockman.Position",
}

# Flat setting required by stockman migrations (swappable FK)
CRAFTSMAN_POSITION_MODEL = "stockman.Position"
