from django.db import models
from django.contrib.auth.models import User

from products.models import ProductScan
from users.models import CompanyProfile


class Complaint(models.Model):

    STAGE_CHOICES = [
        ('REGISTERED', 'Registered'),
        ('FORWARDED', 'Forwarded to Company'),
        ('RESPONDED', 'Initial Response from Company'),
        ('VERIFICATION', 'Verification'),
        ('COMPLETED', 'Completion'),
    ]

    complaint_id = models.AutoField(primary_key=True)

    complaint_number = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    # --------------------------------------------------------
    # CUSTOMER
    # --------------------------------------------------------

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='complaints'
    )

    # --------------------------------------------------------
    # ORIGINAL PARAKH SCAN
    # --------------------------------------------------------
    #
    # This is the important connection to the original report.
    #
    # Company can use:
    #
    # complaint.scan.id
    #
    # to open the exact original Parakh result.
    # --------------------------------------------------------

    scan = models.ForeignKey(
        ProductScan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complaints'
    )

    # --------------------------------------------------------
    # REGISTERED COMPANY
    # --------------------------------------------------------

    company = models.ForeignKey(
        CompanyProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complaints'
    )

    # --------------------------------------------------------
    # COMPLAINT INFORMATION
    # --------------------------------------------------------

    subject = models.CharField(
        max_length=200
    )

    description = models.TextField()

    product_name = models.CharField(
        max_length=200
    )

    company_name = models.CharField(
        max_length=200
    )

    violation_category = models.CharField(
        max_length=500
    )

    # --------------------------------------------------------
    # ORIGINAL PARAKH COMPLIANCE REPORT
    # --------------------------------------------------------

    compliance_report = models.TextField(
        blank=True
    )

    # --------------------------------------------------------
    # CURRENT STAGE
    # --------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=STAGE_CHOICES,
        default='REGISTERED'
    )

    # --------------------------------------------------------
    # CUSTOMER SUBMISSION
    # --------------------------------------------------------

    submitted = models.DateTimeField(
        auto_now_add=True
    )

    # --------------------------------------------------------
    # FORWARDED TO COMPANY
    # --------------------------------------------------------

    forwarded_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # --------------------------------------------------------
    # COMPANY INITIAL RESPONSE
    # --------------------------------------------------------

    initial_response = models.TextField(
        blank=True,
        null=True
    )

    initial_response_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # --------------------------------------------------------
    # COMPANY VERIFICATION
    # --------------------------------------------------------
    #
    # This is where the company explains/submits what was
    # corrected or verified after reviewing the complaint.
    # --------------------------------------------------------

    verification_details = models.TextField(
        blank=True,
        null=True
    )

    verification_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # --------------------------------------------------------
    # COMPLETION
    # --------------------------------------------------------

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return (
            f"Complaint "
            f"#{self.complaint_number or self.complaint_id}"
        )