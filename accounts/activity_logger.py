"""
Utility to write a record to ActivityLog.
Import and call log_activity() from any view.
Uses transaction.on_commit so the write happens AFTER the current DB
transaction commits — this means it never interferes with @transaction.atomic
decorated views and never causes a rollback of the main operation.
"""
from django.db import transaction as _tx


def log_activity(user, action, model_name, object_id="", object_repr="", changes="", organization=None):
    """Schedule an ActivityLog entry to be written after the current transaction commits."""
    user_pk = user.pk if (user and getattr(user, "is_authenticated", False)) else None

    org_id = None
    if organization is not None:
        org_id = organization.pk if hasattr(organization, "pk") else organization
    elif user_pk:
        try:
            from saas.tenant import get_user_organization

            org = get_user_organization(user)
            org_id = org.pk if org else None
        except Exception:
            org_id = getattr(user, "organization_id", None)

    # Sanitise — strip non-ASCII to avoid any encoding edge-cases
    def _safe(s):
        return str(s).encode("utf-8", "replace").decode("utf-8")

    _action       = _safe(action)
    _model_name   = _safe(model_name)
    _object_id    = _safe(object_id)
    _object_repr  = _safe(object_repr)
    _changes      = _safe(changes)

    def _write():
        try:
            from .models import ActivityLog
            ActivityLog.objects.create(
                user_id=user_pk,
                organization_id=org_id,
                action=_action,
                model_name=_model_name,
                object_id=_object_id,
                object_repr=_object_repr,
                changes=_changes,
            )
        except Exception as exc:
            # Never let log failure break anything
            import logging
            logging.getLogger(__name__).warning("ActivityLog write failed: %s", exc)

    _tx.on_commit(_write)

