from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        AGENT = 'agent', 'Support agent'
        ADMIN = 'admin', 'Administrator'

    email = models.EmailField('email address', unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(max_length=20, blank=True)
    address_line = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=12, blank=True)

    @property
    def is_agent(self):
        return self.role == self.Role.AGENT

    @property
    def is_store_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_staff_member(self):
        """Agents and administrators can use the back-office dashboard."""
        return self.is_agent or self.is_store_admin

    def save(self, *args, **kwargs):
        # Store administrators also manage the catalog through the Django admin,
        # so Django-admin access follows the role (superusers always keep it).
        self.is_staff = self.role == self.Role.ADMIN or self.is_superuser
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username
