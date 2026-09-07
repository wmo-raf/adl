# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Bring each plugin repo's docs/ into docs/plugins/ and regenerate the plugin
# index. Required before any build: index.md's toctree points at plugins/index.
# Use SOURCE=local (with PLUGINS_ROOT) to aggregate from sibling checkouts
# instead of cloning.
SOURCE       ?= git
PLUGINS_ROOT ?= ../../adl-plugins
PYTHON       ?= python3

plugins:
	@$(PYTHON) ../scripts/aggregate_plugin_docs.py --source $(SOURCE) --local-root $(PLUGINS_ROOT)

html: plugins
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help plugins html Makefile

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
