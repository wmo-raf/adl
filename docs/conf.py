import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

# -- Path setup --------------------------------------------------------------
DOCS_DIR = os.path.abspath(os.path.dirname(__file__))

sys.path.insert(0, os.path.join(DOCS_DIR, ".."))  # repo root
sys.path.insert(0, os.path.join(DOCS_DIR, "../adl/src"))  # adl package
sys.path.insert(0, DOCS_DIR)  # docs_settings.py

# -- Mock modules that require PostgreSQL/psycopg2 or other C extensions -----
# django-timescaledb imports django.contrib.postgres at module level which
# unconditionally loads psycopg2 — a C extension unavailable on ReadTheDocs.
# Mocking these modules before django.setup() prevents the import chain
# from failing.
MOCK_MODULES = [
    "psycopg2",
    "psycopg2.extensions",
    "psycopg2.errors",
    "psycopg2.sql",
    "psycopg",
    "django.contrib.postgres",
    "django.contrib.postgres.fields",
    "django.contrib.postgres.forms",
    "django.contrib.postgres.forms.ranges",
    "timescale",
    "timescale.db",
    "timescale.db.models",
    "timescale.db.models.models",
    "timescale.db.models.managers",
    "timescale.db.models.querysets",
    "timescale.db.models.expressions",
]

for mod in MOCK_MODULES:
    sys.modules[mod] = MagicMock()

# -- Django setup for autodoc ------------------------------------------------
import django

os.environ["DJANGO_SETTINGS_MODULE"] = "docs_settings"
django.setup()

# -- Project information -----------------------------------------------------

project = "Automated Data Loader (ADL)"
copyright = f"{datetime.now().year}, WMO Regional Office For Africa"
author = "Erick Otenyo"
release = "0.2.1"

on_rtd = os.environ.get("READTHEDOCS", None) == "True"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "myst_parser",
    "sphinx_wagtail_theme",
    "sphinxcontrib.mermaid",
    "sphinxcontrib_django",
]

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"
autoclass_content = "both"

intersphinx_mapping = {
    "python": (
        "https://docs.python.org/3/",
        None,
    ),
    "django": (
        "https://docs.djangoproject.com/en/stable/",
        "https://docs.djangoproject.com/en/stable/_objects/",
    ),
}

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "attrs_inline",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_wagtail_theme"
html_static_path = ["_static"]

html_theme_options = {
    "project_name": "Automated Data Loader (ADL)",
    "logo": "images/logo.svg",
    "logo_alt": "Automated Data Loader (ADL) Logo",
    "logo_height": 50,
    "logo_url": "/",
    "github_url": "https://github.com/wmo-raf/adl/blob/main/docs/",
    "footer_links": ",".join([
        "Github|https://github.com/wmo-raf/adl",
    ]),
}


def setup(app):
    app.add_css_file("css/custom.css")
