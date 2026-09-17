from django.contrib import admin
from .models import ProductScan

@admin.register(ProductScan)
class ProductScanAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at') if hasattr(ProductScan, 'created_at') else ('id', 'user')

# Comment out if ExtractedLabelData no longer exists:
# admin.site.register(ExtractedLabelData)