import os
import sys
from datetime import datetime

import django

# -- Path setup --------------------------------------------------------------
# Make the adl package importable so autodoc can import it
sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(0, os.path.abspath("../adl/src"))
sys.path.insert(0, os.path.abspath("."))

# -- Django setup for autodoc ------------------------------------------------
# autodoc must import ADL's modules to read their docstrings. Django models
# won't import without a configured settings module, so we point at a minimal
# docs-only settings file that has no database, Redis, or external service
# dependencies. See docs/settings.py.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docs_settings")
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

# autodoc settings
# Keep methods in the order they appear in source rather than alphabetically
autodoc_member_order = "bysource"

# Render type hints as part of the parameter description rather than
# cluttering the signature line
autodoc_typehints = "description"

# Only add type information for parameters that have a docstring entry,
# avoiding noise for internal parameters that aren't documented
autodoc_typehints_description_target = "documented"

# Do not skip __init__ — some ADL base classes have meaningful __init__ docs
autoclass_content = "both"

# intersphinx: resolves cross-references to Django and Python docs
# e.g. :class:`~django.db.models.Model` or :exc:`NotImplementedError`
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

# myst_parser settings
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Allow {eval-rst} fences in .md files so autoclass/automethod directives
# embedded in Markdown pages render correctly
myst_enable_extensions = [
    "attrs_inline",
]

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
