"""WhatsApp and email share helpers for bookings and receipts."""
from __future__ import annotations

import re
from urllib.parse import quote

from django.conf import settings


def normalize_whatsapp_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "91" + digits[1:]
    return digits


def whatsapp_share_url(phone: str, message: str) -> str:
    num = normalize_whatsapp_phone(phone)
    if not num or not message:
        return ""
    return f"https://wa.me/{num}?text={quote(message)}"


def mailto_share_url(email: str, subject: str, body: str) -> str:
    if not email:
        return ""
    return f"mailto:{quote(email)}?subject={quote(subject)}&body={quote(body)}"


def email_is_configured() -> bool:
    return bool(getattr(settings, "EMAIL_BACKEND", ""))


def _format_amount(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def booking_share_text(booking, company_name: str, client_copy_url: str = "") -> tuple[str, str]:
    project = booking.p_id.name if booking.p_id else "-"
    plots = ", ".join(
        it.plot_number for it in booking.items.all() if it.plot_number
    ) or "-"
    subject = f"Booking {booking.booking_no} — {company_name}"
    lines = [
        f"Hello {booking.customer_full_name},",
        "",
        f"Your booking details from {company_name}:",
        "",
        f"Booking No: {booking.booking_no}",
        f"Date: {booking.booking_date.strftime('%d-%m-%Y') if booking.booking_date else '-'}",
        f"Project: {project}",
        f"Plot/Flat: {plots}",
    ]
    balance = getattr(booking, "balance", None)
    if balance:
        lines.extend(
            [
                f"Total Amount: Rs.{_format_amount(balance.total_amount)}",
                f"Paid: Rs.{_format_amount(balance.paid_amount)}",
                f"Balance: Rs.{_format_amount(balance.balance_amount)}",
            ]
        )
    if client_copy_url:
        lines.extend(["", f"View booking copy: {client_copy_url}"])
    lines.extend(["", "Thank you,", company_name])
    return subject, "\n".join(lines)


def receipt_share_text(receipt, company_name: str) -> tuple[str, str]:
    booking_no = receipt.b_id.booking_no if receipt.b_id else "-"
    subject = f"Receipt {receipt.receipt_no} — {company_name}"
    lines = [
        f"Hello {receipt.customer_name},",
        "",
        f"Payment receipt from {company_name}:",
        "",
        f"Receipt No: {receipt.receipt_no}",
        f"Receipt Date: {receipt.receipt_date.strftime('%d-%m-%Y') if receipt.receipt_date else '-'}",
        f"Booking No: {booking_no}",
        f"Plot/Flat: {receipt.plot_number or '-'}",
        f"Amount Paid: Rs.{_format_amount(receipt.pay_amount)}",
        f"Balance Due: Rs.{_format_amount(receipt.balance_amount)}",
        f"Payment Mode: {receipt.get_payment_method_display()}",
        "",
        "Thank you,",
        company_name,
    ]
    return subject, "\n".join(lines)


def build_booking_share(request, booking, company_name: str):
    from django.urls import reverse

    client_copy_url = request.build_absolute_uri(
        reverse("booking_client_copy", kwargs={"b_id": booking.b_id})
    )
    subject, body = booking_share_text(booking, company_name, client_copy_url)
    phone = booking.customer_phone
    email = booking.customer_email
    return {
        "whatsapp_url": whatsapp_share_url(phone, body),
        "mailto_url": mailto_share_url(email, subject, body),
        "customer_phone": phone or "",
        "customer_email": email or "",
        "email_subject": subject,
        "email_body": body,
        "can_send_email": email_is_configured() and bool(email),
    }


def build_receipt_share(receipt, company_name: str):
    subject, body = receipt_share_text(receipt, company_name)
    phone = receipt.phone
    email = ""
    if receipt.b_id:
        email = receipt.b_id.customer_email or ""
    return {
        "whatsapp_url": whatsapp_share_url(phone, body),
        "mailto_url": mailto_share_url(email, subject, body),
        "customer_phone": phone or "",
        "customer_email": email or "",
        "email_subject": subject,
        "email_body": body,
        "can_send_email": email_is_configured() and bool(email),
    }


def send_customer_email(to_email: str, subject: str, body: str) -> None:
    from django.core.mail import send_mail

    from .models import get_booking_agent_settings

    if not to_email:
        raise ValueError("Customer email address is missing.")
    if not email_is_configured():
        raise ValueError(
            "Server email is not configured. Use the Email button to open your mail app."
        )
    store = get_booking_agent_settings()
    sender = settings.DEFAULT_FROM_EMAIL or store.company_email
    if not sender:
        raise ValueError("No sender email configured in settings.")
    send_mail(subject, body, sender, [to_email], fail_silently=False)
