from decimal import Decimal
from datetime import date, time
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Appointment, Contract, Customer, Inquiry, Payment, Property, Transaction, User


class PropertyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password="admin123", role=User.Role.ADMIN, is_staff=True)
        cls.agent = User.objects.create_user("agent", password="agent123", role=User.Role.AGENT)
        cls.other_agent = User.objects.create_user("other", password="agent123", role=User.Role.AGENT)
        cls.property = Property.objects.create(
            name="Garden House", property_type=Property.PropertyType.HOUSE, location="Phnom Penh",
            price="125000.50", size="120.25", bedrooms=3, bathrooms=2, assigned_agent=cls.agent,
        )
        cls.other_property = Property.objects.create(
            name="City Condo", property_type=Property.PropertyType.CONDO, location="Siem Reap",
            price="90000.00", size="80.75", bedrooms=2, bathrooms=1,
            status=Property.Status.RENTED, assigned_agent=cls.other_agent,
        )

    def data(self, **overrides):
        values = {
            "name": "New Property", "property_type": "Apartment", "location": "Kampot",
            "description": "A bright apartment.", "price": "65000.25", "size": "65.50",
            "bedrooms": "2", "bathrooms": "1", "status": "Available", "assigned_agent": str(self.agent.pk),
        }
        return {**values, **overrides}

    def url(self, action, obj=None):
        return reverse(f"core:property_{action}", kwargs={"pk": obj.pk} if obj else None)

    def test_all_property_views_require_login(self):
        for action, obj in (("list", None), ("create", None), ("detail", self.property), ("update", self.property), ("delete", self.property)):
            with self.subTest(action=action):
                url = self.url(action, obj)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
                self.assertEqual(self.client.post(url, self.data()).status_code, 302)

    def test_login_logout_and_user_role_permissions(self):
        response = self.client.post(reverse("login"), {"username": "agent", "password": "agent123"})
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 403)
        self.assertNotContains(self.client.get(self.url("list")), 'href="/users/"')
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 200)

    def test_unknown_role_is_denied(self):
        self.agent.role = "unknown"
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url("list")).status_code, 403)
        self.assertEqual(self.client.post(self.url("create"), self.data()).status_code, 403)

    def test_agent_can_view_all_properties_but_only_sees_own_actions(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("list"))
        self.assertContains(response, "Garden House")
        self.assertContains(response, "City Condo")
        self.assertContains(response, self.url("update", self.property))
        self.assertNotContains(response, self.url("update", self.other_property))
        detail = self.client.get(self.url("detail", self.other_property))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, self.url("delete", self.other_property))

    def test_agent_create_forces_self_assignment_even_for_tampered_post(self):
        self.client.force_login(self.agent)
        for assignment in ("", str(self.other_agent.pk), str(self.admin.pk), "999999"):
            with self.subTest(assignment=assignment):
                response = self.client.post(self.url("create"), self.data(assigned_agent=assignment))
                created = Property.objects.latest("pk")
                self.assertRedirects(response, created.get_absolute_url())
                self.assertEqual(created.assigned_agent_id, self.agent.pk)

    def test_agent_can_update_own_property_but_cannot_reassign(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url("update", self.property), self.data(name="Updated", assigned_agent=str(self.other_agent.pk)))
        self.assertRedirects(response, self.property.get_absolute_url())
        self.property.refresh_from_db()
        self.assertEqual(self.property.name, "Updated")
        self.assertEqual(self.property.assigned_agent_id, self.agent.pk)

    def test_agent_cannot_change_other_or_unassigned_properties(self):
        self.client.force_login(self.agent)
        for assignment in (self.other_agent, None):
            self.other_property.assigned_agent = assignment
            self.other_property.save()
            for action in ("update", "delete"):
                with self.subTest(assignment=assignment, action=action):
                    url = self.url(action, self.other_property)
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, self.data()).status_code, 403)
            self.other_property.refresh_from_db()
            self.assertEqual(self.other_property.name, "City Condo")

    def test_delete_requires_post_and_confirmation_page_has_modal(self):
        self.client.force_login(self.agent)
        url = self.url("delete", self.property)
        response = self.client.get(url)
        self.assertContains(response, 'id="deletePropertyModal"')
        self.assertContains(response, "Confirm Delete")
        self.assertTrue(Property.objects.filter(pk=self.property.pk).exists())
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertRedirects(self.client.post(url), self.url("list"))
        self.assertFalse(Property.objects.filter(pk=self.property.pk).exists())

    def test_delete_rejects_missing_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url("delete", self.property)).status_code, 403)
        self.assertTrue(Property.objects.filter(pk=self.property.pk).exists())

    def test_admin_full_crud_and_reassignment(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url("create")).status_code, 200)
        response = self.client.post(self.url("create"), self.data(assigned_agent=""))
        created = Property.objects.latest("pk")
        self.assertRedirects(response, created.get_absolute_url())
        self.assertIsNone(created.assigned_agent)
        response = self.client.post(self.url("update", created), self.data(assigned_agent=str(self.other_agent.pk)))
        self.assertRedirects(response, created.get_absolute_url())
        created.refresh_from_db()
        self.assertEqual(created.assigned_agent, self.other_agent)
        self.assertRedirects(self.client.post(self.url("delete", created)), self.url("list"))

    def test_admin_cannot_assign_property_to_non_agent(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(assigned_agent=str(self.admin.pk)))
        self.assertIn("assigned_agent", response.context["form"].errors)
        self.assertEqual(Property.objects.count(), 2)

    def test_search_name_location_and_combined_filters(self):
        self.client.force_login(self.agent)
        for params, expected in (
            ({"q": "gArDeN"}, [self.property]),
            ({"q": "  siem  "}, [self.other_property]),
            ({"status": "Available"}, [self.property]),
            ({"property_type": "Condo"}, [self.other_property]),
            ({"q": "City", "status": "Rented", "property_type": "Condo"}, [self.other_property]),
            ({"status": "Available", "property_type": "Condo"}, []),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url("list"), params)
                self.assertEqual(list(response.context["properties"]), expected)

    def test_pagination_preserves_filters(self):
        for number in range(21):
            Property.objects.create(name=f"Lake {number}", property_type="Land", location="Kampot", price=1, size=10, bedrooms=0, bathrooms=0)
        self.client.force_login(self.agent)
        filters = {"q": "Lake", "status": "Available", "property_type": "Land"}
        response = self.client.get(self.url("list"), filters)
        self.assertEqual(len(response.context["properties"]), 20)
        self.assertContains(response, "q=Lake&amp;status=Available&amp;property_type=Land&amp;page=2")
        response = self.client.get(self.url("list"), {**filters, "page": 2})
        self.assertEqual(len(response.context["properties"]), 1)

    def test_property_code_is_generated_unique_and_stable_after_delete(self):
        code = self.property.property_code
        self.assertEqual(code, f"PRP-{self.property.pk:06d}")
        self.property.name = "Changed"
        self.property.save()
        self.property.refresh_from_db()
        self.assertEqual(self.property.property_code, code)
        deleted_code = self.other_property.property_code
        self.other_property.delete()
        replacement = Property.objects.create(name="Replacement", property_type="Land", location="Kampot", price=1, size=1, bedrooms=0, bathrooms=0)
        self.assertNotIn(replacement.property_code, (code, deleted_code))

    def test_model_validation_and_protected_agent(self):
        self.property.full_clean()
        self.assertEqual(self.property.size, Decimal("120.25"))
        for field, value in (("price", Decimal("-1")), ("size", Decimal("0")), ("bedrooms", -1), ("bathrooms", -1), ("assigned_agent", self.admin)):
            with self.subTest(field=field):
                self.property.refresh_from_db()
                setattr(self.property, field, value)
                with self.assertRaises(ValidationError):
                    self.property.full_clean()
        with self.assertRaises(ProtectedError):
            self.agent.delete()

    def test_invalid_form_does_not_save(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(price="-1", size="0", bedrooms="-1"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"price", "size", "bedrooms"})
        self.assertEqual(Property.objects.count(), 2)

    def test_image_upload_display_clear_and_invalid_image(self):
        self.client.force_login(self.agent)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            buffer = BytesIO()
            Image.new("RGB", (4, 4), "green").save(buffer, format="PNG")
            upload = SimpleUploadedFile("house.png", buffer.getvalue(), content_type="image/png")
            response = self.client.post(self.url("create"), self.data(image=upload))
            created = Property.objects.latest("pk")
            self.assertRedirects(response, created.get_absolute_url())
            self.assertTrue(created.image.name.startswith("properties/"))
            self.assertTrue(created.image.storage.exists(created.image.name))
            self.assertContains(self.client.get(created.get_absolute_url()), created.image.url)
            response = self.client.post(self.url("update", created), self.data(**{"image-clear": "on"}))
            self.assertRedirects(response, created.get_absolute_url())
            created.refresh_from_db()
            self.assertFalse(created.image)
            invalid = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
            response = self.client.post(self.url("create"), self.data(image=invalid))
            self.assertIn("image", response.context["form"].errors)

    def test_agent_cannot_bypass_permissions_in_django_admin(self):
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_property_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:core_user_changelist")).status_code, 403)


class DemoSeedTests(TestCase):
    def test_seed_is_repeatable_and_creates_expected_accounts_and_properties(self):
        for _ in range(2):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Property.objects.count(), 3)
        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 200)
        self.assertTrue(self.client.login(username="agent", password="agent123"))
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 403)
        self.assertEqual(Property.objects.filter(assigned_agent__username="agent").count(), 3)
        self.assertEqual(Property.objects.filter(owner__customer_type=Customer.CustomerType.SELLER).count(), 3)

    def test_seed_preserves_existing_customers_and_property_owners(self):
        call_command("seed_demo", stdout=StringIO())
        seller = Customer.objects.get(full_name="Sok Dara")
        seller.email = "updated@example.com"
        seller.save()
        property = Property.objects.first()
        property.owner = None
        property.save()
        call_command("seed_demo", stdout=StringIO())
        seller.refresh_from_db()
        property.refresh_from_db()
        self.assertEqual(seller.email, "updated@example.com")
        self.assertIsNone(property.owner)
        self.assertEqual(Customer.objects.count(), 2)


class CustomerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password="admin123", role=User.Role.ADMIN, is_staff=True)
        cls.agent = User.objects.create_user("agent", password="agent123", role=User.Role.AGENT)
        cls.seller = Customer.objects.create(full_name="Sok Dara", phone="012345678", email="dara@example.com", address="Phnom Penh", customer_type=Customer.CustomerType.SELLER)
        cls.buyer = Customer.objects.create(full_name="Chan Sreyneang", phone="098765432", email="sreyneang@example.com", customer_type=Customer.CustomerType.BUYER)
        cls.landlord = Customer.objects.create(full_name="Landlord", phone="010000001", customer_type=Customer.CustomerType.LANDLORD)
        cls.tenant = Customer.objects.create(full_name="Tenant", phone="010000002", customer_type=Customer.CustomerType.TENANT)
        cls.property = Property.objects.create(name="Owned House", property_type="House", location="Phnom Penh", price=100000, size=100, bedrooms=2, bathrooms=1, owner=cls.seller, assigned_agent=cls.agent)

    def data(self, **overrides):
        return {"full_name": "New Customer", "phone": "+855 12 123 456", "email": "new@example.com", "address": "Kampot", "customer_type": "Buyer", **overrides}

    def url(self, action, customer=None):
        return reverse(f"core:customer_{action}", kwargs={"pk": customer.pk} if customer else None)

    def test_customer_routes_require_login(self):
        for action, obj in (("list", None), ("create", None), ("detail", self.seller), ("update", self.seller), ("delete", self.seller)):
            with self.subTest(action=action):
                url = self.url(action, obj)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
                self.assertEqual(self.client.post(url, self.data()).status_code, 302)

    def test_agent_can_list_and_view_but_cannot_mutate_customers(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("list"))
        self.assertContains(response, self.seller.full_name)
        self.assertContains(response, self.buyer.full_name)
        self.assertNotContains(response, self.url("create"))
        self.assertNotContains(response, self.url("update", self.seller))
        self.assertContains(self.client.get(self.url("detail", self.seller)), self.property.get_absolute_url())
        for action, obj in (("create", None), ("update", self.seller), ("delete", self.buyer)):
            with self.subTest(action=action):
                self.assertEqual(self.client.get(self.url(action, obj)).status_code, 403)
                self.assertEqual(self.client.post(self.url(action, obj), self.data()).status_code, 403)
        self.assertEqual(Customer.objects.count(), 4)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.full_name, "Sok Dara")

    def test_admin_can_create_read_update_and_delete_customer(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url("create")).status_code, 200)
        response = self.client.post(self.url("create"), self.data())
        customer = Customer.objects.latest("pk")
        self.assertRedirects(response, customer.get_absolute_url())
        self.assertEqual(customer.customer_code, f"CUS-{customer.pk:06d}")
        code = customer.customer_code
        self.assertContains(self.client.get(customer.get_absolute_url()), "+855 12 123 456")
        self.assertEqual(self.client.get(self.url("update", customer)).status_code, 200)
        response = self.client.post(self.url("update", customer), self.data(full_name="Updated Customer", email="", address="", customer_code="CUS-999999"))
        self.assertRedirects(response, customer.get_absolute_url())
        customer.refresh_from_db()
        self.assertEqual(customer.full_name, "Updated Customer")
        self.assertEqual(customer.customer_code, code)
        self.assertEqual(customer.email, "")
        delete_url = self.url("delete", customer)
        self.assertContains(self.client.get(delete_url), 'id="deleteCustomerModal"')
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())
        self.assertEqual(self.client.delete(delete_url).status_code, 405)
        self.assertRedirects(self.client.post(delete_url), self.url("list"))
        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())

    def test_customer_delete_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url("delete", self.buyer)).status_code, 403)
        self.assertTrue(Customer.objects.filter(pk=self.buyer.pk).exists())

    def test_customer_search_and_type_filter(self):
        self.client.force_login(self.agent)
        for params, expected in (
            ({"q": "  SOK  "}, [self.seller]),
            ({"q": "987654"}, [self.buyer]),
            ({"q": "DARA@EXAMPLE"}, [self.seller]),
            ({"customer_type": "Buyer"}, [self.buyer]),
            ({"q": "Sok", "customer_type": "Buyer"}, []),
            ({"q": "Sok", "customer_type": "Seller"}, [self.seller]),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url("list"), params)
                self.assertEqual(list(response.context["customers"]), expected)

    def test_customer_pagination_preserves_search_and_filter(self):
        for number in range(21):
            Customer.objects.create(full_name=f"Demo {number}", phone="012345678", customer_type="Buyer")
        self.client.force_login(self.agent)
        filters = {"q": "Demo", "customer_type": "Buyer"}
        response = self.client.get(self.url("list"), filters)
        self.assertEqual(len(response.context["customers"]), 20)
        self.assertContains(response, "q=Demo&amp;customer_type=Buyer&amp;page=2")
        response = self.client.get(self.url("list"), {**filters, "page": 2})
        self.assertEqual(len(response.context["customers"]), 1)

    def test_invalid_customer_fields_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(full_name=" ", phone="", email="invalid", customer_type="Invalid"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"full_name", "phone", "email", "customer_type"})
        self.assertEqual(Customer.objects.count(), 4)

    def test_linked_owner_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.seller.delete()
        self.client.force_login(self.admin)
        response = self.client.post(self.url("delete", self.seller), follow=True)
        self.assertRedirects(response, self.seller.get_absolute_url())
        self.assertContains(response, "has linked records and cannot be deleted")
        self.property.refresh_from_db()
        self.assertEqual(self.property.owner_id, self.seller.pk)

    def test_owner_type_cannot_be_changed_to_buyer_or_tenant(self):
        self.client.force_login(self.admin)
        for kind in (Customer.CustomerType.BUYER, Customer.CustomerType.TENANT):
            with self.subTest(kind=kind):
                self.seller.customer_type = kind
                with self.assertRaises(ValidationError):
                    self.seller.clean()
                response = self.client.post(self.url("update", self.seller), self.data(customer_type=kind))
                self.assertIn("customer_type", response.context["form"].errors)
                self.seller.refresh_from_db()
                self.assertEqual(self.seller.customer_type, Customer.CustomerType.SELLER)
        response = self.client.post(self.url("update", self.seller), self.data(customer_type="Landlord"))
        self.assertRedirects(response, self.seller.get_absolute_url())
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.customer_type, Customer.CustomerType.LANDLORD)

    def test_unlinked_customer_can_change_type(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("update", self.buyer), self.data(customer_type="Seller"))
        self.assertRedirects(response, self.buyer.get_absolute_url())
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.customer_type, Customer.CustomerType.SELLER)

    def test_property_owner_selector_and_tampered_values(self):
        self.client.force_login(self.agent)
        url = reverse("core:property_update", kwargs={"pk": self.property.pk})
        response = self.client.get(url)
        self.assertEqual(set(response.context["form"].fields["owner"].queryset), {self.seller, self.landlord})
        data = {"name": self.property.name, "property_type": "House", "location": "Phnom Penh", "price": "100000.00", "size": "100.00", "bedrooms": 2, "bathrooms": 1, "status": "Available"}
        for owner in (self.buyer, self.tenant):
            with self.subTest(owner=owner):
                response = self.client.post(url, {**data, "owner": owner.pk})
                self.assertIn("owner", response.context["form"].errors)
                self.property.refresh_from_db()
                self.assertEqual(self.property.owner_id, self.seller.pk)
                self.property.owner = owner
                with self.assertRaises(ValidationError):
                    self.property.clean()
        response = self.client.post(url, {**data, "owner": self.landlord.pk})
        self.assertRedirects(response, self.property.get_absolute_url())
        self.property.refresh_from_db()
        self.assertEqual(self.property.owner, self.landlord)
        self.assertContains(self.client.get(self.property.get_absolute_url()), self.landlord.get_absolute_url())
        response = self.client.post(url, {**data, "owner": ""})
        self.assertRedirects(response, self.property.get_absolute_url())
        self.property.refresh_from_db()
        self.assertIsNone(self.property.owner)

    def test_customer_permissions_also_apply_in_django_admin(self):
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_customer_changelist")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:core_customer_add"), self.data()).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_customer_changelist")).status_code, 200)


class InquiryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password="admin123", role=User.Role.ADMIN, is_staff=True)
        cls.agent = User.objects.create_user("agent", password="agent123", role=User.Role.AGENT)
        cls.other_agent = User.objects.create_user("other", password="agent123", role=User.Role.AGENT)
        cls.customer = Customer.objects.create(full_name="Sok Dara", phone="012345678", customer_type="Buyer")
        cls.other_customer = Customer.objects.create(full_name="Chan Sreyneang", phone="098765432", customer_type="Tenant")
        cls.property = Property.objects.create(name="Garden House", property_type="House", location="Phnom Penh", price=100000, size=100, bedrooms=2, bathrooms=1, assigned_agent=cls.other_agent)
        cls.inquiry = Inquiry.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, message="Interested in a garden.")
        cls.other_inquiry = Inquiry.objects.create(customer=cls.other_customer, property=cls.property, agent=cls.other_agent, status="Contacted", message="Evening viewing requested.")
        cls.unassigned = Inquiry.objects.create(customer=cls.customer, property=cls.property)

    def url(self, action, inquiry=None):
        return reverse(f"core:inquiry_{action}", kwargs={"pk": inquiry.pk} if inquiry else None)

    def data(self, **overrides):
        return {"customer": str(self.customer.pk), "property": str(self.property.pk), "agent": str(self.agent.pk), "inquiry_date": timezone.localdate().isoformat(), "message": "Please arrange a viewing.", "status": "New", **overrides}

    def test_all_inquiry_routes_require_login(self):
        for action, obj in (("list", None), ("create", None), ("detail", self.inquiry), ("update", self.inquiry), ("delete", self.inquiry)):
            with self.subTest(action=action):
                url = self.url(action, obj)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
                self.assertEqual(self.client.post(url, self.data()).status_code, 302)

    def test_agent_can_view_all_but_only_sees_own_actions(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("list"))
        for inquiry in (self.inquiry, self.other_inquiry, self.unassigned):
            self.assertContains(response, inquiry.inquiry_code)
            self.assertEqual(self.client.get(inquiry.get_absolute_url()).status_code, 200)
        self.assertContains(response, self.url("update", self.inquiry))
        self.assertNotContains(response, self.url("update", self.other_inquiry))
        self.assertNotContains(response, self.url("delete", self.unassigned))
        detail = self.client.get(self.inquiry.get_absolute_url())
        self.assertContains(detail, self.customer.get_absolute_url())
        self.assertContains(detail, self.property.get_absolute_url())
        self.assertNotContains(self.client.get(self.other_inquiry.get_absolute_url()), self.url("update", self.other_inquiry))

    def test_agent_create_always_assigns_self(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url("create")).status_code, 200)
        for assignment in ("", str(self.other_agent.pk), str(self.admin.pk), "999999"):
            with self.subTest(assignment=assignment):
                response = self.client.post(self.url("create"), self.data(agent=assignment))
                inquiry = Inquiry.objects.latest("pk")
                self.assertRedirects(response, inquiry.get_absolute_url())
                self.assertEqual(inquiry.agent_id, self.agent.pk)
                self.assertEqual(inquiry.property.assigned_agent_id, self.other_agent.pk)

    def test_agent_updates_all_statuses_without_reassigning_or_changing_property_status(self):
        self.client.force_login(self.agent)
        original_code = self.inquiry.inquiry_code
        self.assertEqual(self.client.get(self.url("update", self.inquiry)).status_code, 200)
        for status in Inquiry.Status.values:
            with self.subTest(status=status):
                response = self.client.post(self.url("update", self.inquiry), self.data(agent=str(self.other_agent.pk), status=status, inquiry_code="INQ-999999"))
                self.assertRedirects(response, self.inquiry.get_absolute_url())
                self.inquiry.refresh_from_db()
                self.assertEqual(self.inquiry.status, status)
                self.assertEqual(self.inquiry.agent_id, self.agent.pk)
                self.assertEqual(self.inquiry.inquiry_code, original_code)
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)

    def test_agent_cannot_edit_delete_or_claim_other_and_unassigned_inquiries(self):
        self.client.force_login(self.agent)
        for inquiry in (self.other_inquiry, self.unassigned):
            for action in ("update", "delete"):
                with self.subTest(inquiry=inquiry, action=action):
                    self.assertEqual(self.client.get(self.url(action, inquiry)).status_code, 403)
                    self.assertEqual(self.client.post(self.url(action, inquiry), self.data()).status_code, 403)
        self.other_inquiry.refresh_from_db()
        self.unassigned.refresh_from_db()
        self.assertEqual(self.other_inquiry.agent_id, self.other_agent.pk)
        self.assertIsNone(self.unassigned.agent_id)

    def test_admin_can_create_unassigned_assign_reassign_and_delete(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(agent=""))
        inquiry = Inquiry.objects.latest("pk")
        self.assertRedirects(response, inquiry.get_absolute_url())
        self.assertIsNone(inquiry.agent)
        for agent in (self.agent, self.other_agent):
            response = self.client.post(self.url("update", inquiry), self.data(agent=str(agent.pk), status="Negotiation"))
            self.assertRedirects(response, inquiry.get_absolute_url())
            inquiry.refresh_from_db()
            self.assertEqual(inquiry.agent_id, agent.pk)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(self.url("update", inquiry), self.data()).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(self.url("delete", inquiry)), self.url("list"))
        self.assertFalse(Inquiry.objects.filter(pk=inquiry.pk).exists())

    def test_agent_can_delete_own_only_by_post_with_csrf(self):
        self.client.force_login(self.agent)
        url = self.url("delete", self.inquiry)
        self.assertContains(self.client.get(url), 'id="deleteInquiryModal"')
        self.assertTrue(Inquiry.objects.filter(pk=self.inquiry.pk).exists())
        self.assertEqual(self.client.delete(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.agent)
        self.assertEqual(client.post(url).status_code, 403)
        self.assertRedirects(self.client.post(url), self.url("list"))
        self.assertFalse(Inquiry.objects.filter(pk=self.inquiry.pk).exists())

    def test_search_and_combined_status_agent_filters(self):
        self.client.force_login(self.agent)
        for params, expected in (
            ({"q": self.inquiry.inquiry_code}, [self.inquiry]),
            ({"q": "  CHAN  "}, [self.other_inquiry]),
            ({"q": "Garden House", "agent": str(self.agent.pk)}, [self.inquiry]),
            ({"q": "evening"}, [self.other_inquiry]),
            ({"status": "Contacted", "agent": str(self.other_agent.pk)}, [self.other_inquiry]),
            ({"agent": "unassigned"}, [self.unassigned]),
            ({"status": "Completed"}, []),
            ({"agent": "invalid"}, []),
            ({"agent": "9" * 100}, []),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url("list"), params)
                self.assertEqual(list(response.context["inquiries"]), expected)

    def test_pagination_preserves_filters(self):
        for _ in range(21):
            Inquiry.objects.create(customer=self.customer, property=self.property, agent=self.agent, message="Pagination test")
        self.client.force_login(self.agent)
        filters = {"q": "Pagination", "status": "New", "agent": str(self.agent.pk)}
        response = self.client.get(self.url("list"), filters)
        self.assertEqual(len(response.context["inquiries"]), 20)
        self.assertContains(response, f'q=Pagination&amp;status=New&amp;agent={self.agent.pk}&amp;page=2')
        self.assertEqual(len(self.client.get(self.url("list"), {**filters, "page": 2}).context["inquiries"]), 1)

    def test_invalid_fields_and_admin_agent_assignment_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(customer="", property="999999", agent=str(self.admin.pk), inquiry_date="2026-02-30", status="Invalid"))
        self.assertEqual(set(response.context["form"].errors), {"customer", "property", "agent", "inquiry_date", "status"})
        self.assertEqual(Inquiry.objects.count(), 3)
        self.inquiry.agent = self.admin
        with self.assertRaises(ValidationError):
            self.inquiry.clean()

    def test_codes_defaults_and_model_validation(self):
        self.assertEqual(self.inquiry.inquiry_code, f"INQ-{self.inquiry.pk:06d}")
        self.assertEqual(self.inquiry.inquiry_date, timezone.localdate())
        self.assertEqual(self.inquiry.status, Inquiry.Status.NEW)
        self.inquiry.full_clean()
        removed_code = self.unassigned.inquiry_code
        self.unassigned.delete()
        inquiry = Inquiry.objects.create(customer=self.customer, property=self.property)
        self.assertNotIn(inquiry.inquiry_code, (removed_code, self.inquiry.inquiry_code))

    def test_inquiry_protects_customer_property_and_agent_from_deletion(self):
        for obj in (self.customer, self.property, self.agent):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()
        self.client.force_login(self.admin)
        for model, obj in (("customer", self.customer), ("property", self.property)):
            response = self.client.post(reverse(f"core:{model}_delete", kwargs={"pk": obj.pk}), follow=True)
            self.assertRedirects(response, obj.get_absolute_url())
            self.assertContains(response, "has linked records and cannot be deleted")
        self.assertEqual(Inquiry.objects.count(), 3)

    def test_unknown_role_is_denied(self):
        self.agent.role = "unknown"
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url("list")).status_code, 403)
        self.assertEqual(self.client.post(self.url("create"), self.data()).status_code, 403)

    def test_django_admin_cannot_bypass_role_permissions(self):
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_inquiry_changelist")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:core_inquiry_add"), self.data()).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_inquiry_changelist")).status_code, 200)


class AppointmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password="admin123", role=User.Role.ADMIN, is_staff=True)
        cls.agent = User.objects.create_user("agent", password="agent123", role=User.Role.AGENT)
        cls.other_agent = User.objects.create_user("other", password="agent123", role=User.Role.AGENT)
        cls.customer = Customer.objects.create(full_name="Sok Dara", phone="012345678", customer_type="Buyer")
        cls.property = Property.objects.create(name="Garden House", property_type="House", location="Phnom Penh", price=100000, size=100, bedrooms=2, bathrooms=1, assigned_agent=cls.other_agent)
        cls.appointment = Appointment.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, appointment_date=date(2026, 10, 1), appointment_time=time(9, 30), notes="Morning viewing")
        cls.other = Appointment.objects.create(customer=cls.customer, property=cls.property, agent=cls.other_agent, appointment_date=date(2026, 10, 2), appointment_time=time(14), status="Completed", notes="Afternoon viewing")

    def url(self, action, appointment=None):
        return reverse(f"core:appointment_{action}", kwargs={"pk": appointment.pk} if appointment else None)

    def data(self, **overrides):
        return {"customer": str(self.customer.pk), "property": str(self.property.pk), "agent": str(self.agent.pk), "appointment_date": "2026-10-03", "appointment_time": "15:45", "notes": "View the property.", "status": "Scheduled", **overrides}

    def test_routes_require_login_and_unknown_roles_are_blocked(self):
        for action, obj in (("list", None), ("create", None), ("detail", self.appointment), ("update", self.appointment), ("delete", self.appointment)):
            with self.subTest(action=action):
                url = self.url(action, obj)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
                self.assertEqual(self.client.post(url, self.data()).status_code, 302)
        self.agent.role = "unknown"
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url("list")).status_code, 403)
        self.assertEqual(self.client.post(self.url("create"), self.data()).status_code, 403)

    def test_agent_can_view_all_appointments_and_links_but_only_own_actions(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("list"))
        self.assertContains(response, self.appointment.appointment_code)
        self.assertContains(response, self.other.appointment_code)
        self.assertContains(response, self.url("update", self.appointment))
        self.assertNotContains(response, self.url("update", self.other))
        detail = self.client.get(self.appointment.get_absolute_url())
        self.assertContains(detail, "2026-10-01")
        self.assertContains(detail, "09:30")
        self.assertContains(detail, self.customer.get_absolute_url())
        self.assertContains(detail, self.property.get_absolute_url())
        self.assertNotContains(self.client.get(self.other.get_absolute_url()), self.url("delete", self.other))

    def test_agent_create_ignores_tampered_assignment_and_saves_schedule(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("create"))
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'type="time"')
        for assignment in ("", str(self.other_agent.pk), str(self.admin.pk), "invalid"):
            with self.subTest(assignment=assignment):
                response = self.client.post(self.url("create"), self.data(agent=assignment))
                appointment = Appointment.objects.latest("pk")
                self.assertRedirects(response, appointment.get_absolute_url())
                self.assertEqual(appointment.agent_id, self.agent.pk)
                self.assertEqual(appointment.appointment_date, date(2026, 10, 3))
                self.assertEqual(appointment.appointment_time, time(15, 45))
                self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

    def test_agent_can_reschedule_and_change_status_without_reassignment(self):
        self.client.force_login(self.agent)
        code = self.appointment.appointment_code
        inquiry = Inquiry.objects.create(customer=self.customer, property=self.property, agent=self.agent)
        response = self.client.get(self.url("update", self.appointment))
        self.assertContains(response, 'value="09:30"')
        for status in Appointment.Status.values:
            with self.subTest(status=status):
                response = self.client.post(self.url("update", self.appointment), self.data(status=status, agent=str(self.other_agent.pk), appointment_code="APT-999999"))
                self.assertRedirects(response, self.appointment.get_absolute_url())
                self.appointment.refresh_from_db()
                self.assertEqual(self.appointment.status, status)
                self.assertEqual(self.appointment.appointment_time, time(15, 45))
                self.assertEqual(self.appointment.agent_id, self.agent.pk)
                self.assertEqual(self.appointment.appointment_code, code)
        self.property.refresh_from_db()
        inquiry.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)
        self.assertEqual(inquiry.status, Inquiry.Status.NEW)

    def test_agent_cannot_change_other_appointments(self):
        self.client.force_login(self.agent)
        for action in ("update", "delete"):
            self.assertEqual(self.client.get(self.url(action, self.other)).status_code, 403)
            self.assertEqual(self.client.post(self.url(action, self.other), self.data()).status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, Appointment.Status.COMPLETED)
        self.assertEqual(self.other.agent_id, self.other_agent.pk)

    def test_admin_full_crud_and_reassignment(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data())
        appointment = Appointment.objects.latest("pk")
        self.assertRedirects(response, appointment.get_absolute_url())
        response = self.client.post(self.url("update", appointment), self.data(agent=str(self.other_agent.pk), status="Cancelled"))
        self.assertRedirects(response, appointment.get_absolute_url())
        appointment.refresh_from_db()
        self.assertEqual(appointment.agent_id, self.other_agent.pk)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(self.url("update", appointment), self.data()).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(self.url("delete", appointment)), self.url("list"))
        self.assertFalse(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_own_delete_uses_confirmation_and_csrf_protected_post(self):
        self.client.force_login(self.agent)
        url = self.url("delete", self.appointment)
        self.assertContains(self.client.get(url), 'id="deleteAppointmentModal"')
        self.assertTrue(Appointment.objects.filter(pk=self.appointment.pk).exists())
        self.assertEqual(self.client.delete(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.agent)
        self.assertEqual(client.post(url).status_code, 403)
        self.assertRedirects(self.client.post(url), self.url("list"))
        self.assertFalse(Appointment.objects.filter(pk=self.appointment.pk).exists())

    def test_search_filters_and_malformed_agent_ids(self):
        self.client.force_login(self.agent)
        for params, expected in (
            ({"q": self.appointment.appointment_code}, [self.appointment]),
            ({"q": "  sok  ", "status": "Scheduled"}, [self.appointment]),
            ({"q": "Garden House", "agent": str(self.other_agent.pk)}, [self.other]),
            ({"q": "morning"}, [self.appointment]),
            ({"status": "Completed", "agent": str(self.other_agent.pk)}, [self.other]),
            ({"status": "Cancelled"}, []),
            ({"agent": "invalid"}, []),
            ({"agent": "9" * 100}, []),
        ):
            with self.subTest(params=params):
                self.assertEqual(list(self.client.get(self.url("list"), params).context["appointments"]), expected)

    def test_pagination_preserves_filters(self):
        for _ in range(21):
            Appointment.objects.create(customer=self.customer, property=self.property, agent=self.agent, appointment_time=time(10), notes="Pagination test")
        self.client.force_login(self.agent)
        filters = {"q": "Pagination", "status": "Scheduled", "agent": str(self.agent.pk)}
        response = self.client.get(self.url("list"), filters)
        self.assertEqual(len(response.context["appointments"]), 20)
        self.assertContains(response, f'q=Pagination&amp;status=Scheduled&amp;agent={self.agent.pk}&amp;page=2')
        self.assertEqual(len(self.client.get(self.url("list"), {**filters, "page": 2}).context["appointments"]), 1)

    def test_invalid_schedule_relations_and_assignment_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(customer="", property="999999", agent=str(self.admin.pk), appointment_date="2026-02-30", appointment_time="25:00", status="Invalid"))
        self.assertEqual(set(response.context["form"].errors), {"customer", "property", "agent", "appointment_date", "appointment_time", "status"})
        response = self.client.post(self.url("create"), self.data(agent="", appointment_time=""))
        self.assertEqual(set(response.context["form"].errors), {"agent", "appointment_time"})
        self.assertEqual(Appointment.objects.count(), 2)
        self.appointment.agent = self.admin
        with self.assertRaises(ValidationError):
            self.appointment.clean()

    def test_codes_defaults_and_historical_appointments(self):
        appointment = Appointment.objects.create(customer=self.customer, property=self.property, agent=self.agent, appointment_time=time(10))
        self.assertEqual(appointment.appointment_code, f"APT-{appointment.pk:06d}")
        self.assertEqual(appointment.appointment_date, timezone.localdate())
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)
        appointment.full_clean()
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(appointment_date="2020-01-01", status="Completed", notes=""))
        historical = Appointment.objects.latest("pk")
        self.assertRedirects(response, historical.get_absolute_url())
        self.assertEqual(historical.appointment_date, date(2020, 1, 1))

    def test_appointment_protects_customer_property_and_agent(self):
        for obj in (self.customer, self.property, self.agent):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()
        self.client.force_login(self.admin)
        for model, obj in (("customer", self.customer), ("property", self.property)):
            response = self.client.post(reverse(f"core:{model}_delete", kwargs={"pk": obj.pk}), follow=True)
            self.assertRedirects(response, obj.get_absolute_url())
            self.assertContains(response, "has linked records and cannot be deleted")
        self.assertEqual(Appointment.objects.count(), 2)

    def test_django_admin_enforces_roles(self):
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_appointment_changelist")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:core_appointment_add"), self.data()).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_appointment_changelist")).status_code, 200)


class TransactionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin", password="admin123", role=User.Role.ADMIN, is_staff=True)
        cls.agent = User.objects.create_user("agent", password="agent123", role=User.Role.AGENT)
        cls.other_agent = User.objects.create_user("other", password="agent123", role=User.Role.AGENT)
        cls.customer = Customer.objects.create(full_name="Sok Dara", phone="012345678", customer_type="Buyer")
        cls.other_customer = Customer.objects.create(full_name="Chan Sreyneang", phone="098765432", customer_type="Tenant")
        cls.property = Property.objects.create(name="Garden House", property_type="House", location="Phnom Penh", price=100000, size=100, bedrooms=2, bathrooms=1, assigned_agent=cls.other_agent)
        cls.other_property = Property.objects.create(name="River Apartment", property_type="Apartment", location="Kampot", price=500, size=80, bedrooms=2, bathrooms=1)
        cls.inquiry = Inquiry.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent)
        cls.other_inquiry = Inquiry.objects.create(customer=cls.other_customer, property=cls.other_property, agent=cls.other_agent)
        cls.transaction = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, transaction_type="Sale", amount="95000.25")
        cls.other = Transaction.objects.create(customer=cls.other_customer, property=cls.other_property, agent=cls.other_agent, transaction_type="Rental", amount="500.00", start_date=date(2026, 10, 1), end_date=date(2027, 10, 1))

    def url(self, action, obj=None):
        return reverse(f"core:transaction_{action}", kwargs={"pk": obj.pk} if obj else None)

    def data(self, **overrides):
        return {"customer": str(self.customer.pk), "property": str(self.property.pk), "agent": str(self.agent.pk), "inquiry": "", "transaction_type": "Sale", "amount": "95000.25", "transaction_date": "2026-10-01", "status": "Pending", "start_date": "", "end_date": "", **overrides}

    def test_login_and_role_checks(self):
        for action, obj in (("list", None), ("create", None), ("detail", self.transaction), ("update", self.transaction), ("delete", self.transaction)):
            with self.subTest(action=action):
                url = self.url(action, obj)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
                self.assertEqual(self.client.post(url, self.data()).status_code, 302)
        self.agent.role = "unknown"
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url("list")).status_code, 403)

    def test_agent_views_all_but_cannot_mutate_other_transactions(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url("list"))
        self.assertContains(response, self.transaction.transaction_code)
        self.assertContains(response, self.other.transaction_code)
        self.assertContains(response, self.url("update", self.transaction))
        self.assertNotContains(response, self.url("update", self.other))
        self.assertEqual(self.client.get(self.other.get_absolute_url()).status_code, 200)
        for action in ("update", "delete"):
            self.assertEqual(self.client.get(self.url(action, self.other)).status_code, 403)
            self.assertEqual(self.client.post(self.url(action, self.other), self.data(status="Completed")).status_code, 403)
        self.other.refresh_from_db()
        self.assertEqual(self.other.status, Transaction.Status.PENDING)

    def test_agent_create_forces_self_assignment(self):
        self.client.force_login(self.agent)
        for agent in ("", str(self.other_agent.pk), str(self.admin.pk), "invalid"):
            with self.subTest(agent=agent):
                response = self.client.post(self.url("create"), self.data(agent=agent))
                obj = Transaction.objects.latest("pk")
                self.assertRedirects(response, obj.get_absolute_url())
                self.assertEqual(obj.agent_id, self.agent.pk)
                self.assertEqual(obj.amount, Decimal("95000.25"))
                self.assertEqual(obj.transaction_code, f"TRN-{obj.pk:06d}")
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)

    def test_sale_completion_updates_property_and_agent_cannot_reassign(self):
        self.client.force_login(self.agent)
        code = self.transaction.transaction_code
        response = self.client.post(self.url("update", self.transaction), self.data(status="Completed", agent=str(self.other_agent.pk)))
        self.assertRedirects(response, self.transaction.get_absolute_url())
        self.transaction.refresh_from_db()
        self.property.refresh_from_db()
        self.assertEqual(self.transaction.status, Transaction.Status.COMPLETED)
        self.assertEqual(self.transaction.agent_id, self.agent.pk)
        self.assertEqual(self.transaction.transaction_code, code)
        self.assertEqual(self.property.status, Property.Status.SOLD)
        self.assertContains(self.client.get(self.transaction.get_absolute_url()), "Sold")

    def test_rental_completion_updates_property_and_dates(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("update", self.other), self.data(customer=self.other_customer.pk, property=self.other_property.pk, agent=self.other_agent.pk, transaction_type="Rental", amount="525.50", start_date="2026-10-01", end_date="2027-10-01", status="Completed"))
        self.assertRedirects(response, self.other.get_absolute_url())
        self.other.refresh_from_db()
        self.other_property.refresh_from_db()
        self.assertEqual(self.other_property.status, Property.Status.RENTED)
        self.assertEqual(self.other.amount, Decimal("525.50"))
        self.assertEqual(self.other.end_date, date(2027, 10, 1))
        self.assertContains(self.client.get(self.other.get_absolute_url()), "Monthly rent")

    def test_rental_requires_both_dates_and_strictly_later_end(self):
        self.client.force_login(self.admin)
        for start, end, fields in (("", "", {"start_date", "end_date"}), ("2026-10-01", "", {"end_date"}), ("", "2027-10-01", {"start_date"}), ("2026-10-01", "2026-10-01", {"end_date"}), ("2026-10-01", "2026-09-30", {"end_date"})):
            with self.subTest(start=start, end=end):
                response = self.client.post(self.url("create"), self.data(transaction_type="Rental", start_date=start, end_date=end))
                self.assertEqual(set(response.context["form"].errors), fields)
        self.assertEqual(Transaction.objects.count(), 2)
        self.other.end_date = self.other.start_date
        with self.assertRaises(ValidationError):
            self.other.clean()

    def test_sale_discards_rental_dates_and_invalid_fields_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(start_date="2026-10-01", end_date="2027-10-01"))
        obj = Transaction.objects.latest("pk")
        self.assertRedirects(response, obj.get_absolute_url())
        self.assertIsNone(obj.start_date)
        self.assertIsNone(obj.end_date)
        response = self.client.post(self.url("create"), self.data(amount="-1", agent=self.admin.pk, customer="", property="999999", status="Invalid", transaction_date="2026-02-30"))
        self.assertEqual(set(response.context["form"].errors), {"amount", "agent", "customer", "property", "status", "transaction_date"})

    def test_cancellation_releases_only_reserved_property(self):
        for status in Property.Status.values:
            with self.subTest(property_status=status):
                self.property.status = status
                self.property.save()
                self.transaction.status = Transaction.Status.CANCELLED
                self.transaction.save()
                self.property.refresh_from_db()
                expected = Property.Status.AVAILABLE if status == Property.Status.RESERVED else status
                self.assertEqual(self.property.status, expected)
                # Use a separate pending transaction for each status case.
                if status != Property.Status.values[-1]:
                    self.property.status = Property.Status.AVAILABLE
                    self.property.save()
                    self.transaction = Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, transaction_type="Sale", amount=1)

    def test_sold_property_excluded_and_tampered_creation_rejected(self):
        self.property.status = Property.Status.SOLD
        self.property.save()
        self.client.force_login(self.admin)
        response = self.client.get(self.url("create"))
        self.assertNotIn(self.property, response.context["form"].fields["property"].queryset)
        response = self.client.post(self.url("create"), self.data(property=self.property.pk))
        self.assertIn("property", response.context["form"].errors)
        with self.assertRaises(ValidationError):
            Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, transaction_type="Sale", amount=1)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_stale_property_cache_cannot_complete_a_second_sale(self):
        competing = Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, transaction_type="Sale", amount=1)
        self.assertEqual(competing.property.status, Property.Status.AVAILABLE)
        self.transaction.status = Transaction.Status.COMPLETED
        self.transaction.save()
        competing.status = Transaction.Status.COMPLETED
        with self.assertRaises(ValidationError):
            competing.save()
        competing.refresh_from_db()
        self.assertEqual(competing.status, Transaction.Status.PENDING)

    def test_completed_edit_does_not_reapply_property_side_effects(self):
        self.transaction.status = Transaction.Status.COMPLETED
        self.transaction.save()
        self.client.force_login(self.agent)
        response = self.client.get(self.url("update", self.transaction))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url("update", self.transaction), self.data(status="Completed", amount="96000.00"))
        self.assertRedirects(response, self.transaction.get_absolute_url())
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount, Decimal("96000.00"))
        self.transaction.status = Transaction.Status.CANCELLED
        self.transaction.save()
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.SOLD)

    def test_terminal_transactions_cannot_reopen_or_change_property_type(self):
        self.transaction.status = Transaction.Status.COMPLETED
        self.transaction.save()
        for field, value in (("status", "Pending"), ("property", self.other_property), ("transaction_type", "Rental")):
            with self.subTest(field=field):
                self.transaction.refresh_from_db()
                setattr(self.transaction, field, value)
                with self.assertRaises(ValidationError):
                    self.transaction.save()
        self.transaction.refresh_from_db()
        self.transaction.status = Transaction.Status.CANCELLED
        self.transaction.save()
        self.transaction.status = Transaction.Status.COMPLETED
        with self.assertRaises(ValidationError):
            self.transaction.save()

    def test_create_from_inquiry_prefills_locks_relations_and_completes_source(self):
        self.client.force_login(self.agent)
        url = reverse("core:transaction_create_from_inquiry", kwargs={"inquiry_pk": self.inquiry.pk})
        response = self.client.get(url)
        self.assertEqual(response.context["form"].initial["customer"], self.customer.pk)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.NEW)
        response = self.client.post(url, self.data(inquiry=self.other_inquiry.pk, customer=self.other_customer.pk, property=self.other_property.pk))
        obj = Transaction.objects.latest("pk")
        self.assertRedirects(response, obj.get_absolute_url())
        self.assertEqual((obj.inquiry_id, obj.customer_id, obj.property_id), (self.inquiry.pk, self.customer.pk, self.property.pk))
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.COMPLETED)
        self.assertContains(self.client.get(obj.get_absolute_url()), self.inquiry.get_absolute_url())

    def test_inquiry_permissions_apply_to_both_source_route_and_regular_form(self):
        self.client.force_login(self.agent)
        url = reverse("core:transaction_create_from_inquiry", kwargs={"inquiry_pk": self.other_inquiry.pk})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.data()).status_code, 403)
        response = self.client.post(self.url("create"), self.data(inquiry=self.other_inquiry.pk, customer=self.other_customer.pk, property=self.other_property.pk))
        self.assertIn("inquiry", response.context["form"].errors)
        self.other_inquiry.refresh_from_db()
        self.assertEqual(self.other_inquiry.status, Inquiry.Status.NEW)

    def test_invalid_source_transaction_has_no_side_effects(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("create"), self.data(inquiry=self.inquiry.pk, customer=self.other_customer.pk, property=self.other_property.pk))
        self.assertIn("customer", response.context["form"].errors)
        self.assertIn("property", response.context["form"].errors)
        source_url = reverse("core:transaction_create_from_inquiry", kwargs={"inquiry_pk": self.inquiry.pk})
        response = self.client.post(source_url, self.data(transaction_type="Rental", status="Completed"))
        self.assertIn("start_date", response.context["form"].errors)
        self.inquiry.refresh_from_db()
        self.property.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.NEW)
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_source_inquiry_cannot_be_replaced_on_update(self):
        obj = Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, inquiry=self.inquiry, transaction_type="Sale", amount=1)
        obj.inquiry = None
        with self.assertRaises(ValidationError):
            obj.save()
        obj.refresh_from_db()
        self.assertEqual(obj.inquiry_id, self.inquiry.pk)

    def test_atomic_rollback_includes_transaction_inquiry_and_property(self):
        from django.db.models.query import QuerySet
        original_update = QuerySet.update

        def fail_property_update(queryset, **kwargs):
            if queryset.model is Property:
                raise RuntimeError("Simulated property update failure")
            return original_update(queryset, **kwargs)

        with patch.object(QuerySet, "update", fail_property_update), self.assertRaises(RuntimeError):
            Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, inquiry=self.inquiry, transaction_type="Sale", amount=1, status="Completed")
        self.inquiry.refresh_from_db()
        self.property.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(self.inquiry.status, Inquiry.Status.NEW)
        self.assertEqual(self.property.status, Property.Status.AVAILABLE)

    def test_admin_reassigns_and_old_agent_loses_edit_access(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url("update", self.transaction), self.data(agent=self.other_agent.pk))
        self.assertRedirects(response, self.transaction.get_absolute_url())
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(self.url("update", self.transaction), self.data()).status_code, 403)

    def test_delete_uses_modal_and_csrf_and_does_not_undo_completion(self):
        self.transaction.status = Transaction.Status.COMPLETED
        self.transaction.save()
        self.client.force_login(self.agent)
        url = self.url("delete", self.transaction)
        self.assertContains(self.client.get(url), 'id="deleteTransactionModal"')
        self.assertTrue(Transaction.objects.filter(pk=self.transaction.pk).exists())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.agent)
        self.assertEqual(client.post(url).status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertRedirects(self.client.post(url), self.url("list"))
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.SOLD)

    def test_transaction_foreign_keys_protect_history(self):
        obj = Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, inquiry=self.inquiry, transaction_type="Sale", amount=1)
        for target in (self.customer, self.property, self.agent, self.inquiry):
            with self.subTest(model=type(target).__name__), self.assertRaises(ProtectedError):
                target.delete()
        obj.refresh_from_db()

    def test_search_filters_and_pagination(self):
        self.client.force_login(self.agent)
        for params, expected in (({"q": self.transaction.transaction_code}, [self.transaction]), ({"q": "  river  ", "transaction_type": "Rental", "status": "Pending"}, [self.other]), ({"q": "Sok", "transaction_type": "Rental"}, [])):
            with self.subTest(params=params):
                self.assertEqual(list(self.client.get(self.url("list"), params).context["transactions"]), expected)
        for _ in range(21):
            Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, transaction_type="Sale", amount=1)
        filters = {"q": "Sok", "transaction_type": "Sale", "status": "Pending"}
        response = self.client.get(self.url("list"), filters)
        self.assertEqual(len(response.context["transactions"]), 20)
        self.assertContains(response, "q=Sok&amp;transaction_type=Sale&amp;status=Pending&amp;page=2")
        self.assertEqual(len(self.client.get(self.url("list"), {**filters, "page": 2}).context["transactions"]), 2)

    def test_django_admin_cannot_bypass_roles_and_uses_property_side_effects(self):
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_transaction_changelist")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_transaction_add")).status_code, 200)
        response = self.client.post(reverse("admin:core_transaction_add"), {**self.data(status="Completed"), "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, Property.Status.SOLD)


class ContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("contract-admin", role="admin", is_staff=True)
        cls.agent = User.objects.create_user("contract-agent", role="agent")
        cls.other_agent = User.objects.create_user("contract-other", role="agent")
        cls.customer = Customer.objects.create(full_name="Contract Buyer", phone="012345678", customer_type="Buyer")
        cls.property = Property.objects.create(name="Contract House", property_type="House", location="Kampot", price=100, size=50, bedrooms=1, bathrooms=1)
        cls.transaction = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, transaction_type="Sale", amount=100)
        cls.other = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.other_agent, transaction_type="Sale", amount=100)
        cls.contract = Contract.objects.create(contract_number="CON-001", transaction=cls.transaction, customer=cls.customer, property=cls.property, contract_type="Sale", amount=100)

    def data(self, **overrides):
        return {"contract_number": "CON-002", "transaction": self.transaction.pk, "customer": self.customer.pk, "property": self.property.pk, "contract_type": "Sale", "amount": "100.00", "start_date": "2026-09-24", "end_date": "", "status": "Draft", "description": "Demo contract", **overrides}

    def test_contract_crud_and_transaction_prefill(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("core:contract_create"), {"transaction": self.transaction.pk})
        self.assertEqual(response.context["form"].initial["customer"], self.customer.pk)
        response = self.client.post(reverse("core:contract_create"), self.data())
        created = Contract.objects.get(contract_number="CON-002")
        self.assertRedirects(response, created.get_absolute_url())
        self.assertContains(self.client.get(created.get_absolute_url()), "Demo contract")
        self.assertRedirects(self.client.post(reverse("core:contract_update", args=[created.pk]), self.data(status="Active")), created.get_absolute_url())
        created.refresh_from_db()
        self.assertEqual(created.status, "Active")
        self.assertContains(self.client.get(reverse("core:contract_delete", args=[created.pk])), 'class="modal fade"')
        self.assertTrue(Contract.objects.filter(pk=created.pk).exists())
        self.assertRedirects(self.client.post(reverse("core:contract_delete", args=[created.pk])), reverse("core:contract_list"))

    def test_contract_permissions_and_tampered_transaction(self):
        self.assertEqual(self.client.get(reverse("core:contract_list")).status_code, 302)
        self.client.force_login(self.other_agent)
        self.assertEqual(self.client.get(self.contract.get_absolute_url()).status_code, 200)
        for action in ("update", "delete"):
            url = reverse(f"core:contract_{action}", args=[self.contract.pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.data()).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:contract_create"), {"transaction": self.transaction.pk}).status_code, 403)
        response = self.client.post(reverse("core:contract_create"), self.data())
        self.assertIn("transaction", response.context["form"].errors)
        self.client.force_login(self.agent)
        response = self.client.post(reverse("core:contract_update", args=[self.contract.pk]), self.data(transaction=self.other.pk))
        self.assertIn("transaction", response.context["form"].errors)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("core:contract_update", args=[self.contract.pk])).status_code, 200)

    def test_contract_validation_and_unique_number(self):
        self.client.force_login(self.admin)
        other_customer = Customer.objects.create(full_name="Other", phone="1", customer_type="Buyer")
        for overrides, field in (({"customer": other_customer.pk}, "customer"), ({"contract_type": "Rental"}, "contract_type"), ({"end_date": "2026-09-24"}, "end_date"), ({"amount": "-1"}, "amount"), ({"contract_number": "CON-001"}, "contract_number"), ({"transaction": "999999"}, "transaction")):
            with self.subTest(field=field):
                response = self.client.post(reverse("core:contract_create"), self.data(**overrides))
                self.assertIn(field, response.context["form"].errors)
        self.assertEqual(Contract.objects.count(), 1)

    def test_contract_search_filter_and_protected_history(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("core:contract_list"), {"q": "CON-001", "status": "Draft"})
        self.assertEqual(list(response.context["object_list"]), [self.contract])
        self.assertEqual(len(self.client.get(reverse("core:contract_list"), {"status": "Active"}).context["object_list"]), 0)
        with self.assertRaises(ProtectedError):
            self.transaction.delete()
        response = self.client.post(reverse("core:transaction_delete", args=[self.transaction.pk]), follow=True)
        self.assertContains(response, "has linked records")

    def test_contract_delete_csrf_and_admin_role(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.agent)
        self.assertEqual(client.post(reverse("core:contract_delete", args=[self.contract.pk])).status_code, 403)
        self.agent.is_staff = True
        self.agent.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("admin:core_contract_changelist")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_contract_add")).status_code, 200)

    def test_rental_contract_dates_and_property_must_match(self):
        self.client.force_login(self.agent)
        rental = Transaction.objects.create(customer=self.customer, property=self.property, agent=self.agent, transaction_type="Rental", amount=100, start_date=date(2026, 10, 1), end_date=date(2027, 10, 1))
        data = self.data(transaction=rental.pk, contract_type="Rental", start_date="2026-10-01")
        for end_date in ("", "2026-10-01", "2026-09-30"):
            response = self.client.post(reverse("core:contract_create"), {**data, "end_date": end_date})
            self.assertIn("end_date", response.context["form"].errors)
        other_property = Property.objects.create(name="Other Contract House", property_type="House", location="Kampot", price=100, size=50, bedrooms=1, bathrooms=1)
        response = self.client.post(reverse("core:contract_create"), {**data, "end_date": "2027-10-01", "property": other_property.pk})
        self.assertIn("property", response.context["form"].errors)
        self.assertEqual(self.client.post(reverse("core:contract_create"), {**data, "end_date": "2027-10-01"}).status_code, 302)

    def test_contract_preserves_transaction_links_and_follows_reassignment(self):
        other_customer = Customer.objects.create(full_name="Different Buyer", phone="2", customer_type="Buyer")
        self.transaction.customer = other_customer
        with self.assertRaises(ValidationError):
            self.transaction.save()
        self.transaction.refresh_from_db()
        self.transaction.transaction_type = "Rental"
        self.transaction.start_date = date(2026, 10, 1)
        self.transaction.end_date = date(2027, 10, 1)
        with self.assertRaises(ValidationError):
            self.transaction.save()
        self.transaction.refresh_from_db()
        self.transaction.agent = self.other_agent
        self.transaction.save()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("core:contract_update", args=[self.contract.pk])).status_code, 403)
        self.client.force_login(self.other_agent)
        self.assertEqual(self.client.get(reverse("core:contract_update", args=[self.contract.pk])).status_code, 200)



class PaymentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("payment-admin", role="admin", is_staff=True)
        cls.agent = User.objects.create_user("payment-agent", role="agent")
        cls.other_agent = User.objects.create_user("payment-other", role="agent")
        cls.customer = Customer.objects.create(full_name="Payment Buyer", phone="012345678", customer_type="Buyer")
        cls.property = Property.objects.create(name="Payment House", property_type="House", location="Kampot", price=100, size=50, bedrooms=1, bathrooms=1)
        cls.transaction = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, transaction_type="Sale", amount=100)
        cls.other = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.other_agent, transaction_type="Sale", amount=100)
        cls.payment = Payment.objects.create(transaction=cls.transaction, customer=cls.customer, amount=50, payment_method="Cash")

    def data(self, **overrides):
        return {"transaction": self.transaction.pk, "customer": self.customer.pk, "amount": "5000.25", "payment_date": "2026-09-24", "payment_method": "Cash", "status": "Pending", "note": "Deposit", **overrides}

    def test_payment_crud_and_no_balance_enforcement(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.payment.status, "Pending")
        response = self.client.post(reverse("core:payment_create"), self.data())
        created = Payment.objects.exclude(pk=self.payment.pk).get()
        self.assertRedirects(response, created.get_absolute_url())
        self.assertEqual(created.amount, Decimal("5000.25"))
        self.assertRedirects(self.client.post(reverse("core:payment_update", args=[created.pk]), self.data(status="Paid")), created.get_absolute_url())
        created.refresh_from_db()
        self.assertEqual(created.status, "Paid")
        self.property.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.property.status, "Available")
        self.assertEqual(self.transaction.status, "Pending")
        self.assertContains(self.client.get(reverse("core:payment_delete", args=[created.pk])), 'class="modal fade"')
        self.assertTrue(Payment.objects.filter(pk=created.pk).exists())
        self.assertRedirects(self.client.post(reverse("core:payment_delete", args=[created.pk])), reverse("core:payment_list"))

    def test_payment_permissions_and_assignment_changes(self):
        self.assertEqual(self.client.get(reverse("core:payment_list")).status_code, 302)
        self.client.force_login(self.other_agent)
        self.assertEqual(self.client.get(self.payment.get_absolute_url()).status_code, 200)
        for action in ("update", "delete"):
            url = reverse(f"core:payment_{action}", args=[self.payment.pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.data()).status_code, 403)
        response = self.client.post(reverse("core:payment_create"), self.data())
        self.assertIn("transaction", response.context["form"].errors)
        self.client.force_login(self.agent)
        response = self.client.post(reverse("core:payment_update", args=[self.payment.pk]), self.data(transaction=self.other.pk))
        self.assertIn("transaction", response.context["form"].errors)
        self.transaction.agent = self.other_agent
        self.transaction.save()
        self.assertEqual(self.client.get(reverse("core:payment_update", args=[self.payment.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("core:payment_update", args=[self.payment.pk])).status_code, 200)

    def test_payment_validation_and_transaction_history(self):
        self.client.force_login(self.agent)
        other_customer = Customer.objects.create(full_name="Other Buyer", phone="1", customer_type="Buyer")
        for overrides, field in (({"customer": other_customer.pk}, "customer"), ({"amount": "-1"}, "amount"), ({"payment_method": "Gateway"}, "payment_method"), ({"payment_date": "bad"}, "payment_date"), ({"transaction": "999999"}, "transaction")):
            response = self.client.post(reverse("core:payment_create"), self.data(**overrides))
            self.assertIn(field, response.context["form"].errors)
        self.assertEqual(Payment.objects.count(), 1)
        with self.assertRaises(ProtectedError):
            self.transaction.delete()
        self.transaction.customer = other_customer
        with self.assertRaises(ValidationError):
            self.transaction.save()
        self.payment.refresh_from_db()
        self.payment.customer = other_customer
        with self.assertRaises(ValidationError):
            self.payment.full_clean()

    def test_payment_filters_pagination_and_csrf(self):
        Payment.objects.bulk_create([Payment(transaction=self.transaction, customer=self.customer, amount=1, payment_method="Cash") for _ in range(21)])
        self.client.force_login(self.agent)
        response = self.client.get(reverse("core:payment_list"), {"q": "Payment Buyer", "status": "Pending"})
        self.assertEqual(len(response.context["object_list"]), 20)
        self.assertContains(response, "q=Payment+Buyer&amp;status=Pending&amp;page=2")
        self.assertEqual(len(self.client.get(reverse("core:payment_list"), {"status": "Paid"}).context["object_list"]), 0)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.agent)
        self.assertEqual(client.post(reverse("core:payment_delete", args=[self.payment.pk])).status_code, 403)

    def test_payment_admin_role_and_prefill(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("core:payment_create"), {"transaction": self.transaction.pk})
        self.assertEqual(response.context["form"].initial["customer"], self.customer.pk)
        self.assertEqual(self.client.get(reverse("core:payment_create"), {"transaction": self.other.pk}).status_code, 403)
        self.agent.is_staff = True
        self.agent.save()
        self.assertEqual(self.client.get(reverse("admin:core_payment_changelist")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:core_payment_add")).status_code, 200)


class DashboardTests(TestCase):
    def test_dashboard_empty_and_role_access(self):
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 302)
        for role in ("admin", "agent"):
            user = User.objects.create_user(f"dashboard-{role}", role=role)
            self.client.force_login(user)
            response = self.client.get(reverse("core:dashboard"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["stats"]["paid_total"], Decimal("0.00"))
            self.assertEqual(response.context["chart_values"], [0, 0, 0, 0])
            self.assertContains(response, 'id="propertyChart"', count=1)
        user.role = "unknown"
        user.save()
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 403)

    def test_dashboard_counts_paid_total_and_upcoming_time(self):
        agent = User.objects.create_user("stats-agent", role="agent")
        customer = Customer.objects.create(full_name="Statistics Buyer", phone="1", customer_type="Buyer")
        prop = Property.objects.create(name="Statistics House", property_type="House", location="Kampot", price=100, size=50, bedrooms=1, bathrooms=1)
        deal = Transaction.objects.create(customer=customer, property=prop, agent=agent, transaction_type="Sale", amount=100)
        for amount, status in (("12.10", "Paid"), ("0.20", "Paid"), ("900", "Pending")):
            Payment.objects.create(transaction=deal, customer=customer, amount=amount, payment_method="Cash", status=status)
        now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        for appointment_time, status in ((time(11), "Scheduled"), (time(13), "Scheduled"), (time(14), "Completed")):
            Appointment.objects.create(customer=customer, property=prop, agent=agent, appointment_date=now.date(), appointment_time=appointment_time, status=status)
        self.client.force_login(agent)
        with patch("core.views.timezone.localtime", return_value=now):
            response = self.client.get(reverse("core:dashboard"))
        stats = response.context["stats"]
        self.assertEqual(stats["paid_total"], Decimal("12.30"))
        self.assertEqual(stats["total_payments"], 3)
        self.assertEqual(stats["upcoming_appointments"], 1)
        self.assertEqual(stats["available_properties"], 1)
        self.assertEqual(stats["total_transactions"], 1)


class ReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("report-agent", role="agent")
        cls.customer = Customer.objects.create(full_name="Report Buyer", phone="1", customer_type="Buyer")
        cls.property = Property.objects.create(name="Report House", property_type="House", location="Kampot", price=100, size=50, bedrooms=1, bathrooms=1)
        cls.transaction = Transaction.objects.create(customer=cls.customer, property=cls.property, agent=cls.agent, transaction_type="Sale", amount=100, transaction_date=date(2026, 9, 24))
        cls.payment = Payment.objects.create(customer=cls.customer, transaction=cls.transaction, amount=25, payment_method="Cash", status="Paid", payment_date=date(2026, 9, 24))

    def test_reports_permissions_and_all_three_tables(self):
        url = reverse("core:report_list")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.agent)
        response = self.client.get(url)
        self.assertContains(response, 'class="table table-striped table-hover"', count=3)
        self.assertEqual(list(response.context["properties"]), [self.property])
        self.assertEqual(list(response.context["transactions"]), [self.transaction])
        self.assertEqual(list(response.context["payments"]), [self.payment])
        self.agent.role = "admin"
        self.agent.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.agent.role = "unknown"
        self.agent.save()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_report_filters_dates_and_invalid_input(self):
        self.client.force_login(self.agent)
        url = reverse("core:report_list")
        response = self.client.get(url, {"q": "Report", "property_status": "Available", "property_type": "House", "transaction_type": "Sale", "transaction_status": "Pending", "payment_method": "Cash", "payment_status": "Paid", "date_from": "2026-09-24", "date_to": "2026-09-24"})
        for name in ("properties", "transactions", "payments"):
            self.assertEqual(response.context[name].paginator.count, 1)
        response = self.client.get(url, {"property_status": "Sold", "transaction_status": "Completed", "payment_status": "Pending"})
        for name in ("properties", "transactions", "payments"):
            self.assertEqual(response.context[name].paginator.count, 0)
        response = self.client.get(url, {"date_from": "2026-09-25"})
        self.assertEqual(response.context["properties"].paginator.count, 1)
        self.assertEqual(response.context["transactions"].paginator.count, 0)
        self.assertEqual(response.context["payments"].paginator.count, 0)
        for filters in ({"date_from": "invalid"}, {"date_from": "2026-09-25", "date_to": "2026-09-24"}, {"property_status": "invalid"}):
            response = self.client.get(url, filters)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(response.context["transactions"].paginator.count, 0)

    def test_report_pagination_preserves_filters(self):
        Payment.objects.bulk_create([Payment(transaction=self.transaction, customer=self.customer, amount=1, payment_method="Cash", status="Paid") for _ in range(22)])
        self.client.force_login(self.agent)
        response = self.client.get(reverse("core:report_list"), {"payment_status": "Paid"})
        self.assertEqual(len(response.context["payments"]), 20)
        self.assertContains(response, "payment_status=Paid&amp;payments_page=2#payments")
        response = self.client.get(reverse("core:report_list"), {"payment_status": "Paid", "payments_page": "2"})
        self.assertEqual(len(response.context["payments"]), 3)
        self.assertEqual(response.context["properties"].number, 1)
        self.assertEqual(self.client.get(reverse("core:report_list"), {"payments_page": "bad"}).status_code, 200)


class DemoWorkflowTests(TestCase):
    """The specified 13-step workflow, through HTTP forms, for sale and rental."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("workflow-admin", password="admin123", role="admin")
        cls.agent = User.objects.create_user("workflow-agent", password="agent123", role="agent")

    def post_success(self, route, data, *args):
        response = self.client.post(reverse(route, args=args), data)
        errors = response.context["form"].errors if response.context and "form" in response.context else response.content[:300]
        self.assertEqual(response.status_code, 302, errors)
        return response

    def run_workflow(self, deal_type):
        # 1. Admin logs in and can access the Users section.
        self.post_success("login", {"username": "workflow-admin", "password": "admin123"})
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 200)
        # 2. Add property.
        self.post_success("core:property_create", {"name": "Workflow Home", "property_type": "House", "location": "Phnom Penh", "price": "90000", "size": "120", "bedrooms": 3, "bathrooms": 2, "status": "Available", "assigned_agent": self.agent.pk})
        prop = Property.objects.get(name="Workflow Home")
        # 3. Add customer.
        self.post_success("core:customer_create", {"full_name": "Workflow Customer", "phone": "012345678", "customer_type": "Buyer" if deal_type == "Sale" else "Tenant"})
        customer = Customer.objects.get(full_name="Workflow Customer")
        # 4. Record inquiry, initially unassigned.
        inquiry_data = {"customer": customer.pk, "property": prop.pk, "inquiry_date": "2026-09-24", "status": "New", "message": "Interested in a viewing"}
        self.post_success("core:inquiry_create", inquiry_data)
        inquiry = Inquiry.objects.get(customer=customer)
        self.assertIsNone(inquiry.agent_id)
        # 5. Assign agent, then log in as that agent.
        self.post_success("core:inquiry_update", {**inquiry_data, "agent": self.agent.pk}, inquiry.pk)
        self.client.logout()
        self.post_success("login", {"username": "workflow-agent", "password": "agent123"})
        self.assertEqual(self.client.get(reverse("core:user_list")).status_code, 403)
        # 6. Schedule property viewing.
        appointment_data = {"customer": customer.pk, "property": prop.pk, "appointment_date": "2026-09-25", "appointment_time": "09:30", "status": "Scheduled"}
        self.post_success("core:appointment_create", appointment_data)
        appointment = Appointment.objects.get(customer=customer)
        self.assertEqual(appointment.agent_id, self.agent.pk)
        # 7. Complete viewing and record the customer's decision.
        self.post_success("core:appointment_update", {**appointment_data, "status": "Completed"}, appointment.pk)
        self.post_success("core:inquiry_update", {**inquiry_data, "status": "Negotiation"}, inquiry.pk)
        # 8. Create transaction from inquiry.
        deal_data = {"transaction_type": deal_type, "amount": "90000.00" if deal_type == "Sale" else "500.00", "transaction_date": "2026-09-25", "status": "Pending", "start_date": "2026-10-01" if deal_type == "Rental" else "", "end_date": "2027-10-01" if deal_type == "Rental" else ""}
        self.post_success("core:transaction_create_from_inquiry", deal_data, inquiry.pk)
        deal = Transaction.objects.get(inquiry=inquiry)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, "Completed")
        # 9. Create linked contract.
        self.post_success("core:contract_create", {"contract_number": "DEMO-001", "transaction": deal.pk, "customer": customer.pk, "property": prop.pk, "contract_type": deal_type, "start_date": "2026-10-01", "end_date": deal_data["end_date"], "amount": deal_data["amount"], "status": "Active"})
        contract = Contract.objects.get(transaction=deal)
        # 10. Record manual payment.
        self.post_success("core:payment_create", {"transaction": deal.pk, "customer": customer.pk, "amount": "5000.25", "payment_date": "2026-09-25", "payment_method": "Cash", "status": "Paid", "note": "Demo payment"})
        payment = Payment.objects.get(transaction=deal)
        # 11. Complete transaction without losing linked history.
        self.post_success("core:transaction_update", {**deal_data, "customer": customer.pk, "property": prop.pk, "status": "Completed"}, deal.pk)
        deal.refresh_from_db()
        self.assertEqual(deal.status, "Completed")
        # 12. Property reflects Sold / Rented.
        prop.refresh_from_db()
        expected_status = "Sold" if deal_type == "Sale" else "Rented"
        self.assertEqual(prop.status, expected_status)
        self.assertContains(self.client.get(deal.get_absolute_url()), contract.contract_number)
        self.assertContains(self.client.get(deal.get_absolute_url()), str(payment))
        # 13. Dashboard and filtered reports reflect the workflow.
        dashboard = self.client.get(reverse("core:dashboard"))
        self.assertEqual(dashboard.context["stats"][f"{expected_status.lower()}_properties"], 1)
        self.assertEqual(dashboard.context["stats"]["paid_total"], Decimal("5000.25"))
        self.assertEqual(dashboard.context["stats"]["total_inquiries"], 1)
        reports = self.client.get(reverse("core:report_list"), {"property_status": expected_status, "transaction_status": "Completed", "payment_status": "Paid", "date_from": "2026-09-25", "date_to": "2026-09-25"})
        self.assertEqual(list(reports.context["properties"]), [prop])
        self.assertEqual(list(reports.context["transactions"]), [deal])
        self.assertEqual(list(reports.context["payments"]), [payment])

    def test_13_step_sale_workflow(self):
        self.run_workflow("Sale")

    def test_13_step_rental_workflow(self):
        self.run_workflow("Rental")
