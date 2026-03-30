"""Sync public EmailTenantMembership when tenant users change."""

from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from users.models import User


@receiver(post_save, sender=User)
def sync_email_membership_on_user_save(sender, instance, **kwargs):
    if not getattr(settings, "USE_MULTITENANT", False):
        return
    from tenants.email_index import sync_user_membership

    sync_user_membership(instance)


@receiver(post_delete, sender=User)
def remove_email_membership_on_user_delete(sender, instance, **kwargs):
    if not getattr(settings, "USE_MULTITENANT", False):
        return
    from tenants.email_index import remove_user_membership

    remove_user_membership(instance)
