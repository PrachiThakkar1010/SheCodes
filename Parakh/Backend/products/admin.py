from django.contrib import admin
from .models import ProductScan

from django.contrib import admin
from .models import ProductScan, ExtractedLabelData

admin.site.register(ProductScan)
admin.site.register(ExtractedLabelData)
@admin.register(ProductScan)
class ProductScanAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at') if hasattr(ProductScan, 'created_at') else ('id', 'user')

# Comment out if ExtractedLabelData no longer exists:
# admin.site.register(ExtractedLabelData)