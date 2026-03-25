from django import forms
from .models import Project, Task


class CreateProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "description", "status", "budget", "currency")
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "Project name",
                "maxlength": "50",
            }),
            "description": forms.Textarea(attrs={
                "placeholder": "What is this project about?",
                "rows": 4,
                "maxlength": "1000",
            }),
            "budget": forms.NumberInput(attrs={
                "placeholder": "e.g. 25000",
                "min": "0",
                "step": "0.01"
            }),
        }

    def clean_budget(self):
        budget = self.cleaned_data.get("budget")
        if budget is not None and budget < 0:
            raise forms.ValidationError("Budget cannot be negative.")
        return budget


class UpdateProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "description", "status", "budget", "currency")
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "Project name",
                "maxlength": "50",
            }),
            "description": forms.Textarea(attrs={
                "placeholder": "What is this project about?",
                "rows": 4,
                "maxlength": "1000",
            }),
            "budget": forms.NumberInput(attrs={
                "placeholder": "e.g. 25000",
                "min": "0",
                "step": "0.01"
            }),
        }

    def clean_budget(self):
        budget = self.cleaned_data.get("budget")
        if budget is not None and budget < 0:
            raise forms.ValidationError("Budget cannot be negative.")
        return budget


class TaskForm(forms.ModelForm):
    """
    Used for both create and edit — the view determines which action to take.
    The assignee queryset is set dynamically in the view based on org members.
    """
    class Meta:
        model = Task
        fields = ("title", "description", "status", "priority", "due_date", "assigned_to")
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "What needs to be done?",
                "maxlength": "50",
            }),
            "description": forms.Textarea(attrs={
                "placeholder": "Add more detail (optional)",
                "rows": 4,
                "maxlength": "500",
            }),
            "due_date": forms.DateInput(attrs={
                "type": "date",
            }),
        }

    # The queryset for the assignee field is set dynamically in the view based on org members and project guests.
    def __init__(self, *args, org_members=None, guest_members=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Include both org members and guest members, but avoid duplicates if some users are in both lists
        org_ids = {m.user_id for m in (org_members or [])}
        guest_ids = {m.user_id for m in (guest_members or [])}
        guest_only_ids = guest_ids - org_ids
        user_ids = list(org_ids) + list(guest_only_ids)

        from django.contrib.auth.models import User

        # Set the queryset for the assigned_to field to include only users who are either org members or guest members of the project
        queryset = User.objects.filter(pk__in=user_ids)
        self.fields["assigned_to"].queryset = queryset
        self.fields["assigned_to"].empty_label = "Unassigned"

        # Show "Full Name (@username)" or "@username" so duplicates are unambiguous
        def label_from_instance(user):
            full_name = user.get_full_name()
            if full_name:
                return f"{full_name} (@{user.username})"
            return f"@{user.username}"

        self.fields["assigned_to"].label_from_instance = label_from_instance