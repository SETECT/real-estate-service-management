from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"

urlpatterns = [
    path("reports/", views.ReportListView.as_view(), name="report_list"),
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/add/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/", views.PaymentDetailView.as_view(), name="payment_detail"),
    path("payments/<int:pk>/edit/", views.PaymentUpdateView.as_view(), name="payment_update"),
    path("payments/<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),
    path("contracts/", views.ContractListView.as_view(), name="contract_list"),
    path("contracts/add/", views.ContractCreateView.as_view(), name="contract_create"),
    path("contracts/<int:pk>/", views.ContractDetailView.as_view(), name="contract_detail"),
    path("contracts/<int:pk>/edit/", views.ContractUpdateView.as_view(), name="contract_update"),
    path("contracts/<int:pk>/delete/", views.ContractDeleteView.as_view(), name="contract_delete"),
    path("", RedirectView.as_view(pattern_name="core:dashboard", permanent=False)),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("properties/", views.PropertyListView.as_view(), name="property_list"),
    path("properties/add/", views.PropertyCreateView.as_view(), name="property_create"),
    path("properties/<int:pk>/", views.PropertyDetailView.as_view(), name="property_detail"),
    path("properties/<int:pk>/edit/", views.PropertyUpdateView.as_view(), name="property_update"),
    path("properties/<int:pk>/delete/", views.PropertyDeleteView.as_view(), name="property_delete"),
    path("customers/", views.CustomerListView.as_view(), name="customer_list"),
    path("customers/add/", views.CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<int:pk>/", views.CustomerDetailView.as_view(), name="customer_detail"),
    path("customers/<int:pk>/edit/", views.CustomerUpdateView.as_view(), name="customer_update"),
    path("customers/<int:pk>/delete/", views.CustomerDeleteView.as_view(), name="customer_delete"),
    path("inquiries/", views.InquiryListView.as_view(), name="inquiry_list"),
    path("inquiries/add/", views.InquiryCreateView.as_view(), name="inquiry_create"),
    path("inquiries/<int:pk>/", views.InquiryDetailView.as_view(), name="inquiry_detail"),
    path("inquiries/<int:pk>/edit/", views.InquiryUpdateView.as_view(), name="inquiry_update"),
    path("inquiries/<int:pk>/delete/", views.InquiryDeleteView.as_view(), name="inquiry_delete"),
    path("appointments/", views.AppointmentListView.as_view(), name="appointment_list"),
    path("appointments/add/", views.AppointmentCreateView.as_view(), name="appointment_create"),
    path("appointments/<int:pk>/", views.AppointmentDetailView.as_view(), name="appointment_detail"),
    path("appointments/<int:pk>/edit/", views.AppointmentUpdateView.as_view(), name="appointment_update"),
    path("appointments/<int:pk>/delete/", views.AppointmentDeleteView.as_view(), name="appointment_delete"),
    path("transactions/", views.TransactionListView.as_view(), name="transaction_list"),
    path("transactions/add/", views.TransactionCreateView.as_view(), name="transaction_create"),
    path("transactions/<int:pk>/", views.TransactionDetailView.as_view(), name="transaction_detail"),
    path("transactions/<int:pk>/edit/", views.TransactionUpdateView.as_view(), name="transaction_update"),
    path("transactions/<int:pk>/delete/", views.TransactionDeleteView.as_view(), name="transaction_delete"),
    path("inquiries/<int:inquiry_pk>/transaction/", views.TransactionCreateView.as_view(), name="transaction_create_from_inquiry"),
]
