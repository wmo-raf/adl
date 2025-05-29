import os
from datetime import datetime

project = 'Automated Data Loader (ADL)'
copyright = f"{datetime.now().year}, WMO Regional Office For Africa"
author = 'Erick Otenyo'
release = '0.2.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

on_rtd = os.environ.get("READTHEDOCS", None) == "True"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "myst_parser",
    "sphinx_wagtail_theme",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output


html_theme = 'sphinx_wagtail_theme'
html_static_path = ['_static']

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
    app.add_css_file('css/custom.css')
