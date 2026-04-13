import os
import sys
from datetime import datetime

# -- Path setup --------------------------------------------------------------
DOCS_DIR = os.path.abspath(os.path.dirname(__file__))

sys.path.insert(0, os.path.join(DOCS_DIR, ".."))  # repo root
sys.path.insert(0, os.path.join(DOCS_DIR, "../adl/src"))  # adl package
sys.path.insert(0, DOCS_DIR)  # docs_settings.py

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
