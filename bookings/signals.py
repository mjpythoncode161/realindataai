from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import BalanceMaster, BookingItem, BookingMaster


def _recalculate_balance(booking_id: int) -> None:
    booking = BookingMaster.objects.filter(pk=booking_id).first()
    if not booking:
        return

    balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
    balance.recalculate()
    balance.save()


@receiver(post_save, sender=BookingItem)
def booking_item_saved(sender, instance: BookingItem, **kwargs):
    if not instance.b_id_id:
        return
    transaction.on_commit(lambda: _recalculate_balance(instance.b_id_id))


@receiver(post_delete, sender=BookingItem)
def booking_item_deleted(sender, instance: BookingItem, **kwargs):
    if not instance.b_id_id:
        return
    transaction.on_commit(lambda: _recalculate_balance(instance.b_id_id))
