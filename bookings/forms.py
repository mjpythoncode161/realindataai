from __future__ import annotations

from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from .models import (
    AccountsDebitPayment,
    AgentMaster,
    BookingAgentSettings,
    BookingItem,
    BookingMaster,
    Project,
    ReceiptMaster,
    Payment,
    get_booking_agent_settings,
)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "num_plots", "location"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Project Name"}),
            "num_plots": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Enter No. of plots"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Location"}),
        }


class BookingAgentSettingsForm(forms.ModelForm):
    class Meta:
        model = BookingAgentSettings
        fields = [
            "company_name",
            "company_address",
            "company_phone",
            "company_email",
            "enable_manager",
            "enable_executive",
            "enable_telecaller",
        ]
        labels = {
            "company_name": "Company / Firm Name",
            "company_address": "Company Address",
            "company_phone": "Phone",
            "company_email": "Email",
            "enable_manager": "Manager",
            "enable_executive": "Executive",
            "enable_telecaller": "Telecaller",
        }
        widgets = {
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. LANDLINK REAL ESTATE"}
            ),
            "company_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Office address shown on forms, ledgers, and client copies",
                }
            ),
            "company_phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Contact phone (optional)"}
            ),
            "company_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "Contact email (optional)"}
            ),
            "enable_manager": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
            "enable_executive": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
            "enable_telecaller": forms.CheckboxInput(attrs={"class": "custom-control-input"}),
        }

    def clean(self):
        cleaned = super().clean()
        if not any(
            cleaned.get(field)
            for field in ("enable_manager", "enable_executive", "enable_telecaller")
        ):
            raise forms.ValidationError("Enable at least one role for bookings and reports.")
        return cleaned


AGENT_FIELD_GROUPS = {
    "manager": [
        "manager_u_id",
        "manager_percentage",
        "manager_tds",
        "manager_security_amount",
    ],
    "executive": [
        "executive_u_id",
        "executive_percentage",
        "executive_tds",
        "executive_security_amount",
    ],
    "telecaller": [
        "telecaller_u_id",
        "telecaller_percentage",
        "telecaller_tds",
        "telecaller_security_amount",
    ],
}


class AgentMasterForm(forms.ModelForm):
    class Meta:
        model = AgentMaster
        fields = ["u_id", "commission_percentage", "tds_amount", "security_amount", "effective_date", "payment_method", "remarks"]
        widgets = {
            "u_id": forms.Select(attrs={"class": "form-control"}),
            "commission_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001", "min": "0", "placeholder": "e.g. 0.5268 or 0.25"}),
            "tds_amount": forms.NumberInput(attrs={"class": "form-control"}),
            "security_amount": forms.NumberInput(attrs={"class": "form-control"}),
            "effective_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Enter remarks (optional)"}),
        }

    def __init__(self, *args, **kwargs):
        role = kwargs.pop("role", None)
        super().__init__(*args, **kwargs)
        if role:
            from accounts.models import Users
            if role == "accounts":
                # Accounts entries are for manager/executive/telecaller agents
                self.fields["u_id"].queryset = Users.objects.filter(
                    role__in=["manager", "executive", "telecaller"]
                ).order_by("full_name")
                self.fields["u_id"].label = "Select User (Manager / Executive / Telecaller)"
                self.fields["u_id"].empty_label = "— Select user —"
                self.fields["effective_date"].label = "Accounts Date"
                self.fields["effective_date"].required = True
                self.fields.pop("tds_amount", None)
                self.fields.pop("commission_percentage", None)
                self.fields.pop("security_amount", None)
                self.fields.pop("payment_method", None)
                self.fields.pop("remarks", None)
            else:
                self.fields["u_id"].queryset = Users.objects.filter(role=role)
                self.fields.pop("payment_method", None)
                self.fields.pop("effective_date", None)


class AccountsDebitPaymentForm(forms.ModelForm):
    payment_date = forms.DateField(
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    class Meta:
        model = AccountsDebitPayment
        fields = ["debit_type", "amount", "payment_date", "payment_method", "remarks"]
        widgets = {
            "debit_type": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Note",
                    "maxlength": "255",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["debit_type"].label = "Type"
        self.fields["amount"].label = "Amount"
        self.fields["payment_date"].label = "Date"
        self.fields["payment_method"].label = "Mode"
        self.fields["remarks"].label = "Note"
        self.fields["debit_type"].choices = [
            (AccountsDebitPayment.DebitType.COMMISSION, "Commission"),
            (AccountsDebitPayment.DebitType.SECURITY, "Security"),
        ]
        self.empty_permitted = True

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount") or Decimal("0")
        if amount <= 0:
            return cleaned
        if not cleaned.get("payment_date"):
            self.add_error("payment_date", "Date is required when amount is entered.")
        return cleaned


class BaseAccountsDebitPaymentFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for form in self.forms:
            form.empty_permitted = True

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            amount = form.cleaned_data.get("amount") or Decimal("0")
            if amount > 0:
                active += 1
        if active == 0 and (not self.instance or not self.instance.pk):
            raise forms.ValidationError("Add at least one payment entry.")


AccountsDebitPaymentFormSet = inlineformset_factory(
    AgentMaster,
    AccountsDebitPayment,
    form=AccountsDebitPaymentForm,
    formset=BaseAccountsDebitPaymentFormSet,
    extra=1,
    can_delete=True,
)

ACCOUNTS_PAYMENT_FORMSET_PREFIX = "payments"


class BookingMasterForm(forms.ModelForm):
    booking_date = forms.DateField(
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
    )
    date_of_birth = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
    )
    next_payment_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
    )

    class Meta:
        model = BookingMaster
        fields = [
            "booking_date",
            "phone",
            "full_name",
            "email",
            "date_of_birth",
            "occupation",
            "present_address",
            "permanent_address",
            "aadhar_number",
            "pin_code",
            "manager_u_id",
            "manager_percentage",
            "manager_tds",
            "manager_security_amount",
            "executive_u_id",
            "executive_percentage",
            "executive_tds",
            "executive_security_amount",
            "telecaller_u_id",
            "telecaller_percentage",
            "telecaller_tds",
            "telecaller_security_amount",
            "payment_method",
            "payment_status",
            "payment_details",
            "nominee",
            "relationship",
            "p_id",
            "location",
            "next_payment_date",
        ]
        widgets = {
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Enter phone number", "maxlength": "15"}
            ),
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Full Name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Enter Mail ID"}),
            "occupation": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Occupation"}),
            "present_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Present Address"}),
            "permanent_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Permanent Address"}),
            "aadhar_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Aadhaar Number"}),
            "pin_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Pin Code"}),
            "manager_u_id": forms.Select(attrs={"class": "form-control"}),
            "manager_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001", "min": "0"}),
            "manager_tds": forms.HiddenInput(),
            "manager_security_amount": forms.HiddenInput(),
            "executive_u_id": forms.Select(attrs={"class": "form-control"}),
            "executive_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "executive_tds": forms.HiddenInput(),
            "executive_security_amount": forms.HiddenInput(),
            "telecaller_u_id": forms.Select(attrs={"class": "form-control"}),
            "telecaller_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.0001", "min": "0"}),
            "telecaller_tds": forms.HiddenInput(),
            "telecaller_security_amount": forms.HiddenInput(),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "payment_status": forms.Select(attrs={"class": "form-control"}),
            "payment_details": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Payment Details"}),
            "nominee": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Nominee"}),
            "relationship": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Relationship"}),
            "p_id": forms.Select(attrs={"class": "form-control"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Location"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        optional_customer_fields = [
            "full_name",
            "email",
            "date_of_birth",
            "occupation",
            "present_address",
            "permanent_address",
            "aadhar_number",
            "pin_code",
            "nominee",
            "relationship",
        ]
        for field_name in optional_customer_fields:
            if field_name in self.fields:
                self.fields[field_name].required = False
        if "phone" in self.fields:
            self.fields["phone"].widget.attrs.update(
                {
                    "id": "id_phone",
                    "autocomplete": "tel",
                    "placeholder": "Enter 10-digit mobile number",
                }
            )
        from accounts.models import Users, users_with_role_query
        manager_ids = AgentMaster.objects.filter(role="manager").values_list("u_id_id", flat=True)
        executive_ids = AgentMaster.objects.filter(role="executive").values_list("u_id_id", flat=True)
        telecaller_ids = AgentMaster.objects.filter(role="telecaller").values_list("u_id_id", flat=True)

        self.fields["manager_u_id"].queryset = Users.objects.filter(
            u_id__in=manager_ids
        ).filter(users_with_role_query("manager")).order_by("full_name")
        self.fields["executive_u_id"].queryset = Users.objects.filter(
            u_id__in=executive_ids
        ).filter(users_with_role_query("executive")).order_by("full_name")
        self.fields["telecaller_u_id"].queryset = Users.objects.filter(
            u_id__in=telecaller_ids
        ).filter(users_with_role_query("telecaller")).order_by("full_name")

        self.fields["manager_u_id"].empty_label = "Select Manager"
        self.fields["executive_u_id"].empty_label = "Select Executive"
        self.fields["telecaller_u_id"].empty_label = "Select Telecaller"

        agent_settings = get_booking_agent_settings()
        self.agent_settings = agent_settings
        for role, field_names in AGENT_FIELD_GROUPS.items():
            enabled = agent_settings.is_role_enabled(role)
            for field_name in field_names:
                if field_name not in self.fields:
                    continue
                self.fields[field_name].required = enabled and field_name.endswith("_u_id")
                if not enabled:
                    self.fields[field_name].required = False
                    if field_name.endswith("_u_id"):
                        self.fields[field_name].widget = forms.HiddenInput()
                    elif field_name.endswith("_percentage"):
                        self.fields[field_name].widget = forms.HiddenInput()
                        self.fields[field_name].initial = Decimal("0.00")

        self.fields["p_id"].required = True
        self.fields["p_id"].label = "Project"
        self.fields["p_id"].queryset = Project.objects.all().order_by("name")
        self.fields["p_id"].empty_label = "Select Project"
        self.fields["p_id"].widget.attrs.update({"id": "id_p_id", "class": "form-control"})
        self.fields["location"].widget = forms.HiddenInput()

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone.isdigit() or len(phone) < 10:
            raise forms.ValidationError("Enter a valid phone number.")
        return phone

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get("full_name") or "").strip():
            phone = cleaned.get("phone") or ""
            cleaned["full_name"] = f"Customer {phone[-4:]}" if len(phone) >= 4 else "Customer"
        project = cleaned.get("p_id")
        if project:
            cleaned["location"] = project.location or ""

        agent_settings = get_booking_agent_settings()
        zero = Decimal("0.00")
        for role, field_names in AGENT_FIELD_GROUPS.items():
            if agent_settings.is_role_enabled(role):
                continue
            for field_name in field_names:
                if field_name.endswith("_u_id"):
                    cleaned[field_name] = None
                elif field_name.endswith("_percentage"):
                    cleaned[field_name] = zero
                else:
                    cleaned[field_name] = zero
        return cleaned


class BookingItemForm(forms.ModelForm):
    class Meta:
        model = BookingItem
        fields = [
            "plot_number",
            "plot_name",
            "area_sqft",
            "rate",
            "booking_amount",
        ]
        widgets = {
            "plot_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Flat/Plot"}),
            "plot_name": forms.HiddenInput(),
            "area_sqft": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter Area"}),
            "rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter Rate"}),
            "booking_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter BookingMaster Amount"}),
        }

    def __init__(self, *args, master_project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.master_project = master_project
        self.fields["plot_number"].required = True
        self.fields["area_sqft"].required = True
        self.fields["rate"].required = True
        self.fields["booking_amount"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned

        p_id = self.master_project
        plot_number = (cleaned.get("plot_number") or "").strip()
        area = cleaned.get("area_sqft")
        rate = cleaned.get("rate")

        if not p_id and not plot_number and not area and not rate:
            return cleaned

        if not p_id:
            self.add_error(None, "Select Project in Property Details.")
        if not plot_number:
            self.add_error("plot_number", "Plot number is required.")
        if area is None or area <= 0:
            self.add_error("area_sqft", "Area is required.")
        if rate is None or rate <= 0:
            self.add_error("rate", "Rate is required.")

        if p_id and plot_number:
            plots_to_check = [p.strip() for p in plot_number.split(",") if p.strip()]
            
            # Get all booked plots for this project, excluding current booking if editing, and excluding closed cancellations
            booked_items = BookingItem.objects.filter(p_id=p_id).exclude(
                b_id__status="CANCELLED",
                b_id__cancelled_details__closure_status="CLOSED",
                b_id__cancelled_details__released_for_rebooking=True
            )
            if self.instance.pk:
                booked_items = booked_items.exclude(pk=self.instance.pk)
            
            booked_plots_set = set()
            for item in booked_items:
                if item.plot_number:
                    for p in item.plot_number.split(","):
                        booked_plots_set.add(p.strip())
            
            already_booked = [p for p in plots_to_check if p in booked_plots_set]
            
            if already_booked:
                self.add_error("plot_number", f"Already booked: {', '.join(already_booked)}")

        area = cleaned.get("area_sqft") or Decimal("0.00")
        rate = cleaned.get("rate") or Decimal("0.00")
        cleaned["_calculated_total"] = area * rate
        return cleaned


class ReceiptMasterForm(forms.ModelForm):
    receipt_date = forms.DateField(
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    next_payment_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    class Meta:
        model = ReceiptMaster
        fields = [
            "receipt_date",
            "b_id",
            "customer_name",
            "phone",
            "plot_number",
            "total_amount",
            "pay_amount",
            "balance_amount",
            "payment_method",
            "payment_details",
            "next_payment_date",
        ]
        widgets = {
            "b_id": forms.Select(attrs={"class": "form-control", "id": "id_b_id"}),
            "customer_name": forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Phone No"}),
            "plot_number": forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}),
            "total_amount": forms.NumberInput(attrs={"class": "form-control", "readonly": "readonly"}),
            "balance_amount": forms.NumberInput(attrs={"class": "form-control", "readonly": "readonly"}),
            "pay_amount": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Enter Pay Amount"}),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "payment_details": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Payment Details"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["b_id"].queryset = BookingMaster.objects.exclude(status="CANCELLED").order_by("-b_id")

    def clean(self):
        cleaned_data = super().clean()
        pay_amount = cleaned_data.get("pay_amount")
        booking = cleaned_data.get("b_id")

        if booking and pay_amount is not None:
            from .models import BalanceMaster
            balance_obj = BalanceMaster.objects.filter(b_id=booking).first()
            if balance_obj:
                current_balance = balance_obj.balance_amount
                # For edits, we need the balance as it would be WITHOUT this receipt
                if self.instance and self.instance.pk:
                    current_balance += self.instance.pay_amount
                
                if pay_amount > current_balance:
                    self.add_error("pay_amount", "Payment exceeds remaining balance")
                elif current_balance <= 0 and pay_amount > 0:
                    self.add_error("pay_amount", "Payment exceeds remaining balance")
        
        return cleaned_data


class BaseBookingItemFormSet(forms.BaseInlineFormSet):
    def get_master_project(self):
        if self.data:
            raw = self.data.get("p_id")
            if raw:
                return Project.objects.filter(pk=raw).first()
        if getattr(self.instance, "pk", None) and self.instance.p_id_id:
            return self.instance.p_id
        return None

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["master_project"] = self.get_master_project()
        return kwargs

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        master_project = self.get_master_project()
        if not master_project:
            raise forms.ValidationError("Select Project in Property Details.")
        active_rows = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            plot_number = (form.cleaned_data.get("plot_number") or "").strip()
            area = form.cleaned_data.get("area_sqft")
            rate = form.cleaned_data.get("rate")
            if plot_number and area and area > 0 and rate and rate > 0:
                active_rows += 1
        if active_rows < 1:
            raise forms.ValidationError(
                "Add at least one property row with Plot No, Area, and Rate."
            )

    def save(self, commit=True):
        master_project = self.get_master_project()
        instances = super().save(commit=False)
        for obj in instances:
            if master_project:
                obj.p_id = master_project
            if commit:
                obj.save()
        if commit:
            self.save_m2m()
            for obj in self.deleted_objects:
                obj.delete()
        return instances


BookingItemFormSet = inlineformset_factory(
    BookingMaster,
    BookingItem,
    form=BookingItemForm,
    formset=BaseBookingItemFormSet,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class BookingMasterKGPForm(forms.ModelForm):
    """Post-KGP: project selection (Store Settings projects)."""

    class Meta:
        model = BookingMaster
        fields = ["p_id", "location"]
        widgets = {
            "p_id": forms.Select(attrs={"class": "form-control", "id": "id_p_id"}),
            "location": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["p_id"].label = "Project"
        self.fields["p_id"].queryset = Project.objects.all().order_by("name")
        self.fields["p_id"].required = True
        self.fields["p_id"].empty_label = "Select Project"

    def clean(self):
        cleaned = super().clean()
        project = cleaned.get("p_id")
        if project:
            cleaned["location"] = project.location or ""
        return cleaned


class BookingItemKGPForm(forms.ModelForm):
    """Post-KGP edit: full property row like booking form."""

    class Meta:
        model = BookingItem
        fields = ["plot_number", "area_sqft", "rate", "booking_amount"]
        widgets = {
            "plot_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Enter Flat/Plot"}
            ),
            "area_sqft": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter Area"}
            ),
            "rate": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter Rate"}
            ),
            "booking_amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "placeholder": "Enter BookingMaster Amount",
                }
            ),
        }

    def __init__(self, *args, master_project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.master_project = master_project
        self.fields["plot_number"].required = True
        self.fields["area_sqft"].required = True
        self.fields["rate"].required = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned

        p_id = self.master_project
        plot_number = (cleaned.get("plot_number") or "").strip()
        area = cleaned.get("area_sqft")
        rate = cleaned.get("rate")

        if not plot_number:
            self.add_error("plot_number", "Plot number is required.")
        if area is None or area <= 0:
            self.add_error("area_sqft", "Area is required.")
        if rate is None or rate <= 0:
            self.add_error("rate", "Rate is required.")

        if p_id and plot_number:
            plots_to_check = [p.strip() for p in plot_number.split(",") if p.strip()]
            booked_items = BookingItem.objects.filter(p_id=p_id).exclude(
                b_id__status="CANCELLED",
                b_id__cancelled_details__closure_status="CLOSED",
                b_id__cancelled_details__released_for_rebooking=True,
            )
            if self.instance.pk:
                booked_items = booked_items.exclude(pk=self.instance.pk)

            booked_plots_set = set()
            for item in booked_items:
                if item.plot_number:
                    for p in item.plot_number.split(","):
                        booked_plots_set.add(p.strip())

            already_booked = [p for p in plots_to_check if p in booked_plots_set]
            if already_booked:
                self.add_error("plot_number", f"Already booked: {', '.join(already_booked)}")

        area_val = cleaned.get("area_sqft") or Decimal("0.00")
        rate_val = cleaned.get("rate") or Decimal("0.00")
        cleaned["_calculated_total"] = area_val * rate_val
        return cleaned


class BaseBookingItemKGPFormSet(forms.BaseInlineFormSet):
    def get_master_project(self):
        if self.data:
            raw = self.data.get("p_id")
            if raw:
                return Project.objects.filter(pk=raw).first()
        if getattr(self.instance, "pk", None) and self.instance.p_id_id:
            return self.instance.p_id
        return None

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["master_project"] = self.get_master_project()
        return kwargs

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_rows = 0
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            plot_number = (form.cleaned_data.get("plot_number") or "").strip()
            area = form.cleaned_data.get("area_sqft")
            rate = form.cleaned_data.get("rate")
            if plot_number and area and area > 0 and rate and rate > 0:
                active_rows += 1
        if active_rows < 1:
            raise forms.ValidationError(
                "Add at least one property row with Plot No, Area, and Rate."
            )

    def save(self, commit=True):
        master_project = self.get_master_project()
        instances = super().save(commit=False)
        for obj in instances:
            if master_project:
                obj.p_id = master_project
            obj.total_amount = (obj.area_sqft or Decimal("0.00")) * (obj.rate or Decimal("0.00"))
            if commit:
                obj.save()
        if commit:
            self.save_m2m()
        return instances


BookingItemKGPFormSet = inlineformset_factory(
    BookingMaster,
    BookingItem,
    form=BookingItemKGPForm,
    formset=BaseBookingItemKGPFormSet,
    extra=0,
    can_delete=False,
    min_num=1,
    validate_min=True,
)


class BookingPlotSwapForm(forms.Form):
    swap_with_booking = forms.ModelChoiceField(
        queryset=BookingMaster.objects.none(),
        label="Swap with booking",
        widget=forms.Select(attrs={"class": "form-control"}),
        empty_label="— Select booking to swap with —",
    )

    def __init__(self, booking: BookingMaster, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking
        plots_label = (
            BookingMaster.objects.filter(
                p_id=booking.p_id,
                kgp_completed=True,
                status=BookingMaster.BookingStatus.ACTIVE,
            )
            .exclude(pk=booking.pk)
            .prefetch_related("items")
            .order_by("-b_id")
        )
        self.fields["swap_with_booking"].queryset = plots_label

        def swap_label(obj: BookingMaster) -> str:
            item = obj.items.first()
            plot_no = item.plot_number if item and item.plot_number else "-"
            return f"{obj.booking_no} — {obj.customer_full_name} — Plot {plot_no}"

        self.fields["swap_with_booking"].label_from_instance = swap_label

    def clean_swap_with_booking(self):
        target = self.cleaned_data.get("swap_with_booking")
        if not target:
            raise forms.ValidationError("Select a booking to swap with.")
        if target.pk == self.booking.pk:
            raise forms.ValidationError("Cannot swap with the same booking.")
        if target.p_id_id != self.booking.p_id_id:
            raise forms.ValidationError("Swap is allowed only within the same project.")
        if not target.kgp_completed:
            raise forms.ValidationError("The other booking must also have KGP marked complete.")
        return target

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get("swap_with_booking")
        if not target:
            return cleaned

        source_item = BookingItem.objects.filter(b_id=self.booking).first()
        target_item = BookingItem.objects.filter(b_id=target).first()

        if not source_item or not target_item:
            raise forms.ValidationError("Both bookings must have a property row to swap.")
        if BookingItem.objects.filter(b_id=self.booking).count() != 1:
            raise forms.ValidationError(
                "Plot swap is supported only when this booking has a single property row."
            )
        if BookingItem.objects.filter(b_id=target).count() != 1:
            raise forms.ValidationError(
                "Plot swap is supported only when the other booking has a single property row."
            )

        cleaned["source_item"] = source_item
        cleaned["target_item"] = target_item
        return cleaned


class PaymentForm(forms.ModelForm):
    payment_date = forms.DateField(
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    next_payment_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    
    # UI Helper fields
    phone = forms.CharField(max_length=15, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Phone No"}))
    customer_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "readonly": "readonly"}))
    total_amount = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "readonly": "readonly"}))
    balance_amount = forms.DecimalField(required=False, widget=forms.NumberInput(attrs={"class": "form-control", "readonly": "readonly"}))

    class Meta:
        model = Payment
        fields = [
            "payment_date",
            "b_id",
            "pay_amount",
            "payment_method",
            "payment_details",
            "next_payment_date",
        ]
        widgets = {
            "b_id": forms.Select(attrs={"class": "form-control", "id": "id_b_id"}),
            "pay_amount": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Enter Pay Amount", "id": "id_pay_amount"}),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "payment_details": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter Payment Details"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["b_id"].queryset = BookingMaster.objects.exclude(status="CANCELLED").order_by("-b_id")

    def clean(self):
        cleaned_data = super().clean()
        pay_amount = cleaned_data.get("pay_amount")
        booking = cleaned_data.get("b_id")

        if booking and pay_amount is not None:
            from .models import BalanceMaster
            balance_obj = BalanceMaster.objects.filter(b_id=booking).first()
            if balance_obj:
                current_balance = balance_obj.balance_amount
                if pay_amount > current_balance:
                    self.add_error("pay_amount", "Payment exceeds remaining balance")
                elif current_balance <= 0 and pay_amount > 0:
                    self.add_error("pay_amount", "Payment exceeds remaining balance")
        
        return cleaned_data
