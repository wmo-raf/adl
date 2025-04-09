from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework_api_key.permissions import HasAPIKey


class HasAPIKeyOrIsAuthenticated(BasePermission):
    def has_permission(self, request, view):
        return HasAPIKey().has_permission(request, view) or IsAuthenticated().has_permission(request, view)
