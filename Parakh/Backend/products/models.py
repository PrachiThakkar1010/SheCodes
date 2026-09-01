from django.db import models

from django.db import models
from django.contrib.auth.models import User

class ProductScan(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLIANT', 'Compliant'),
        ('NON_COMPLIANT', 'Non-Compliant'),
        ('FAILED', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scans', null=True, blank=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    image = models.ImageField(upload_to='product_scans/')
    scanned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    def __str__(self):
        username = self.user.username if self.user else "Guest"
        return f"{self.product_name or 'Unnamed Product'} - {self.user.username} ({self.scanned_at.strftime('%Y-%m-%d %H:%M')})"


class ExtractedLabelData(models.Model):
    scan = models.OneToOneField(ProductScan, on_delete=models.CASCADE, related_name='extracted_data')
    raw_ocr_text = models.TextField()
    ingredients = models.TextField(blank=True, null=True)
    nutritional_info = models.JSONField(blank=True, null=True)  # Key-value pairs of nutrients
    manufacturing_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    fssai_license_no = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"OCR Data for Scan #{self.scan.id}"
