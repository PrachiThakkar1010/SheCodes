from django.contrib import admin

from django.contrib import admin
from .models import ProductScan, ExtractedLabelData

admin.site.register(ProductScan)
admin.site.register(ExtractedLabelData)
