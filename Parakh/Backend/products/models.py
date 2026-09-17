from django.db import models
from django.contrib.auth.models import User

class ProductScan(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLIANT', 'Compliant'),
        ('NON_COMPLIANT', 'Non-Compliant'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scans', null=True, blank=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    image = models.ImageField(upload_to='product_scans/')
    scanned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    # Store complete audit JSON
    report_data = models.JSONField(blank=True, null=True)

    def __str__(self):
        return f"{self.product_name or 'Scan'} - {self.scanned_at.strftime('%d %b %Y')}"

class ScanViolation(models.Model):
    scan = models.ForeignKey(ProductScan, on_delete=models.CASCADE, related_name='violations')
    rule_name = models.CharField(max_length=255)
    description = models.TextField()
    severity = models.CharField(max_length=50, default='High')  # High, Medium, Low