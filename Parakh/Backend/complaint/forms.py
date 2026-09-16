from django import forms
from .models import Complaint


class ComplaintForm(forms.ModelForm):

    class Meta:

        model = Complaint

        fields = [
            'subject',
            'description',
            'product_name',
            'company_name',
            'violation_category',
            'evidence',
        ]

        widgets = {

            'subject': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter complaint subject',
                    'required': True,
                }
            ),

            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Describe the issue or violation',
                    'rows': 5,
                    'required': True,
                }
            ),

            'product_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter product name',
                    'required': True,
                }
            ),

            'company_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter company / manufacturer name',
                    'required': True,
                }
            ),

            'violation_category': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter violation category',
                    'required': True,
                }
            ),

            'evidence': forms.ClearableFileInput(
                attrs={
                    'class': 'form-control',
                    'accept': 'image/*',
                    'required': True,
                }
            ),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Make every form field compulsory
        for field in self.fields.values():
            field.required = True