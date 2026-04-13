"""
Minimal Django settings for the Sphinx documentation build.

This file exists solely so that autodoc can import ADL's modules without
needing a running database, Redis instance, or any environment variables.
It is never used at runtime.

"""

SECRET_KEY = "docs-build-only-not-a-real-secret"

DEBUG = False

INSTALLED_APPS = [
    # Django core — required for model imports to resolve
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.gis",
    
    # Wagtail — required because ADL models use Wagtail panels, snippets, etc.
    "wagtail.contrib.settings",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    
    # Third-party deps ADL models import at module level
    "polymorphic",
    "django_countries",
    "wagtailgeowidget",
    "wagtail_modeladmin",
    "rest_framework",
    "rest_framework_api_key",
    "rest_framework_simplejwt",
    "oauth2_provider",
    "timescale",
    "django_celery_beat",
    "django_celery_results",
    "django_eventstream",
    "drf_spectacular",
    "allauth",
    "allauth.account",
    "channels",
    "wagtailiconchooser",
    "wagtailfontawesomesvg",
    "enum_intflagfield",
    
    # ADL apps
    "adl.core",
    "adl.monitoring",
]

# Use a minimal in-memory SQLite database so Django's app registry
# initialises without requiring PostgreSQL/PostGIS/TimescaleDB
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Required by wagtail and django.contrib.staticfiles
STATIC_URL = "/static/"
MEDIA_URL = "/media/"

# Required by Wagtail
WAGTAIL_SITE_NAME = "ADL Docs"

# Suppress warnings about missing secret key length etc.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Timezone
USE_TZ = True
TIME_ZONE = "UTC"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
