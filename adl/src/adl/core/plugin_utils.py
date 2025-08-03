import importlib.metadata
import inspect

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def get_plugin_metadata(plugin_instance):
    """
    Given an instance or class, return the package metadata of the installed package it belongs to.
    """
    # Get the module where the plugin is defined
    module = inspect.getmodule(plugin_instance)
    if not module:
        return {"error": "Could not determine module for the plugin."}
    
    # Get the top-level package name
    top_level_module = module.__name__.split('.')[0]
    
    url_validator = URLValidator()
    
    try:
        dist = importlib.metadata.distribution(top_level_module)
        meta = dist.metadata
        home_page = meta.get("Home-page")
        
        if home_page:
            try:
                url_validator(home_page)
            except ValidationError:
                home_page = None
        
        return {
            "name": meta.get("Name"),
            "version": meta.get("Version"),
            "summary": meta.get("Summary"),
            "author": meta.get("Author"),
            "author_email": meta.get("Author-email"),
            "license": meta.get("License"),
            "home_page": home_page
        }
    except importlib.metadata.PackageNotFoundError:
        return {"error": f"Package metadata for '{top_level_module}' not found."}
