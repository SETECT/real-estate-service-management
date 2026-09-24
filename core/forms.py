from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q

from .models import Appointment, Contract, Customer, Inquiry, Payment, Property, Transaction, User


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            "name", "property_type", "location", "description", "price", "size",
            "bedrooms", "bathrooms", "status", "owner", "assigned_agent", "image",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "property_type": forms.Select(attrs={"class": "form-select"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "price": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "size": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "bedrooms": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "bathrooms": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "owner": forms.Select(attrs={"class": "form-select"}),
            "assigned_agent": forms.Select(attrs={"class": "form-select"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = Customer.objects.filter(
            customer_type__in=[Customer.CustomerType.SELLER, Customer.CustomerType.LANDLORD],
        ).order_by("full_name", "pk")
        self.fields["assigned_agent"].queryset = User.objects.filter(role=User.Role.AGENT).order_by("username")
        if user is not None and user.role == User.Role.AGENT:
            # Disabled fields use server-side initial data even for tampered POSTs.
            self.fields["assigned_agent"].initial = user.pk
            self.fields["assigned_agent"].disabled = True
            self.fields["assigned_agent"].help_text = "Properties you create remain assigned to you."


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["full_name", "phone", "email", "address", "customer_type"]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "type": "tel"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "customer_type": forms.Select(attrs={"class": "form-select"}),
        }


class InquiryForm(forms.ModelForm):
    class Meta:
        model = Inquiry
        fields = ["customer", "property", "agent", "inquiry_date", "message", "status"]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "property": forms.Select(attrs={"class": "form-select"}),
            "agent": forms.Select(attrs={"class": "form-select"}),
            "inquiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("full_name", "pk")
        self.fields["property"].queryset = Property.objects.order_by("name", "pk")
        self.fields["agent"].queryset = User.objects.filter(role=User.Role.AGENT).order_by("username")
        if user is not None and user.role == User.Role.AGENT:
            self.fields["agent"].initial = user.pk
            self.fields["agent"].disabled = True
            self.fields["agent"].help_text = "Your inquiries are assigned to you. Only Admin can reassign them."


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["customer", "property", "agent", "appointment_date", "appointment_time", "notes", "status"]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "property": forms.Select(attrs={"class": "form-select"}),
            "agent": forms.Select(attrs={"class": "form-select"}),
            "appointment_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "appointment_time": forms.TimeInput(format="%H:%M", attrs={"class": "form-control", "type": "time"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("full_name", "pk")
        self.fields["property"].queryset = Property.objects.order_by("name", "pk")
        self.fields["agent"].queryset = User.objects.filter(role=User.Role.AGENT).order_by("username")
        if user is not None and user.role == User.Role.AGENT:
            self.fields["agent"].initial = user.pk
            self.fields["agent"].disabled = True
            self.fields["agent"].help_text = "Your appointments are assigned to you. Only Admin can reassign them."


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["inquiry", "customer", "property", "agent", "transaction_type", "amount", "transaction_date", "status", "start_date", "end_date"]
        widgets = {
            "inquiry": forms.Select(attrs={"class": "form-select"}),
            "customer": forms.Select(attrs={"class": "form-select"}),
            "property": forms.Select(attrs={"class": "form-select"}),
            "agent": forms.Select(attrs={"class": "form-select"}),
            "transaction_type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "transaction_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
        }
        help_texts = {
            "amount": "Sale price for a sale; monthly rent for a rental.",
            "start_date": "Required for rentals only.",
            "end_date": "Required for rentals; must be after the start date.",
            "inquiry": "Optional. Customer and property must match the selected inquiry.",
        }

    def __init__(self, *args, user=None, source_inquiry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("full_name", "pk")
        properties = Property.objects.exclude(status=Property.Status.SOLD)
        if self.instance.pk:
            properties = Property.objects.filter(Q(pk=self.instance.property_id) | ~Q(status=Property.Status.SOLD))
        self.fields["property"].queryset = properties.order_by("name", "pk")
        self.fields["agent"].queryset = User.objects.filter(role=User.Role.AGENT).order_by("username")
        inquiries = Inquiry.objects.select_related("customer", "property")
        if user is not None and user.role == User.Role.AGENT:
            inquiries = inquiries.filter(agent=user)
            self.fields["agent"].initial = user.pk
            self.fields["agent"].disabled = True
            self.fields["agent"].help_text = "Your transactions are assigned to you. Only Admin can reassign them."
        if self.instance.pk:
            inquiries = Inquiry.objects.filter(pk=self.instance.inquiry_id)
            self.fields["inquiry"].disabled = True
            if self.instance.status != Transaction.Status.PENDING:
                self.fields["property"].disabled = True
                self.fields["transaction_type"].disabled = True
        if source_inquiry is not None:
            self.initial.update(inquiry=source_inquiry.pk, customer=source_inquiry.customer_id, property=source_inquiry.property_id)
            if user is not None and user.role == User.Role.ADMIN:
                self.initial["agent"] = source_inquiry.agent_id
            for field in ("inquiry", "customer", "property"):
                self.fields[field].disabled = True
        self.fields["inquiry"].queryset = inquiries


class LinkedTransactionForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        transactions = Transaction.objects.select_related("customer", "property")
        if user is not None and user.role == User.Role.AGENT:
            transactions = transactions.filter(agent=user)
        self.fields["transaction"].queryset = transactions
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"})
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3


class ContractForm(LinkedTransactionForm):
    class Meta:
        model = Contract
        fields = ["contract_number", "transaction", "customer", "property", "contract_type", "start_date", "end_date", "amount", "status", "description"]
        help_texts = {
            "transaction": "Use Create Contract on transaction details to prefill related fields.",
            "customer": "Must match the selected transaction.",
            "property": "Must match the selected transaction.",
            "contract_type": "Must match the transaction type.",
            "end_date": "Required for rentals; must be after the start date.",
        }


class PaymentForm(LinkedTransactionForm):
    class Meta:
        model = Payment
        fields = ["transaction", "customer", "amount", "payment_date", "payment_method", "status", "note"]
        help_texts = {
            "transaction": "Use Record Payment on transaction details to prefill related fields.",
            "customer": "Must match the selected transaction.",
            "amount": "Enter the amount recorded for this payment.",
            "status": "Mark Paid only when the payment has been received.",
        }


class ReportFilterForm(forms.Form):
    q = forms.CharField(label="Search", required=False, max_length=200)
    property_type = forms.ChoiceField(required=False, choices=[("", "All property types"), *Property.PropertyType.choices])
    property_status = forms.ChoiceField(required=False, choices=[("", "All property statuses"), *Property.Status.choices])
    transaction_type = forms.ChoiceField(required=False, choices=[("", "All transaction types"), *Transaction.TransactionType.choices])
    transaction_status = forms.ChoiceField(required=False, choices=[("", "All transaction statuses"), *Transaction.Status.choices])
    payment_method = forms.ChoiceField(required=False, choices=[("", "All payment methods"), *Payment.Method.choices])
    payment_status = forms.ChoiceField(required=False, choices=[("", "All payment statuses"), *Payment.Status.choices])
    date_from = forms.DateField(label="From date (transactions / payments)", required=False)
    date_to = forms.DateField(label="To date (transactions / payments)", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"})

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_to"] < data["date_from"]:
            self.add_error("date_to", "To date must be on or after From date.")
        return data
