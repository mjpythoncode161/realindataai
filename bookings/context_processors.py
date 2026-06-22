def booking_agent_settings(request):
    from .models import get_booking_agent_settings

    settings_obj = get_booking_agent_settings()
    company_name = (settings_obj.company_name or "").strip() or "LANDLINK REAL ESTATE"
    return {
        "agent_settings": settings_obj,
        "company_name": company_name,
        "company_address": settings_obj.company_address or "",
        "company_phone": settings_obj.company_phone or "",
        "company_email": settings_obj.company_email or "",
        "system_name": company_name,
    }
