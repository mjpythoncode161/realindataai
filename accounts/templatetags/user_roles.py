import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def highlight_changes(value):
    """
    Wraps 'old -> new' patterns in colored spans:
    old value = red strikethrough, new value = green bold.
    """
    if not value:
        return value
    text = escape(str(value))

    def replace_arrow(m):
        old = m.group(1).strip()
        new = m.group(2).strip()
        return (
            f'<span style="color:#c0392b;text-decoration:line-through;">{old}</span>'
            f' <span style="color:#999;font-size:0.8em;">&#8594;</span> '
            f'<span style="color:#27ae60;font-weight:600;">{new}</span>'
        )

    result = re.sub(r'([^\|]+?)\s*-&gt;\s*([^\|<]+)', replace_arrow, text)
    return mark_safe(result)


@register.filter
def has_role(user, role_name):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.has_role(role_name)


@register.filter
def has_any_role(user, roles_csv):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role_names = [part.strip() for part in (roles_csv or "").split(",") if part.strip()]
    return user.has_any_role(*role_names)


@register.filter
def can_manage_bookings(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.can_manage_bookings()


@register.filter
def is_lead_only_staff(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_lead_only_staff()


@register.filter
def is_manager_only_staff(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_manager_only_staff()


@register.filter
def is_accounts_only_staff(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_accounts_only_staff()
