import os
import sys
from datetime import datetime

# -- Path setup --------------------------------------------------------------
DOCS_DIR = os.path.abspath(os.path.dirname(__file__))

sys.path.insert(0, os.path.join(DOCS_DIR, ".."))  # repo root
sys.path.insert(0, os.path.join(DOCS_DIR, "../adl/src"))  # adl package
sys.path.insert(0, DOCS_DIR)  # docs_settings.py

# -- Autodoc mock imports ----------------------------------------------------
# Sphinx mocks these before importing any modules for autodoc.
# This handles C extensions and packages unavailable on ReadTheDocs
# (psycopg2, timescale, GDAL-dependent packages etc.) without the
# metaclass and __all__ issues caused by unittest.mock.
autodoc_mock_imports = [
    "psycopg2",
    "psycopg",
    "timescale",
    "django.contrib.postgres",
    "django_eventstream",
    "channels",
    "daphne",
    "wagtailgeowidget",
    "wagtailiconchooser",
    "wagtailfontawesomesvg",
    "enum_intflagfield",
    "timezone_field",
    "polymorphic",
    "django_countries",
    "modelcluster",
    "oauth2_provider",
    "rest_framework",
    "rest_framework_api_key",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "allauth",
]

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

# Keep methods in the order they appear in source
autodoc_member_order = "bysource"

# Render type hints in the parameter description block
autodoc_typehints = "description"

# Only add type info for parameters that have a docstring entry
autodoc_typehints_description_target = "documented"

# Include __init__ docstrings alongside class docstrings
autoclass_content = "both"

# -- Intersphinx -------------------------------------------------------------

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

# -- MyST parser -------------------------------------------------------------

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Allow {eval-rst} fences in .md files so autoclass/automethod directives
# embedded in Markdown pages render correctly
myst_enable_extensions = [
    "attrs_inline",
]

# -- General -----------------------------------------------------------------

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- HTML output -------------------------------------------------------------

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
