from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Customer, Property, User


class Command(BaseCommand):
    help = "Create demo accounts, three properties and two customers; preserve existing records."

    @transaction.atomic
    def handle(self, *args, **options):
        for username, password, role in (
            ("admin", "admin123", User.Role.ADMIN),
            ("agent", "agent123", User.Role.AGENT),
        ):
            account, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "is_staff": role == User.Role.ADMIN, "is_superuser": role == User.Role.ADMIN},
            )
            if created:
                account.set_password(password)
                account.save()
            elif account.role != role:
                self.stdout.write(self.style.WARNING(f"Existing {username} has a different role; left unchanged."))
            elif not account.check_password(password):
                self.stdout.write(self.style.WARNING(f"Existing {username} password preserved; use its existing password."))
        agent = User.objects.filter(username="agent", role=User.Role.AGENT).first()
        seller, _ = Customer.objects.get_or_create(
            full_name="Sok Dara", phone="012345678",
            defaults={"email": "dara@example.com", "address": "Phnom Penh", "customer_type": Customer.CustomerType.SELLER},
        )
        Customer.objects.get_or_create(
            full_name="Chan Sreyneang", phone="098765432",
            defaults={"email": "sreyneang@example.com", "address": "Siem Reap", "customer_type": Customer.CustomerType.BUYER},
        )
        owner = seller if seller.customer_type in (Customer.CustomerType.SELLER, Customer.CustomerType.LANDLORD) else None
        for name, kind, location, price, size, bedrooms, bathrooms in (
            ("Garden House", Property.PropertyType.HOUSE, "Phnom Penh", "120000.00", "150.50", 3, 2),
            ("Riverside Apartment", Property.PropertyType.APARTMENT, "Phnom Penh Riverside", "85000.00", "72.25", 2, 1),
            ("Siem Reap Land", Property.PropertyType.LAND, "Siem Reap", "60000.00", "500.00", 0, 0),
        ):
            Property.objects.get_or_create(name=name, location=location, defaults={
                "property_type": kind, "price": price, "size": size,
                "bedrooms": bedrooms, "bathrooms": bathrooms, "assigned_agent": agent, "owner": owner,
            })
        self.stdout.write(self.style.SUCCESS("Demo accounts, three properties and two customers are ready."))
