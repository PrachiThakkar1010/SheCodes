from django.db import models
from django.contrib.auth.models import User


class Complaint(models.Model):

    complaint_id = models.AutoField(primary_key=True)

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
    )

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
        max_length=100
    )

    evidence = models.ImageField(
        upload_to='complaint_evidence/'
    )

    compliance_report = models.TextField(
        blank=True
    )

    status = models.CharField(
        max_length=50,
        default='Submitted'
    )

    submitted = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Complaint #{self.complaint_id}"