from decimal import Decimal

from django import forms

from saas.models import Organization, SubscriptionPlan


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "name",
            "description",
            "price_inr",
            "billing_period_days",
            "max_projects",
            "max_users",
            "max_bookings",
            "feature_leads",
            "feature_reports",
            "feature_agents",
            "feature_tally",
            "feature_api",
            "is_active",
            "sort_order",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "description": forms.Textarea(attrs={"class": "form-control form-control-sm", "rows": 3}),
            "price_inr": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "billing_period_days": forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
            "max_projects": forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
            "max_users": forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
            "max_bookings": forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
            "feature_leads": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "feature_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "feature_agents": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "feature_tally": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "feature_api": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_price_inr(self):
        value = self.cleaned_data["price_inr"]
        if value < Decimal("0"):
            raise forms.ValidationError("Price cannot be negative.")
        return value


class OrganizationStatusForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["status", "plan"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-control form-control-sm"}),
            "plan": forms.Select(attrs={"class": "form-control form-control-sm"}),
        }


class ExtendRenewalForm(forms.Form):
    extra_days = forms.IntegerField(
        min_value=1,
        max_value=3650,
        initial=30,
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "placeholder": "Days"}),
        label="Extend by (days)",
    )
