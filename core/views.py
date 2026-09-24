from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .forms import AppointmentForm, ContractForm, CustomerForm, InquiryForm, PaymentForm, PropertyForm, ReportFilterForm, TransactionForm
from .mixins import AssignedAppointmentRequiredMixin, AssignedInquiryRequiredMixin, AssignedPropertyRequiredMixin, AssignedTransactionRequiredMixin, RoleRequiredMixin
from .models import Appointment, Contract, Customer, Inquiry, Payment, Property, Transaction, User


class DashboardView(RoleRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = dict(Property.objects.values("status").annotate(total=Count("pk")).values_list("status", "total"))
        now = timezone.localtime()
        upcoming = Appointment.objects.filter(status=Appointment.Status.SCHEDULED).filter(
            Q(appointment_date__gt=now.date()) | Q(appointment_date=now.date(), appointment_time__gte=now.time())
        ).count()
        paid_total = Payment.objects.filter(status=Payment.Status.PAID).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        stats = {
            "total_properties": sum(counts.values()),
            "available_properties": counts.get(Property.Status.AVAILABLE, 0),
            "sold_properties": counts.get(Property.Status.SOLD, 0),
            "rented_properties": counts.get(Property.Status.RENTED, 0),
            "total_customers": Customer.objects.count(),
            "total_inquiries": Inquiry.objects.count(),
            "upcoming_appointments": upcoming,
            "total_transactions": Transaction.objects.count(),
            "total_payments": Payment.objects.count(),
            "paid_total": paid_total,
        }
        labels = ["Total properties", "Available properties", "Sold properties", "Rented properties", "Total customers", "Total inquiries", "Upcoming appointments", "Total transactions", "Recorded payments", "Sum of Paid payments"]
        context.update(stats=stats, cards=list(zip(labels, list(stats.values())[:-1] + [f"{paid_total:,.2f}"])),
                       chart_labels=list(Property.Status.labels), chart_values=[counts.get(value, 0) for value in Property.Status.values])
        return context


class ReportListView(RoleRequiredMixin, TemplateView):
    template_name = "core/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ReportFilterForm(self.request.GET)
        properties = Property.objects.select_related("owner")
        transactions = Transaction.objects.select_related("customer", "property", "agent")
        payments = Payment.objects.select_related("customer", "transaction")
        if form.is_valid():
            data = form.cleaned_data
            query = data.get("q")
            if query:
                properties = properties.filter(Q(name__icontains=query) | Q(location__icontains=query) | Q(owner__full_name__icontains=query))
                transactions = transactions.filter(Q(transaction_code__icontains=query) | Q(customer__full_name__icontains=query) | Q(property__name__icontains=query) | Q(agent__username__icontains=query))
                payments = payments.filter(Q(customer__full_name__icontains=query) | Q(transaction__transaction_code__icontains=query) | Q(transaction__property__name__icontains=query))
            for field, lookup in (("property_type", "property_type"), ("property_status", "status")):
                if data.get(field):
                    properties = properties.filter(**{lookup: data[field]})
            for field, lookup in (("transaction_type", "transaction_type"), ("transaction_status", "status")):
                if data.get(field):
                    transactions = transactions.filter(**{lookup: data[field]})
            for field, lookup in (("payment_method", "payment_method"), ("payment_status", "status")):
                if data.get(field):
                    payments = payments.filter(**{lookup: data[field]})
            for field, comparison in (("date_from", "gte"), ("date_to", "lte")):
                if data.get(field):
                    transactions = transactions.filter(**{f"transaction_date__{comparison}": data[field]})
                    payments = payments.filter(**{f"payment_date__{comparison}": data[field]})
        else:
            properties, transactions, payments = properties.none(), transactions.none(), payments.none()
        context["form"] = form
        for name, records in (("properties", properties), ("transactions", transactions), ("payments", payments)):
            page_key = f"{name}_page"
            page = Paginator(records, 20).get_page(self.request.GET.get(page_key))
            filters = self.request.GET.copy()
            filters.pop(page_key, None)
            context[name] = page
            context[f"{name}_pagination"] = {"page_obj": page, "is_paginated": page.has_other_pages(), "filter_query": filters.urlencode(), "page_key": page_key, "anchor": name}
        return context


class LinkedRecordContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        kind = self.model._meta.model_name
        context.update(kind=kind, title=self.model._meta.verbose_name.title(),
                       list_url=reverse_lazy(f"core:{kind}_list"), create_url=reverse_lazy(f"core:{kind}_create"))
        if getattr(self, "object", None):
            context.update(update_url=reverse_lazy(f"core:{kind}_update", kwargs={"pk": self.object.pk}),
                           delete_url=reverse_lazy(f"core:{kind}_delete", kwargs={"pk": self.object.pk}))
        return context


class AssignedLinkedRecordMixin:
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.role != User.Role.ADMIN and obj.transaction.agent_id != self.request.user.pk:
            raise PermissionDenied("You can only change records for your assigned transactions.")
        return obj


class LinkedRecordListView(RoleRequiredMixin, LinkedRecordContextMixin, ListView):
    template_name = "core/linked/list.html"
    paginate_by = 20

    def get_queryset(self):
        records = super().get_queryset().select_related("transaction__agent", "customer")
        query = self.request.GET.get("q", "").strip()
        if query:
            search = Q(customer__full_name__icontains=query) | Q(transaction__transaction_code__icontains=query)
            if self.model == Contract:
                search |= Q(contract_number__icontains=query)
            records = records.filter(search)
        if self.request.GET.get("status"):
            records = records.filter(status=self.request.GET["status"])
        return records

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(status_choices=self.model.Status.choices, filter_query=filters.urlencode())
        return context


class LinkedRecordFormMixin(LinkedRecordContextMixin):
    template_name = "core/linked/form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_initial(self):
        initial = super().get_initial()
        transaction_id = self.request.GET.get("transaction")
        if transaction_id and not getattr(self, "object", None):
            if not transaction_id.isdecimal() or len(transaction_id) > 18:
                return initial
            source = get_object_or_404(Transaction, pk=transaction_id)
            if self.request.user.role != User.Role.ADMIN and source.agent_id != self.request.user.pk:
                raise PermissionDenied
            initial.update(transaction=source.pk, customer=source.customer_id, property=source.property_id,
                           contract_type=source.transaction_type, amount=source.amount,
                           start_date=source.start_date, end_date=source.end_date)
            if not source.start_date:
                initial.pop("start_date")
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.model._meta.verbose_name.title()} saved successfully.")
        return response


class ContractListView(LinkedRecordListView):
    model = Contract


class ContractDetailView(RoleRequiredMixin, LinkedRecordContextMixin, DetailView):
    model = Contract
    template_name = "core/linked/detail.html"


class ContractCreateView(RoleRequiredMixin, LinkedRecordFormMixin, CreateView):
    model = Contract
    form_class = ContractForm


class ContractUpdateView(RoleRequiredMixin, AssignedLinkedRecordMixin, LinkedRecordFormMixin, UpdateView):
    model = Contract
    form_class = ContractForm


class ContractDeleteView(RoleRequiredMixin, AssignedLinkedRecordMixin, LinkedRecordContextMixin, DeleteView):
    model = Contract
    template_name = "core/linked/confirm_delete.html"
    success_url = reverse_lazy("core:contract_list")
    http_method_names = ["get", "post", "head", "options"]


class PaymentListView(LinkedRecordListView):
    model = Payment


class PaymentDetailView(RoleRequiredMixin, LinkedRecordContextMixin, DetailView):
    model = Payment
    template_name = "core/linked/detail.html"


class PaymentCreateView(RoleRequiredMixin, LinkedRecordFormMixin, CreateView):
    model = Payment
    form_class = PaymentForm


class PaymentUpdateView(RoleRequiredMixin, AssignedLinkedRecordMixin, LinkedRecordFormMixin, UpdateView):
    model = Payment
    form_class = PaymentForm


class PaymentDeleteView(RoleRequiredMixin, AssignedLinkedRecordMixin, LinkedRecordContextMixin, DeleteView):
    model = Payment
    template_name = "core/linked/confirm_delete.html"
    success_url = reverse_lazy("core:payment_list")
    http_method_names = ["get", "post", "head", "options"]


class UserListView(RoleRequiredMixin, ListView):
    allowed_roles = (User.Role.ADMIN,)
    model = User
    template_name = "core/users/user_list.html"
    paginate_by = 20

    def get_queryset(self):
        queryset = User.objects.order_by("username")
        query = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "")
        if query:
            queryset = queryset.filter(Q(username__icontains=query) | Q(email__icontains=query))
        if role:
            queryset = queryset.filter(role=role)
        return queryset


class PropertyListView(RoleRequiredMixin, ListView):
    model = Property
    template_name = "core/properties/property_list.html"
    context_object_name = "properties"
    paginate_by = 20

    def get_queryset(self):
        queryset = Property.objects.select_related("assigned_agent", "owner")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(location__icontains=query))
        for field in ("status", "property_type"):
            value = self.request.GET.get(field, "")
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(
            status_choices=Property.Status.choices,
            type_choices=Property.PropertyType.choices,
            filter_query=filters.urlencode(),
        )
        return context


class PropertyDetailView(RoleRequiredMixin, DetailView):
    queryset = Property.objects.select_related("assigned_agent", "owner")
    template_name = "core/properties/property_detail.html"


class PropertyFormMixin:
    model = Property
    form_class = PropertyForm
    template_name = "core/properties/property_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        if self.request.user.role == User.Role.AGENT:
            form.instance.assigned_agent = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Property saved successfully.")
        return response


class PropertyCreateView(RoleRequiredMixin, PropertyFormMixin, CreateView):
    pass


class PropertyUpdateView(RoleRequiredMixin, AssignedPropertyRequiredMixin, PropertyFormMixin, UpdateView):
    pass


class PropertyDeleteView(RoleRequiredMixin, AssignedPropertyRequiredMixin, DeleteView):
    model = Property
    template_name = "core/properties/property_confirm_delete.html"
    success_url = reverse_lazy("core:property_list")
    http_method_names = ["get", "post", "head", "options"]

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This property has linked records and cannot be deleted.")
            return HttpResponseRedirect(self.object.get_absolute_url())
        messages.success(self.request, "Property deleted successfully.")
        return response


class CustomerListView(RoleRequiredMixin, ListView):
    model = Customer
    template_name = "core/customers/customer_list.html"
    context_object_name = "customers"
    paginate_by = 20

    def get_queryset(self):
        queryset = Customer.objects.all()
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query)
            )
        customer_type = self.request.GET.get("customer_type", "")
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(type_choices=Customer.CustomerType.choices, filter_query=filters.urlencode())
        return context


class CustomerDetailView(RoleRequiredMixin, DetailView):
    model = Customer
    template_name = "core/customers/customer_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["properties"] = self.object.properties.all()
        return context


class CustomerFormMixin:
    # Customers are shared contacts with no assigned-agent field.
    allowed_roles = (User.Role.ADMIN,)
    model = Customer
    form_class = CustomerForm
    template_name = "core/customers/customer_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Customer saved successfully.")
        return response


class CustomerCreateView(CustomerFormMixin, RoleRequiredMixin, CreateView):
    pass


class CustomerUpdateView(CustomerFormMixin, RoleRequiredMixin, UpdateView):
    pass


class CustomerDeleteView(RoleRequiredMixin, DeleteView):
    allowed_roles = (User.Role.ADMIN,)
    model = Customer
    template_name = "core/customers/customer_confirm_delete.html"
    success_url = reverse_lazy("core:customer_list")
    http_method_names = ["get", "post", "head", "options"]

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This customer has linked records and cannot be deleted.")
            return HttpResponseRedirect(self.object.get_absolute_url())
        messages.success(self.request, "Customer deleted successfully.")
        return response


class InquiryListView(RoleRequiredMixin, ListView):
    model = Inquiry
    template_name = "core/inquiries/inquiry_list.html"
    context_object_name = "inquiries"
    paginate_by = 20

    def get_queryset(self):
        queryset = Inquiry.objects.select_related("customer", "property", "agent")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(inquiry_code__icontains=query) | Q(customer__full_name__icontains=query)
                | Q(property__name__icontains=query) | Q(message__icontains=query)
            )
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        agent = self.request.GET.get("agent", "")
        if agent == "unassigned":
            queryset = queryset.filter(agent__isnull=True)
        elif agent:
            # Validate against choices rather than passing arbitrary text to an ID lookup.
            valid_ids = {str(pk) for pk in User.objects.filter(role=User.Role.AGENT).values_list("pk", flat=True)}
            queryset = queryset.filter(agent_id=agent) if agent in valid_ids else queryset.none()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(
            status_choices=Inquiry.Status.choices,
            agents=User.objects.filter(role=User.Role.AGENT).order_by("username"),
            filter_query=filters.urlencode(),
        )
        return context


class InquiryDetailView(RoleRequiredMixin, DetailView):
    queryset = Inquiry.objects.select_related("customer", "property", "agent")
    template_name = "core/inquiries/inquiry_detail.html"


class InquiryFormMixin:
    model = Inquiry
    form_class = InquiryForm
    template_name = "core/inquiries/inquiry_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        if self.request.user.role == User.Role.AGENT:
            form.instance.agent = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Inquiry saved successfully.")
        return response


class InquiryCreateView(RoleRequiredMixin, InquiryFormMixin, CreateView):
    pass


class InquiryUpdateView(RoleRequiredMixin, AssignedInquiryRequiredMixin, InquiryFormMixin, UpdateView):
    pass


class InquiryDeleteView(RoleRequiredMixin, AssignedInquiryRequiredMixin, DeleteView):
    model = Inquiry
    template_name = "core/inquiries/inquiry_confirm_delete.html"
    success_url = reverse_lazy("core:inquiry_list")
    http_method_names = ["get", "post", "head", "options"]

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This inquiry has linked records and cannot be deleted.")
            return HttpResponseRedirect(self.object.get_absolute_url())
        messages.success(self.request, "Inquiry deleted successfully.")
        return response


class AppointmentListView(RoleRequiredMixin, ListView):
    model = Appointment
    template_name = "core/appointments/appointment_list.html"
    context_object_name = "appointments"
    paginate_by = 20

    def get_queryset(self):
        queryset = Appointment.objects.select_related("customer", "property", "agent")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(appointment_code__icontains=query) | Q(customer__full_name__icontains=query)
                | Q(property__name__icontains=query) | Q(notes__icontains=query)
            )
        status = self.request.GET.get("status", "")
        if status:
            queryset = queryset.filter(status=status)
        agent = self.request.GET.get("agent", "")
        if agent:
            # Validate against choices rather than passing arbitrary text to an ID lookup.
            valid_ids = {str(pk) for pk in User.objects.filter(role=User.Role.AGENT).values_list("pk", flat=True)}
            queryset = queryset.filter(agent_id=agent) if agent in valid_ids else queryset.none()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(
            status_choices=Appointment.Status.choices,
            agents=User.objects.filter(role=User.Role.AGENT).order_by("username"),
            filter_query=filters.urlencode(),
        )
        return context


class AppointmentDetailView(RoleRequiredMixin, DetailView):
    queryset = Appointment.objects.select_related("customer", "property", "agent")
    template_name = "core/appointments/appointment_detail.html"


class AppointmentFormMixin:
    model = Appointment
    form_class = AppointmentForm
    template_name = "core/appointments/appointment_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        if self.request.user.role == User.Role.AGENT:
            form.instance.agent = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Appointment saved successfully.")
        return response


class AppointmentCreateView(RoleRequiredMixin, AppointmentFormMixin, CreateView):
    pass


class AppointmentUpdateView(RoleRequiredMixin, AssignedAppointmentRequiredMixin, AppointmentFormMixin, UpdateView):
    pass


class AppointmentDeleteView(RoleRequiredMixin, AssignedAppointmentRequiredMixin, DeleteView):
    model = Appointment
    template_name = "core/appointments/appointment_confirm_delete.html"
    success_url = reverse_lazy("core:appointment_list")
    http_method_names = ["get", "post", "head", "options"]

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This appointment has linked records and cannot be deleted.")
            return HttpResponseRedirect(self.object.get_absolute_url())
        messages.success(self.request, "Appointment deleted successfully.")
        return response


class TransactionListView(RoleRequiredMixin, ListView):
    model = Transaction
    template_name = "core/transactions/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 20

    def get_queryset(self):
        queryset = Transaction.objects.select_related("customer", "property", "agent")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(Q(transaction_code__icontains=query) | Q(customer__full_name__icontains=query) | Q(property__name__icontains=query))
        for field in ("status", "transaction_type"):
            value = self.request.GET.get(field, "")
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update(status_choices=Transaction.Status.choices, type_choices=Transaction.TransactionType.choices, filter_query=filters.urlencode())
        return context


class TransactionDetailView(RoleRequiredMixin, DetailView):
    queryset = Transaction.objects.select_related("customer", "property", "agent", "inquiry")
    template_name = "core/transactions/transaction_detail.html"


class TransactionFormMixin:
    model = Transaction
    form_class = TransactionForm
    template_name = "core/transactions/transaction_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        if "inquiry_pk" in self.kwargs:
            source = get_object_or_404(Inquiry, pk=self.kwargs["inquiry_pk"])
            if self.request.user.role != User.Role.ADMIN and source.agent_id != self.request.user.pk:
                raise PermissionDenied("You can only create transactions from inquiries assigned to you.")
            kwargs["source_inquiry"] = source
        return kwargs

    def form_valid(self, form):
        if self.request.user.role == User.Role.AGENT:
            form.instance.agent = self.request.user
        try:
            response = super().form_valid(form)
        except ValidationError as error:
            # A concurrent completion can sell a property after form validation.
            if hasattr(error, "message_dict"):
                for field, errors in error.message_dict.items():
                    form.add_error(field if field in form.fields else None, errors)
            else:
                form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "Transaction saved successfully.")
        return response


class TransactionCreateView(RoleRequiredMixin, TransactionFormMixin, CreateView):
    pass


class TransactionUpdateView(RoleRequiredMixin, AssignedTransactionRequiredMixin, TransactionFormMixin, UpdateView):
    pass


class TransactionDeleteView(RoleRequiredMixin, AssignedTransactionRequiredMixin, DeleteView):
    model = Transaction
    template_name = "core/transactions/transaction_confirm_delete.html"
    success_url = reverse_lazy("core:transaction_list")
    http_method_names = ["get", "post", "head", "options"]

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "This transaction has linked records and cannot be deleted.")
            return HttpResponseRedirect(self.object.get_absolute_url())
        messages.success(self.request, "Transaction deleted successfully.")
        return response
