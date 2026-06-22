from __future__ import annotations

from django.utils import timezone
from django.db.models import Q

from .models import Customer, Lead, Users


def _normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def phone_has_project_booking(phone: str, project_id) -> bool:
    """Return True if an active booking exists for this phone on the project."""
    if not project_id:
        return False
    normalized = _normalize_phone(phone)
    if len(normalized) < 10:
        return False
    from bookings.models import BookingMaster

    return (
        BookingMaster.objects.filter(p_id_id=project_id)
        .exclude(status="CANCELLED")
        .filter(Q(phone__endswith=normalized) | Q(u_id__phone=normalized))
        .exists()
    )


def _unique_customer_email(lead: Lead) -> str:
    email = (lead.email or "").strip().lower()
    if email and not Users.objects.filter(email__iexact=email).exists():
        return email
    phone = _normalize_phone(lead.phone)
    base = f"customer{phone}@landlink.local"
    candidate = base
    counter = 1
    while Users.objects.filter(email__iexact=candidate).exists():
        candidate = f"customer{phone}{counter}@landlink.local"
        counter += 1
    return candidate


def convert_lead_to_customer(lead: Lead, actor, password: str | None = None) -> Customer:
    if lead.status == Lead.Status.CONFIRMED and lead.converted_customer_id:
        return lead.converted_customer

    phone = _normalize_phone(lead.phone)
    if len(phone) < 10:
        raise ValueError("Lead phone number must be at least 10 digits.")

    existing_user = Users.objects.filter(phone=phone).first()
    if existing_user:
        user = existing_user
        roles = user.get_roles()
        if "customer" not in roles:
            user.set_roles(roles + ["customer"])
            user.save(update_fields=["roles", "role"])
        customer, _ = Customer.objects.get_or_create(
            u_id=user,
            defaults={"aadhar_number": lead.aadhar_number or ""},
        )
    else:
        email = _unique_customer_email(lead)
        if not password:
            password = phone[-6:] if len(phone) >= 6 else "123456"
        user = Users.objects.create_user(
            username=email,
            email=email,
            full_name=lead.full_name,
            phone=phone,
            role="customer",
            password=password,
            created_by=actor,
        )
        user.set_roles(["customer"])
        user.save(update_fields=["roles", "role"])
        customer = Customer.objects.create(
            u_id=user,
            aadhar_number=lead.aadhar_number or "",
            occupation=lead.occupation or "",
            present_address=lead.present_address or "",
        )

    if lead.aadhar_number and not customer.aadhar_number:
        customer.aadhar_number = lead.aadhar_number
    if lead.occupation and not customer.occupation:
        customer.occupation = lead.occupation
    if lead.present_address and not customer.present_address:
        customer.present_address = lead.present_address
    customer.save()

    lead.status = Lead.Status.CONFIRMED
    lead.confirmed_at = timezone.now()
    lead.converted_customer = customer
    lead.save(update_fields=["status", "confirmed_at", "converted_customer", "updated_at"])
    return customer
