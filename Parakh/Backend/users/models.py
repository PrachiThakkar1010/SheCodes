from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)

class CompanyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='companyprofile')
    company_name = models.CharField(max_length=255)
    gst_number = models.CharField(max_length=50)

    def __str__(self):
        return self.company_name