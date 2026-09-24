from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .models import User


class RoleRequiredMixin(AccessMixin):
    allowed_roles = (User.Role.ADMIN, User.Role.AGENT)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AssignedPropertyRequiredMixin:
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.role != User.Role.ADMIN and obj.assigned_agent_id != self.request.user.pk:
            raise PermissionDenied("You can only change properties assigned to you.")
        return obj


class AssignedInquiryRequiredMixin:
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.role != User.Role.ADMIN and obj.agent_id != self.request.user.pk:
            raise PermissionDenied("You can only change inquiries assigned to you.")
        return obj


class AssignedAppointmentRequiredMixin:
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.role != User.Role.ADMIN and obj.agent_id != self.request.user.pk:
            raise PermissionDenied("You can only change appointments assigned to you.")
        return obj


class AssignedTransactionRequiredMixin:
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.role != User.Role.ADMIN and obj.agent_id != self.request.user.pk:
            raise PermissionDenied("You can only change transactions assigned to you.")
        return obj
