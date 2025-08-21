from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

class UserRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('email', 'role')

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user and hasattr(user, 'role') and user.role in [User.Role.ADMIN, User.Role.MANAGER]:
            self.fields['role'].choices = User.Role.choices
        else:
            allowed_roles = [
                (User.Role.CLIENT, 'Client'),
                (User.Role.OPERATOR, 'Operator'),
            ]
            self.fields['role'].choices = allowed_roles
