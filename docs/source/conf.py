# Configuration file for the Sphinx documentation builder.

import os
import sys

# Add autish package to path for autodoc
sys.path.insert(0, os.path.abspath("../../autish"))

# -- Project information -----------------------------------------------------
project = "autish"
copyright = "2024, autish contributors"
author = "autish contributors"

# The full version, including alpha/beta/rc tags
release = "0.0.1"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# MyST configuration
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_image",
    "linkify",
    "substitution",
    "tasklist",
]

# -- Options for HTML output -------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

# -- Intersphinx mapping -----------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "typer": ("https://typer.tiangolo.com/", None),
    "rich": ("https://rich.readthedocs.io/en/latest/", None),
}

# -- Autodoc configuration ---------------------------------------------------
autodoc_member_order = "bysource"
autodoc_typehints = "description"
