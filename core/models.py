from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, router, transaction
from django.urls import reverse
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        AGENT = "agent", "Agent"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.AGENT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Customer(models.Model):
    class CustomerType(models.TextChoices):
        BUYER = "Buyer", "Buyer"
        SELLER = "Seller", "Seller"
        TENANT = "Tenant", "Tenant"
        LANDLORD = "Landlord", "Landlord"

    customer_code = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    customer_type = models.CharField(max_length=10, choices=CustomerType.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.customer_code} - {self.full_name}"

    def get_absolute_url(self):
        return reverse("core:customer_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.pk and self.customer_type not in (self.CustomerType.SELLER, self.CustomerType.LANDLORD):
            if self.properties.exists():
                raise ValidationError({"customer_type": "A property owner must remain a Seller or Landlord. Reassign their properties first."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self.customer_code = f"pending-{uuid4().hex}"
        with transaction.atomic(using=database):
            super().save(*args, **kwargs)
            self.customer_code = f"CUS-{self.pk:06d}"
            type(self).objects.using(database).filter(pk=self.pk).update(customer_code=self.customer_code)


class Property(models.Model):
    class PropertyType(models.TextChoices):
        HOUSE = "House", "House"
        APARTMENT = "Apartment", "Apartment"
        CONDO = "Condo", "Condo"
        LAND = "Land", "Land"
        COMMERCIAL = "Commercial", "Commercial"

    class Status(models.TextChoices):
        AVAILABLE = "Available", "Available"
        RESERVED = "Reserved", "Reserved"
        SOLD = "Sold", "Sold"
        RENTED = "Rented", "Rented"

    property_code = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    name = models.CharField(max_length=200)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices)
    location = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    size = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Area in square metres.",
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    bedrooms = models.PositiveIntegerField()
    bathrooms = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    owner = models.ForeignKey(
        Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="properties",
        limit_choices_to={"customer_type__in": [Customer.CustomerType.SELLER, Customer.CustomerType.LANDLORD]},
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="assigned_properties", limit_choices_to={"role": User.Role.AGENT},
    )
    image = models.ImageField(upload_to="properties/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.property_code} - {self.name}"

    def get_absolute_url(self):
        return reverse("core:property_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        errors = {}
        if self.price is not None and self.price < 0:
            errors["price"] = "Price cannot be negative."
        if self.size is not None and self.size <= 0:
            errors["size"] = "Size must be greater than zero."
        if self.assigned_agent_id and self.assigned_agent.role != User.Role.AGENT:
            errors["assigned_agent"] = "Select a user with the Agent role."
        if self.owner_id and self.owner.customer_type not in (Customer.CustomerType.SELLER, Customer.CustomerType.LANDLORD):
            errors["owner"] = "Select a Seller or Landlord as the owner."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        # Use the database PK, not a race-prone count/max. The temporary code
        # remains private until both writes commit in this transaction.
        self.property_code = f"pending-{uuid4().hex}"
        with transaction.atomic(using=database):
            super().save(*args, **kwargs)
            self.property_code = f"PRP-{self.pk:06d}"
            type(self).objects.using(database).filter(pk=self.pk).update(property_code=self.property_code)


class Inquiry(models.Model):
    class Status(models.TextChoices):
        NEW = "New", "New"
        CONTACTED = "Contacted", "Contacted"
        VIEWING = "Viewing", "Viewing"
        NEGOTIATION = "Negotiation", "Negotiation"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    inquiry_code = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="inquiries")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="inquiries")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="inquiries", limit_choices_to={"role": User.Role.AGENT},
    )
    inquiry_date = models.DateField(default=timezone.localdate)
    message = models.TextField("Message / notes", blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-inquiry_date", "-created_at", "-pk"]

    def __str__(self):
        return self.inquiry_code

    def get_absolute_url(self):
        return reverse("core:inquiry_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.agent_id and self.agent.role != User.Role.AGENT:
            raise ValidationError({"agent": "Select a user with the Agent role."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self.inquiry_code = f"pending-{uuid4().hex}"
        with transaction.atomic(using=database):
            super().save(*args, **kwargs)
            self.inquiry_code = f"INQ-{self.pk:06d}"
            type(self).objects.using(database).filter(pk=self.pk).update(inquiry_code=self.inquiry_code)


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "Scheduled", "Scheduled"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    appointment_code = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="appointments")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="appointments")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="appointments",
        limit_choices_to={"role": User.Role.AGENT},
    )
    appointment_date = models.DateField(default=timezone.localdate)
    appointment_time = models.TimeField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-appointment_date", "-appointment_time", "-pk"]

    def __str__(self):
        return self.appointment_code

    def get_absolute_url(self):
        return reverse("core:appointment_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.agent_id and self.agent.role != User.Role.AGENT:
            raise ValidationError({"agent": "Select a user with the Agent role."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        self.appointment_code = f"pending-{uuid4().hex}"
        with transaction.atomic(using=database):
            super().save(*args, **kwargs)
            self.appointment_code = f"APT-{self.pk:06d}"
            type(self).objects.using(database).filter(pk=self.pk).update(appointment_code=self.appointment_code)


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        SALE = "Sale", "Sale"
        RENTAL = "Rental", "Rental"

    class Status(models.TextChoices):
        PENDING = "Pending", "Pending"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    transaction_code = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="transactions")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="transactions")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transactions",
        limit_choices_to={"role": User.Role.AGENT},
    )
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions")
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    transaction_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-transaction_date", "-created_at", "-pk"]

    def __str__(self):
        return self.transaction_code

    def get_absolute_url(self):
        return reverse("core:transaction_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        errors = {}
        database = self._state.db or router.db_for_write(type(self), instance=self)
        previous = type(self).objects.using(database).filter(pk=self.pk).first() if self.pk else None
        if self.transaction_type == self.TransactionType.RENTAL:
            if not self.start_date:
                errors["start_date"] = "Start date is required for a rental."
            if not self.end_date:
                errors["end_date"] = "End date is required for a rental."
            if self.start_date and self.end_date and self.end_date <= self.start_date:
                errors["end_date"] = "End date must be after start date."
        elif self.transaction_type == self.TransactionType.SALE:
            self.start_date = self.end_date = None
        if self.agent_id and self.agent.role != User.Role.AGENT:
            errors["agent"] = "Select a user with the Agent role."
        if previous:
            # Keep existing contracts and receipts consistent when editing a deal.
            if self.contracts.exists():
                for field in ("customer_id", "property_id", "transaction_type"):
                    if getattr(previous, field) != getattr(self, field):
                        errors[field.removesuffix("_id")] = "This field cannot change while contracts reference the transaction."
            if self.payments.exists() and previous.customer_id != self.customer_id:
                errors["customer"] = "Customer cannot change while payments reference the transaction."
            if previous.inquiry_id != self.inquiry_id:
                errors["inquiry"] = "The source inquiry cannot be changed after creation."
            if previous.status != self.Status.PENDING:
                if self.property_id != previous.property_id:
                    errors["property"] = "The property cannot be changed after completion or cancellation."
                if self.transaction_type != previous.transaction_type:
                    errors["transaction_type"] = "The type cannot be changed after completion or cancellation."
                allowed = {self.Status.COMPLETED, self.Status.CANCELLED} if previous.status == self.Status.COMPLETED else {self.Status.CANCELLED}
                if self.status not in allowed:
                    errors["status"] = "Completed or cancelled transactions cannot be reopened."
        selecting_property = not previous or previous.property_id != self.property_id
        completing = self.status == self.Status.COMPLETED and (not previous or previous.status != self.Status.COMPLETED)
        if self.property_id and (selecting_property or completing) and self.property.status == Property.Status.SOLD:
            errors["property"] = "A sold property cannot be selected or completed in a new transaction."
        if self.inquiry_id:
            if self.customer_id != self.inquiry.customer_id:
                errors["customer"] = "Customer must match the source inquiry."
            if self.property_id != self.inquiry.property_id:
                errors["property"] = "Property must match the source inquiry."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            previous = None
            if not self._state.adding:
                previous = type(self).objects.using(database).select_for_update().get(pk=self.pk)
            # Serialise property transitions and refresh cached relations before validation.
            if self.property_id:
                self.property = Property.objects.using(database).select_for_update().get(pk=self.property_id)
            if self.inquiry_id:
                self.inquiry = Inquiry.objects.using(database).select_for_update().get(pk=self.inquiry_id)
            self.full_clean()
            if previous is None:
                self.transaction_code = f"pending-{uuid4().hex}"
            # Save the complete validated state: partial writes must not desynchronise status effects.
            kwargs.pop("update_fields", None)
            super().save(*args, **kwargs)
            if previous is None:
                self.transaction_code = f"TRN-{self.pk:06d}"
                type(self).objects.using(database).filter(pk=self.pk).update(transaction_code=self.transaction_code)
                if self.inquiry_id:
                    Inquiry.objects.using(database).filter(pk=self.inquiry_id).update(status=Inquiry.Status.COMPLETED, updated_at=timezone.now())
            if previous is None or previous.status != self.status:
                new_status = None
                if self.status == self.Status.COMPLETED:
                    new_status = Property.Status.SOLD if self.transaction_type == self.TransactionType.SALE else Property.Status.RENTED
                elif self.status == self.Status.CANCELLED and self.property.status == Property.Status.RESERVED:
                    new_status = Property.Status.AVAILABLE
                if new_status:
                    Property.objects.using(database).filter(pk=self.property_id).update(status=new_status, updated_at=timezone.now())
                    self.property.status = new_status


class Contract(models.Model):
    class ContractType(models.TextChoices):
        SALE = "Sale", "Sale Contract"
        RENTAL = "Rental", "Rental Contract"

    class Status(models.TextChoices):
        DRAFT = "Draft", "Draft"
        ACTIVE = "Active", "Active"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    contract_number = models.CharField(max_length=60, unique=True)
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="contracts")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="contracts")
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="contracts")
    contract_type = models.CharField(max_length=10, choices=ContractType.choices)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField("Contract amount", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.contract_number

    def get_absolute_url(self):
        return reverse("core:contract_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_id:
            for field in ("customer", "property"):
                if getattr(self, f"{field}_id") != getattr(self.transaction, f"{field}_id"):
                    errors[field] = f"{field.title()} must match the transaction."
            if self.contract_type != self.transaction.transaction_type:
                errors["contract_type"] = "Contract type must match the transaction."
        if self.contract_type == self.ContractType.RENTAL and not self.end_date:
            errors["end_date"] = "End date is required for rental contracts."
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            errors["end_date"] = "End date must be after start date."
        if errors:
            raise ValidationError(errors)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "Cash", "Cash"
        BANK_TRANSFER = "Bank Transfer", "Bank Transfer"
        OTHER = "Other", "Other"

    class Status(models.TextChoices):
        PAID = "Paid", "Paid"
        PENDING = "Pending", "Pending"

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="payments")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    payment_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=15, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date", "-created_at", "-pk"]

    def __str__(self):
        return f"PAY-{self.pk:06d}" if self.pk else "New payment"

    def get_absolute_url(self):
        return reverse("core:payment_detail", kwargs={"pk": self.pk})

    def clean(self):
        super().clean()
        if self.transaction_id and self.customer_id != self.transaction.customer_id:
            raise ValidationError({"customer": "Customer must match the transaction."})
