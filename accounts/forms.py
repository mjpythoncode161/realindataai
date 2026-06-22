from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Lead, LeadActivity


class ProfileUpdateForm(forms.Form):
    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name"}),
    )
    phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "10-digit mobile"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email address"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if not self.is_bound:
            self.fields["full_name"].initial = user.full_name
            self.fields["phone"].initial = user.phone
            self.fields["email"].initial = user.email

    def clean_phone(self):
        phone = "".join(ch for ch in (self.cleaned_data.get("phone") or "") if ch.isdigit())
        if len(phone) < 10:
            raise ValidationError("Enter a valid 10-digit phone number.")
        return phone[-10:]

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        from .models import Users

        if Users.objects.exclude(u_id=self.user.u_id).filter(email__iexact=email).exists():
            raise ValidationError("This email is already used by another account.")
        return email


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Current password", "autocomplete": "current-password"}
        ),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "New password", "autocomplete": "new-password"}
        ),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Confirm new password", "autocomplete": "new-password"}
        ),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        current = cleaned.get("current_password")
        new_pass = cleaned.get("new_password")
        confirm = cleaned.get("confirm_password")

        if not self.user.check_password(current):
            self.add_error("current_password", "Current password is incorrect.")

        if new_pass != confirm:
            self.add_error("confirm_password", "Passwords do not match.")

        if new_pass and len(new_pass) < 6:
            self.add_error("new_password", "Password must be at least 6 characters.")

        if new_pass:
            try:
                validate_password(new_pass, self.user)
            except ValidationError as exc:
                for message in exc.messages:
                    self.add_error("new_password", message)

        return cleaned


class CustomerRegistrationForm(forms.Form):
    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone = forms.CharField(max_length=15)
    password = forms.CharField(widget=forms.PasswordInput)
    aadhar_number = forms.CharField(max_length=20)


class LandLinkSignupForm(forms.Form):
    company_name = forms.CharField(
        max_length=200,
        label="Company / agency name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your company name"}),
    )
    full_name = forms.CharField(
        max_length=150,
        label="Your full name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Work email"}),
    )
    phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "10-digit mobile"}),
    )
    password = forms.CharField(
        min_length=6,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Password (min 6 characters)"}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"}),
    )

    def clean_phone(self):
        phone = "".join(ch for ch in (self.cleaned_data.get("phone") or "") if ch.isdigit())
        if len(phone) < 10:
            raise ValidationError("Enter a valid 10-digit phone number.")
        return phone[-10:]

    def clean_email(self):
        from .models import Users

        email = (self.cleaned_data.get("email") or "").strip().lower()
        if Users.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists. Please sign in.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        phone = cleaned.get("phone")
        if phone:
            from .models import Users

            if Users.objects.filter(phone=phone).exists():
                self.add_error("phone", "This phone number is already registered.")
        return cleaned


class ContactForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email address"}),
    )
    phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone (optional)"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "placeholder": "How can we help?", "rows": 4}),
    )


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            "full_name",
            "phone",
            "email",
            "p_id",
            "plot_interest",
            "budget",
            "source",
            "occupation",
            "present_address",
            "aadhar_number",
            "notes",
            "status",
            "next_follow_up_date",
            "assigned_to",
        ]
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "10-digit mobile"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email (optional)"}),
            "p_id": forms.Select(attrs={"class": "form-control"}),
            "plot_interest": forms.TextInput(attrs={"class": "form-control", "placeholder": "Plot / flat interest"}),
            "budget": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Budget"}),
            "source": forms.Select(attrs={"class": "form-control"}),
            "occupation": forms.TextInput(attrs={"class": "form-control", "placeholder": "Occupation"}),
            "present_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Address"}),
            "aadhar_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Aadhaar (optional)"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Initial notes"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "next_follow_up_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "assigned_to": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from bookings.models import Project
        from .models import Users, users_with_any_role_query

        self.fields["p_id"].queryset = Project.objects.all().order_by("name")
        self.fields["p_id"].empty_label = "Select Project"
        if user and user.has_role("manager") and not user.has_role("admin"):
            assignable = Users.objects.filter(
                users_with_any_role_query("executive", "telecaller")
            ).distinct()
        elif user and user.has_any_role("executive", "telecaller") and not user.has_any_role(
            "admin", "manager", "followup"
        ):
            assignable = Users.objects.filter(pk=user.pk)
        else:
            assignable = Users.objects.filter(
                users_with_any_role_query("followup", "manager", "executive", "telecaller")
            ).distinct()
        self.fields["assigned_to"].queryset = assignable.order_by("full_name")
        self.fields["assigned_to"].empty_label = "Select executive or telecaller"
        self.fields["assigned_to"].required = True
        self.fields["email"].required = False
        self.fields["aadhar_number"].required = False
        self.fields["budget"].required = False
        self.fields["next_follow_up_date"].required = False

    def clean_phone(self):
        phone = "".join(ch for ch in (self.cleaned_data.get("phone") or "") if ch.isdigit())
        if len(phone) < 10:
            raise ValidationError("Enter a valid 10-digit phone number.")
        return phone[-10:]

    def clean_aadhar_number(self):
        aadhar = (self.cleaned_data.get("aadhar_number") or "").strip()
        if aadhar and (not aadhar.isdigit() or len(aadhar) != 12):
            raise ValidationError("Aadhaar must be exactly 12 digits.")
        return aadhar


class LeadActivityForm(forms.ModelForm):
    class Meta:
        model = LeadActivity
        fields = ["activity_type", "note", "next_follow_up_date"]
        widgets = {
            "activity_type": forms.Select(attrs={"class": "form-control"}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Follow-up notes"}),
            "next_follow_up_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["next_follow_up_date"].required = False


class LeadConfirmForm(forms.Form):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Leave blank to use phone last 6 digits"}
        ),
        label="Customer login password",
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"}),
    )

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        confirm = cleaned.get("confirm_password") or ""
        if password and password != confirm:
            self.add_error("confirm_password", "Passwords do not match.")
        if password and len(password) < 6:
            self.add_error("password", "Password must be at least 6 characters.")
        return cleaned
