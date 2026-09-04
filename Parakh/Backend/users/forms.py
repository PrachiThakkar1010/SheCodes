from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import UserProfile

class CustomUserRegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=50, required=True, label="Full Name")
    email = forms.EmailField(required=True, label="Email Address")
    mobile_number = forms.CharField(max_length=15, required=True, label="Mobile Number")

    class Meta:
        model = User
        fields = ('username', 'first_name', 'email')

    def save(self, commit=True):
        user = super().save(commit=True)
        # Create or update profile with the mobile number
        UserProfile.objects.create(
            user=user,
            mobile_number=self.cleaned_data.get('mobile_number')
        )
        return user