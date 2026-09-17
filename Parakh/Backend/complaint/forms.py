from django import forms

from .models import Complaint


class ComplaintForm(forms.ModelForm):
    """
    Complaint submission form.

    Product information and violation information are populated
    from Parakh's compliance scan.

    The original ProductScan images are automatically associated
    with the complaint through Complaint.scan, so the user does
    NOT upload evidence separately.
    """

    class Meta:
        model = Complaint

        fields = [
            'subject',
            'description',
            'product_name',
            'company_name',
            'violation_category',
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
                    'placeholder': (
                        'Describe the issue or add any additional information '
                        'you want to communicate to the company.'
                    ),
                    'rows': 6,
                    'required': True,
                }
            ),

            'product_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Product name',
                    'readonly': True,
                }
            ),

            'company_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Company / manufacturer name',
                }
            ),

            'violation_category': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Violation category',
                    'readonly': True,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        parakh_scan = kwargs.pop('parakh_scan', None)

        super().__init__(*args, **kwargs)

        # These fields are required for every complaint.
        self.fields['product_name'].required = True
        self.fields['company_name'].required = True
        self.fields['violation_category'].required = True

        if parakh_scan:

            # -------------------------------------------------
            # PRODUCT NAME
            # -------------------------------------------------

            product_name = parakh_scan.get(
                'product_name',
                ''
            )

            self.fields['product_name'].initial = product_name

            # -------------------------------------------------
            # COMPANY / MANUFACTURER
            # -------------------------------------------------

            company_name = parakh_scan.get(
                'company_name',
                ''
            )

            # If Parakh successfully detected the manufacturer,
            # keep the field readonly.
            if company_name and company_name != 'Manufacturer not detected':

                self.fields['company_name'].initial = company_name

                self.fields['company_name'].widget.attrs['readonly'] = True

                self.fields['company_name'].help_text = (
                    'Manufacturer identified from the product packaging.'
                )

            # If manufacturer was NOT detected, allow the user
            # to enter the company name manually.
            else:

                self.fields['company_name'].initial = ''

                self.fields['company_name'].widget.attrs.pop(
                    'readonly',
                    None
                )

                self.fields['company_name'].widget.attrs[
                    'placeholder'
                ] = 'Enter company / manufacturer name'

                self.fields['company_name'].help_text = (
                    'Parakh could not identify the manufacturer from '
                    'the scan. Please enter the company name shown '
                    'on the product packaging.'
                )

            # -------------------------------------------------
            # VIOLATION
            # -------------------------------------------------

            self.fields['violation_category'].initial = parakh_scan.get(
                'violation_category',
                ''
            )

            # -------------------------------------------------
            # SUBJECT
            # -------------------------------------------------

            self.fields['subject'].initial = parakh_scan.get(
                'subject',
                'Non-Compliant Product Report'
            )

            # -------------------------------------------------
            # DESCRIPTION
            # -------------------------------------------------

            self.fields['description'].initial = parakh_scan.get(
                'description',
                ''
            )