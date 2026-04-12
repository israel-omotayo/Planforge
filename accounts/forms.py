from django.contrib.auth.password_validation import (
    MinimumLengthValidator,
    UserAttributeSimilarityValidator,
    CommonPasswordValidator,
    NumericPasswordValidator,
)
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth import get_user_model
from django import forms

#gets the currently active user model
User = get_user_model()

"""
Creates a new user, validates details, checks password rules, ensures password confirmation matches, 
hashes the password, and saves the user as inactive.
"""
class SignUpForm(forms.ModelForm):
    #render_value=False prevents the password from being redisplayed if the form is re-rendered with errors
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Password", "autocomplete": "off"}, render_value=False),
        label="Password"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm password", "autocomplete": "off"}, render_value=False),
        label="Confirm Password"
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "First Name"})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Last Name"})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "Email Address"})
    )
    username = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Username"})
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name"]

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            # only block if an ACTIVE user already has this username.
            # Never delete accounts here — that belongs in the service layer
            if User.objects.filter(username__iexact=username, is_active=True).exists():
                raise forms.ValidationError("That username is already taken.")
        return username

    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name')
        if any(char.isdigit() for char in first_name):
            raise forms.ValidationError("Names should not contain numbers.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name')
        if any(char.isdigit() for char in last_name):
            raise forms.ValidationError("Names should not contain numbers.")
        return last_name

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # only block if an ACTIVE user already has this email.
            # Never delete accounts here — see clean_username note above.
            if User.objects.filter(email__iexact=email, is_active=True).exists():
                raise forms.ValidationError("Email address is already registered.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not password:
            return password

        validators = [
            MinimumLengthValidator(min_length=8),
            UserAttributeSimilarityValidator(),
            CommonPasswordValidator(),
            NumericPasswordValidator(),
        ]

        for validator in validators:
            validator.validate(password, user=self.instance)

        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm = cleaned_data.get("confirm_password")

        if password and confirm and password != confirm:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data

    def save(self, commit=True):
        #creates a new user instance without saving it to the database yet
        user = super().save(commit=False)
        #set_password hashes the password and sets it on the user instance
        user.set_password(self.cleaned_data["password"])
        user.email = self.cleaned_data["email"]
        #new users set as inactive until they verify their email
        user.is_active = False
        if commit:
            user.save()
        return user
    
"""
Lets a logged-in user edit username, first name, last name, and email.
"""
class ProfileUpdateForm(forms.ModelForm):
    username = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={'placeholder': ' '})
    )
    first_name = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={'placeholder': ' '})
    )
    last_name = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={'placeholder': ' '})
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    # Set placeholder for all fields to a single space to prevent browser autofill from showing the default value
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in self.fields:
            self.fields[field_name].widget.attrs.setdefault('placeholder', ' ')
    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()

        if not username:
            raise forms.ValidationError("Username is required.")

        # Django's built-in validator: allows letters, digits, @, ., +, -, _
        validator = UnicodeUsernameValidator()
        try:
            validator(username)
        except forms.ValidationError:
            raise forms.ValidationError(
                "Username may only contain letters, numbers, and @, ., +, -, _ characters."
            )

        # Uniqueness check — exclude the current user so they can keep the same username
        qs = User.objects.filter(username__iexact=username, is_active=True)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That username is already taken.")

        return username

    def clean_first_name(self):
        first_name = self.cleaned_data.get("first_name", "").strip()
        if not first_name.isalpha():
            raise forms.ValidationError("First name should contain only letters.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get("last_name", "").strip()
        if not last_name.isalpha():
            raise forms.ValidationError("Last name should contain only letters.")
        return last_name

"""
Collects username and password for login.
"""
class LoginForm(forms.Form):
    username = forms.CharField(
        required=True,
        max_length=30,
        widget=forms.TextInput(attrs={'placeholder': 'Username', 'autocomplete': 'username'})
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'autocomplete': 'current-password'}, render_value=False)
    )

"""
Collects and validates a 6-digit verification code.
"""
class VerifyCodeForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': '000000', 'autocomplete': 'one-time-code', 'inputmode': 'numeric'})
    )    

    # Ensure the code is exactly 6 digits and contains only numbers
    def clean_code(self):
        #strip whitespace and validate that the code is numeric and 6 digits long
        code = self.cleaned_data.get('code', '').strip()
        if not code.isdigit():
            raise forms.ValidationError("Code must be 6 digits.")
        return code