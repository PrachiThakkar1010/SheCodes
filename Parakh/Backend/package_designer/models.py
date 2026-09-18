from django.db import models
from django.contrib.auth.models import User


class PackagingProject(models.Model):
    CATEGORY_CHOICES = [
        ('FOOD_BEVERAGE', 'Food & Beverages (General)'),
        ('DAIRY', 'Dairy & Milk Products'),
        ('SNACKS_CONFECTIONERY', 'Snacks & Confectionery'),
        ('NUTRACEUTICALS', 'Health Supplements & Nutraceuticals'),
        ('BEVERAGES', 'Packaged Drinking Water & Beverages'),
        ('COSMETICS', 'Cosmetics & Personal Care'),
        ('GENERAL_COMMODITY', 'General Packaged Commodity'),
    ]

    PACK_TYPE_CHOICES = [
        ('POUCH', 'Flexible Pouch / Bag'),
        ('BOX', 'Carton / Rectangular Box'),
        ('CYLINDER', 'Cylindrical Bottle / Can'),
        ('JAR', 'Tub / Jar'),
        ('TETRA', 'Tetra Pak / Multi-layered Carton'),
    ]

    DIET_TYPE_CHOICES = [
        ('VEG', 'Vegetarian (Green Dot)'),
        ('NON_VEG', 'Non-Vegetarian (Brown Triangle)'),
        ('NOT_APPLICABLE', 'Not Applicable (Non-food / Commodity)'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='packaging_projects', null=True, blank=True)
    title = models.CharField(max_length=255, default='New Packaging Project')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='FOOD_BEVERAGE')
    pack_type = models.CharField(max_length=30, choices=PACK_TYPE_CHOICES, default='POUCH')
    
    # Dimensions stored in cm
    height_cm = models.FloatField(default=15.0)
    width_cm = models.FloatField(default=10.0)
    depth_cm = models.FloatField(default=4.0, blank=True, null=True)
    diameter_cm = models.FloatField(blank=True, null=True)

    net_quantity = models.FloatField(default=100.0)
    quantity_unit = models.CharField(max_length=20, default='g')  # g, kg, ml, l, units
    mrp = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    
    diet_type = models.CharField(max_length=20, choices=DIET_TYPE_CHOICES, default='VEG')
    fssai_license_no = models.CharField(max_length=30, blank=True, null=True, default='10021000000000')
    
    brand_name = models.CharField(max_length=150, blank=True, default='PureCraft')
    generic_product_name = models.CharField(max_length=200, blank=True, default='Roasted Almonds with Sea Salt')
    
    manufacturer_name = models.CharField(max_length=255, blank=True, default='PureCraft Foods Pvt. Ltd.')
    manufacturer_address = models.TextField(blank=True, default='Plot No. 42, Food Park, Phase 1, Gurgaon, Haryana - 122001, India')
    packer_details = models.TextField(blank=True, null=True)
    country_of_origin = models.CharField(max_length=100, default='India')
    
    consumer_care_email = models.EmailField(default='care@purecraft.in')
    consumer_care_phone = models.CharField(max_length=50, default='+91-1800-111-2222')
    consumer_care_contact = models.TextField(blank=True, default='Manager - Consumer Redressal, PureCraft Foods, Plot 42, Food Park, Gurgaon')

    ingredients = models.TextField(blank=True, default='Almonds (96%), Edible Vegetable Oil (Sunflower), Edible Common Salt (Sea Salt 1.5%), Natural Rosemary Extract.')
    marketing_claims = models.TextField(blank=True, default='High Protein, Zero Trans Fat, No Added Sugar, 100% Natural')
    shelf_life_months = models.IntegerField(default=6)

    # Visual design, themes, colors, and imagery
    primary_color = models.CharField(max_length=20, default='#073b70')
    accent_color = models.CharField(max_length=20, default='#f59e0b')
    bg_color = models.CharField(max_length=20, default='#073b70')
    theme_preset = models.CharField(max_length=30, default='MODERN_NAVY')
    finish_type = models.CharField(max_length=30, default='MATTE')
    hero_image_url = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.generic_product_name}) - {self.user.username if self.user else 'Guest'}"


class DesignSpecification(models.Model):
    project = models.OneToOneField(PackagingProject, on_delete=models.CASCADE, related_name='spec')
    pdp_area_sqcm = models.FloatField(default=0.0)
    min_font_size_mm = models.FloatField(default=1.0)
    min_numeral_size_mm = models.FloatField(default=2.0)
    veg_symbol_size_mm = models.FloatField(default=3.0)
    unit_sale_price_text = models.CharField(max_length=100, blank=True)
    
    # Complete generated statutory JSON payload (PDP copy, back copy, claims review, nutrition table, layout blueprint)
    spec_data = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Spec for Project #{self.project.id} ({self.project.title})"


class DesignChatMessage(models.Model):
    project = models.ForeignKey(PackagingProject, on_delete=models.CASCADE, related_name='chat_messages', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    role = models.CharField(max_length=20, choices=[('user', 'User'), ('assistant', 'AI Assistant')])
    content = models.TextField()
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.role.upper()}] {self.content[:40]}..."

