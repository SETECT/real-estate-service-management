from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Appointment, Contract, Customer, Inquiry, Payment, Property, Transaction, User
from .forms import ContractForm, PaymentForm, TransactionForm




class AdminRoleOnlyMixin:
    def has_module_permission(self, request):
        return request.user.role == User.Role.ADMIN

    def has_view_permission(self, request, obj=None):
        return request.user.role == User.Role.ADMIN

    def has_add_permission(self, request):
        return request.user.role == User.Role.ADMIN

    def has_change_permission(self, request, obj=None):
        return request.user.role == User.Role.ADMIN

    def has_delete_permission(self, request, obj=None):
        return request.user.role == User.Role.ADMIN


@admin.register(User)
class RESMSUserAdmin(AdminRoleOnlyMixin, UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("RESMS", {"fields": ("role", "created_at", "updated_at")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("RESMS", {"fields": ("role",)}),)
    readonly_fields = ("created_at", "updated_at")
    list_display = ("username", "email", "role", "is_staff")


@admin.register(Contract)
class ContractAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    form = ContractForm
    list_display = ("contract_number", "transaction", "customer", "contract_type", "amount", "status")
    list_filter = ("status", "contract_type")
    search_fields = ("contract_number", "customer__full_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    form = PaymentForm
    list_display = ("id", "transaction", "customer", "amount", "payment_date", "payment_method", "status")
    list_filter = ("status", "payment_method")
    search_fields = ("transaction__transaction_code", "customer__full_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Property)
class PropertyAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    list_display = ("property_code", "name", "property_type", "location", "price", "status", "owner", "assigned_agent")
    list_filter = ("status", "property_type")
    search_fields = ("property_code", "name", "location")
    readonly_fields = ("property_code", "created_at", "updated_at")


@admin.register(Customer)
class CustomerAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    list_display = ("customer_code", "full_name", "phone", "email", "customer_type")
    list_filter = ("customer_type",)
    search_fields = ("customer_code", "full_name", "phone", "email")
    readonly_fields = ("customer_code", "created_at", "updated_at")


@admin.register(Inquiry)
class InquiryAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    list_display = ("inquiry_code", "customer", "property", "agent", "inquiry_date", "status")
    list_filter = ("status", "agent")
    search_fields = ("inquiry_code", "customer__full_name", "property__name", "message")
    readonly_fields = ("inquiry_code", "created_at", "updated_at")


@admin.register(Appointment)
class AppointmentAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    list_display = ("appointment_code", "customer", "property", "agent", "appointment_date", "appointment_time", "status")
    list_filter = ("status", "agent", "appointment_date")
    search_fields = ("appointment_code", "customer__full_name", "property__name", "notes")
    readonly_fields = ("appointment_code", "created_at", "updated_at")


@admin.register(Transaction)
class TransactionAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    form = TransactionForm
    list_display = ("transaction_code", "customer", "property", "agent", "transaction_type", "amount", "status")
    list_filter = ("transaction_type", "status")
    search_fields = ("transaction_code", "customer__full_name", "property__name")
    readonly_fields = ("transaction_code", "created_at", "updated_at")
