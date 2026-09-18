import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage

from .models import PackagingProject, DesignSpecification, DesignChatMessage
from .compliance_rules_engine import (
    calculate_pdp_area,
    get_statutory_font_sizes,
    calculate_unit_sale_price,
    compile_full_statutory_spec,
    validate_marketing_claims,
    detect_allergens,
)
from .assistant_service import (
    generate_ai_design_recommendations,
    chat_with_packaging_assistant
)


def studio_view(request, project_id=None):
    """
    Main interactive packaging compliance studio view.
    """
    project = None
    if project_id:
        project = get_object_or_404(PackagingProject, id=project_id)
    elif request.user.is_authenticated:
        project = PackagingProject.objects.filter(user=request.user).order_by('-updated_at').first()

    recent_projects = []
    if request.user.is_authenticated:
        recent_projects = PackagingProject.objects.filter(user=request.user).order_by('-updated_at')[:5]

    context = {
        'project': project,
        'recent_projects': recent_projects,
    }
    return render(request, 'design_studio.html', context)


@csrf_exempt
def api_calculate_pdp(request):
    """
    Real-time dynamic endpoint to calculate PDP area, minimum statutory font sizes,
    and unit sale price as dimensions or net weight change.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    pack_type = data.get('pack_type', 'POUCH')
    try:
        h = float(data.get('height_cm', 15.0) or 15.0)
        w = float(data.get('width_cm', 10.0) or 10.0)
        d = float(data.get('depth_cm', 0.0) or 0.0)
        dia = float(data.get('diameter_cm', 0.0) or 0.0)
        net_qty = float(data.get('net_quantity', 100.0) or 100.0)
        qty_unit = str(data.get('quantity_unit', 'g'))
        mrp = float(data.get('mrp', 50.0) or 50.0)
    except (ValueError, TypeError) as err:
        return JsonResponse({'error': f'Invalid numeric parameter: {err}'}, status=400)

    pdp_area = calculate_pdp_area(pack_type, h, w, d, dia)
    font_specs = get_statutory_font_sizes(pdp_area, net_qty, qty_unit)
    usp_data = calculate_unit_sale_price(mrp, net_qty, qty_unit)

    return JsonResponse({
        'status': 'success',
        'pdp_area_sqcm': pdp_area,
        'font_specs': font_specs,
        'usp_data': usp_data,
    })


@csrf_exempt
def api_generate_spec(request):
    """
    Compiles statutory rules + Gemini AI design enrichment into a full packaging spec.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST.dict()

    user = request.user if request.user.is_authenticated else None

    # Step 1: Run deterministic compliance rules engine
    rule_spec = compile_full_statutory_spec(data)

    # Step 2: Enrich with Gemini GenAI (Nutrition Table, claim remedies, design tips)
    ai_enrichment = generate_ai_design_recommendations(data, rule_spec)

    merged_spec = {
        **rule_spec,
        "ai_enrichment": ai_enrichment
    }

    project_id = data.get('project_id')
    project = None
    if project_id:
        try:
            project = PackagingProject.objects.get(id=project_id)
            if user and project.user != user:
                project = None
        except PackagingProject.DoesNotExist:
            project = None

    if not project and (user or data.get('save_project')):
        project = PackagingProject.objects.create(
            user=user,
            title=data.get('title', 'Packaging Project'),
            category=data.get('category', 'FOOD_BEVERAGE'),
            pack_type=data.get('pack_type', 'POUCH'),
            height_cm=float(data.get('height_cm', 15.0) or 15.0),
            width_cm=float(data.get('width_cm', 10.0) or 10.0),
            depth_cm=float(data.get('depth_cm', 0.0) or 0.0),
            diameter_cm=float(data.get('diameter_cm', 0.0) or 0.0),
            net_quantity=float(data.get('net_quantity', 100.0) or 100.0),
            quantity_unit=data.get('quantity_unit', 'g'),
            mrp=float(data.get('mrp', 50.0) or 50.0),
            diet_type=data.get('diet_type', 'VEG'),
            brand_name=data.get('brand_name', 'PureCraft'),
            generic_product_name=data.get('generic_product_name', 'Product'),
            fssai_license_no=data.get('fssai_license_no', ''),
            manufacturer_name=data.get('manufacturer_name', ''),
            manufacturer_address=data.get('manufacturer_address', ''),
            consumer_care_email=data.get('consumer_care_email', ''),
            consumer_care_phone=data.get('consumer_care_phone', ''),
            ingredients=data.get('ingredients', ''),
            marketing_claims=data.get('marketing_claims', ''),
            shelf_life_months=int(data.get('shelf_life_months', 6) or 6),
            primary_color=data.get('primary_color', '#073b70'),
            accent_color=data.get('accent_color', '#f59e0b'),
            theme_preset=data.get('theme_preset', 'MODERN_NAVY'),
            finish_type=data.get('finish_type', 'MATTE'),
            hero_image_url=data.get('hero_image_url', ''),
        )

    if project:
        DesignSpecification.objects.update_or_create(
            project=project,
            defaults={
                'pdp_area_sqcm': rule_spec['pdp_calculations']['pdp_area_sqcm'],
                'min_font_size_mm': rule_spec['pdp_calculations']['min_general_font_mm'],
                'min_numeral_size_mm': rule_spec['pdp_calculations']['min_net_qty_numeral_mm'],
                'veg_symbol_size_mm': rule_spec['pdp_calculations']['veg_symbol']['square_side_mm'],
                'unit_sale_price_text': rule_spec['usp_data']['usp_text'],
                'spec_data': merged_spec
            }
        )

    return JsonResponse({
        'status': 'success',
        'project_id': project.id if project else None,
        'spec': merged_spec
    })


@csrf_exempt
def api_chat_assistant(request):
    """
    Conversational packaging legal assistant endpoint.
    Modifies packaging blueprint if instructed and returns compliance critique.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    message = data.get('message', '').strip()
    if not message:
        return JsonResponse({'error': 'Message is required'}, status=400)

    project_id = data.get('project_id')
    project_context = data.get('project_context')
    chat_history = data.get('history', [])

    project = None
    if project_id:
        try:
            project = PackagingProject.objects.get(id=project_id)
            if not project_context:
                project_context = {
                    'title': project.title,
                    'generic_product_name': project.generic_product_name,
                    'category': project.category,
                    'pack_type': project.pack_type,
                    'height_cm': project.height_cm,
                    'width_cm': project.width_cm,
                    'net_quantity': project.net_quantity,
                    'quantity_unit': project.quantity_unit,
                    'mrp': float(project.mrp),
                    'diet_type': project.diet_type,
                    'ingredients': project.ingredients,
                    'marketing_claims': project.marketing_claims,
                    'primary_color': project.primary_color,
                    'accent_color': project.accent_color,
                    'theme_preset': project.theme_preset,
                    'finish_type': project.finish_type,
                    'hero_image_url': project.hero_image_url,
                }
        except PackagingProject.DoesNotExist:
            pass

    chat_result = chat_with_packaging_assistant(message, chat_history, project_context)
    reply = chat_result.get('reply', '')
    blueprint_patch = chat_result.get('blueprint_patch')

    # If the chatbot emitted blueprint changes and a project exists, persist updates
    if project and blueprint_patch and isinstance(blueprint_patch, dict):
        allowed_fields = [
            'brand_name', 'generic_product_name', 'category', 'pack_type',
            'net_quantity', 'quantity_unit', 'mrp', 'diet_type', 'ingredients',
            'marketing_claims', 'primary_color', 'accent_color', 'bg_color',
            'theme_preset', 'finish_type', 'hero_image_url'
        ]
        for key, val in blueprint_patch.items():
            if key in allowed_fields and val is not None:
                if key in ('net_quantity', 'mrp') and isinstance(val, (int, float, str)):
                    try:
                        setattr(project, key, float(val))
                    except ValueError:
                        pass
                else:
                    setattr(project, key, val)
        project.save()

    # Persist in DB if logged in or project attached
    user = request.user if request.user.is_authenticated else None
    if user or project:
        DesignChatMessage.objects.create(
            project=project,
            user=user,
            role='user',
            content=message
        )
        DesignChatMessage.objects.create(
            project=project,
            user=user,
            role='assistant',
            content=reply,
            metadata={'blueprint_patch': blueprint_patch} if blueprint_patch else None
        )

    return JsonResponse({
        'status': 'success',
        'reply': reply,
        'blueprint_patch': blueprint_patch
    })


@csrf_exempt
def api_upload_asset(request):
    """
    Handles user uploads of product photos, illustrations, or company logos.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    file = request.FILES.get('image') or request.FILES.get('file') or request.FILES.get('asset_file')
    if not file:
        return JsonResponse({'error': 'No file uploaded'}, status=400)

    save_path = default_storage.save(f'packaging_assets/{file.name}', file)
    image_url = default_storage.url(save_path)

    return JsonResponse({
        'status': 'success',
        'image_url': image_url,
        'asset_url': image_url
    })


def spec_sheet_view(request, project_id=None):
    """
    Print-friendly, executive Packaging Compliance Handoff Sheet for graphic designers and printers.
    """
    project = None
    spec_data = {}

    if project_id:
        project = get_object_or_404(PackagingProject, id=project_id)
        if hasattr(project, 'spec') and project.spec:
            spec_data = project.spec.spec_data

    if not spec_data:
        default_data = {
            'title': project.title if project else 'PureCraft Packaging Spec',
            'generic_product_name': project.generic_product_name if project else 'Roasted Almonds with Sea Salt',
            'category': project.category if project else 'FOOD_BEVERAGE',
            'pack_type': project.pack_type if project else 'POUCH',
            'height_cm': project.height_cm if project else 16.0,
            'width_cm': project.width_cm if project else 11.0,
            'depth_cm': project.depth_cm if project else 4.0,
            'diameter_cm': project.diameter_cm if project else 0.0,
            'net_quantity': project.net_quantity if project else 100.0,
            'quantity_unit': project.quantity_unit if project else 'g',
            'mrp': float(project.mrp) if project else 60.0,
            'diet_type': project.diet_type if project else 'VEG',
            'brand_name': project.brand_name if project else 'PureCraft',
            'fssai_license_no': project.fssai_license_no if project else '10021000000000',
            'manufacturer_name': project.manufacturer_name if project else 'PureCraft Foods Pvt. Ltd.',
            'manufacturer_address': project.manufacturer_address if project else 'Plot 42, Food Park, Gurgaon - 122001',
            'consumer_care_email': project.consumer_care_email if project else 'care@purecraft.in',
            'consumer_care_phone': project.consumer_care_phone if project else '+91-1800-111-2222',
            'ingredients': project.ingredients if project else 'Almonds (96%), Sunflower Oil, Sea Salt (1.5%), Rosemary Extract.',
            'marketing_claims': project.marketing_claims if project else 'High Protein, Zero Trans Fat, No Added Sugar, 100% Natural',
            'shelf_life_months': project.shelf_life_months if project else 6,
        }
        rule_spec = compile_full_statutory_spec(default_data)
        ai_enrichment = generate_ai_design_recommendations(default_data, rule_spec)
        spec_data = {**rule_spec, "ai_enrichment": ai_enrichment}

    return render(request, 'spec_sheet.html', {
        'project': project,
        'spec': spec_data
    })
