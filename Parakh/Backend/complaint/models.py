from django.db import models
from django.contrib.auth.models import User
from products.models import ProductScan


class Complaint(models.Model):

    STAGE_CHOICES = [
        ('REGISTERED', 'Registered'),
        ('FORWARDED', 'Forwarded to Company'),
        ('RESPONDED', 'Initial Response from Company'),
        ('COMPLETED', 'Completion'),
    ]

    complaint_id = models.AutoField(primary_key=True)

    complaint_number = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='complaints'
    )

    scan = models.ForeignKey(
        ProductScan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complaints'
    )

    subject = models.CharField(max_length=200)

    description = models.TextField()

    product_name = models.CharField(max_length=200)

    company_name = models.CharField(max_length=200)

    violation_category = models.CharField(max_length=500)

    compliance_report = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=STAGE_CHOICES,
        default='REGISTERED'
    )

    submitted = models.DateTimeField(auto_now_add=True)

    forwarded_at = models.DateTimeField(
        blank=True,
        null=True
    )

    initial_response = models.TextField(
        blank=True,
        null=True
    )

    initial_response_at = models.DateTimeField(
        blank=True,
        null=True
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return f"Complaint #{self.complaint_number or self.complaint_id}"