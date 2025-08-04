from django.contrib.admin.utils import quote
from django.urls import reverse
from django.utils.functional import cached_property, classproperty
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.views.bulk_action import BulkAction
from wagtail.admin.views.generic import BeforeAfterHookMixin
from wagtail.models import ReferenceIndex
from wagtail.snippets.permissions import get_permission_name

from ..viewsets import ADLET_MODELS


class AdletDeleteBulkAction(BeforeAfterHookMixin, BulkAction):
    display_name = _("Delete")
    action_type = "delete"
    aria_label = _("Delete selected items")
    template_name = "wagtailsnippets/bulk_actions/confirm_bulk_delete.html"
    action_priority = 30
    classes = {"serious"}
    
    @classproperty
    def models(self):
        return ADLET_MODELS
    
    @cached_property
    def _actionable_objects(self):
        # Cache the actionable objects so that we can use them early in the
        # dispatch() method, and reuse it later when needed. We don't name this
        # property "actionable_objects" because the method returns a tuple of
        # `(objects, {"items_with_no_access": items_with_no_access})` and the base
        # class assigns the `objects` to self.actionable_objects.
        return super().get_actionable_objects()
    
    def get_actionable_objects(self):
        return self._actionable_objects
    
    # Run the snippet deletion hooks that we've had since before bulk actions
    # were introduced.
    # These are different from the base bulk action hooks that are run by
    # __run_{before,after}_hooks(), as those are only called in form_valid().
    # Here, we make use of the BeforeAfterHookMixin to run the before hook at
    # the beginning of dispatch(), and the after hook at the end of form_valid(),
    # which is how the delete-multiple view for snippets used to work.
    
    def run_before_hook(self):
        # The method returns a tuple of
        # `(objects, {"items_with_no_access": items_with_no_access})`, hence [0]
        objects = self.get_actionable_objects()[0]
        return self.run_hook("before_delete_adlet", self.request, objects)
    
    def run_after_hook(self):
        objects = self.get_actionable_objects()[0]
        return self.run_hook("after_delete_adlet", self.request, objects)
    
    def check_perm(self, adlet):
        if getattr(self, "can_delete_items", None) is None:
            # since adlet permissions are not enforced per object, makes sense to just check once per model request
            self.can_delete_items = self.request.user.has_perm(
                get_permission_name("delete", self.model)
            )
        return self.can_delete_items
    
    @classmethod
    def execute_action(cls, objects, user=None, **kwargs):
        kwargs["self"].model.objects.filter(
            pk__in=[adlet.pk for adlet in objects]
        ).delete()
        return len(objects), 0
    
    def get_context_data(self, **kwargs):
        
        kwargs.update(
            {
                "model_opts": self.model._meta,
                "header_icon": self.model.adlet_viewset.icon,
            }
        )
        
        context = super().get_context_data(**kwargs)
        
        # Add usage information to the context only if there is a single item
        if len(context["items"]) == 1:
            item_context = context["items"][0]
            item = item_context["item"]
            item_context.update(
                {
                    "usage_count": (
                        ReferenceIndex.get_grouped_references_to(item).count()
                    ),
                    "usage_url": reverse(
                        item.adlet_viewset.get_url_name("usage"),
                        args=(quote(item.pk),),
                    ),
                }
            )
        return context
    
    def get_success_message(self, num_parent_objects, num_child_objects):
        if num_parent_objects == 1:
            return _("%(model_name)s '%(object)s' deleted.") % {
                "model_name": capfirst(self.model._meta.verbose_name),
                "object": self.actionable_objects[0],
            }
        else:
            return ngettext(
                "%(count)d %(model_name)s deleted.",
                "%(count)d %(model_name)s deleted.",
                num_parent_objects,
            ) % {
                "model_name": capfirst(self.model._meta.verbose_name_plural),
                "count": num_parent_objects,
            }
    
    def object_context(self, adlet):
        return {
            "item": adlet,
            "edit_url": AdminURLFinder(self.request.user).get_edit_url(adlet),
        }
    
    def get_execution_context(self):
        return {**super().get_execution_context(), "self": self}
