from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse

from .models import ProductScan, ProductScanImage
from compliance.models import ComplianceRule
from compliance.engine.pipeline import run_scan
from complaint.models import Complaint

def home_view(request):
    return render(request, 'index.html')


MIN_IMAGES_REQUIRED = 2


def scan_view(request):
    if request.method == 'POST':
        images = request.FILES.getlist('images')
        # backward compat: a single-file post under the old field name
        if not images and request.FILES.get('image'):
            images = [request.FILES.get('image')]

        if len(images) < MIN_IMAGES_REQUIRED:
            message = (
                f"Please provide at least {MIN_IMAGES_REQUIRED} photos covering the whole "
                "packet (front and back, and any side panels with extra declarations) - a "
                "single photo rarely shows every mandatory declaration."
            )
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (
                request.content_type or ''
            ).startswith('multipart')
            if is_ajax:
                return JsonResponse({'error': message}, status=400)
            return render(request, 'scan.html', {'error': message})

        product_name = request.POST.get('product_name', '')
        category = request.POST.get('category', '')
        user = request.user if request.user.is_authenticated else None

        scan = ProductScan.objects.create(
            user=user,
            product_name=product_name,
            category=category,
            image=images[0],
            status='PENDING',
        )
        for i, img in enumerate(images):
            ProductScanImage.objects.create(scan=scan, image=img, order=i)

        run_scan(scan)

        redirect_url = reverse('result', kwargs={'scan_id': scan.id})
        if (request.content_type or '').startswith('multipart'):
            return JsonResponse({'redirect_url': redirect_url})
        return redirect('result', scan_id=scan.id)

    return render(request, 'scan.html')


def result_view(request, scan_id):
    if request.user.is_authenticated:
        scan = get_object_or_404(
            ProductScan,
            id=scan_id,
            user=request.user
        )
    else:
        scan = get_object_or_404(
            ProductScan,
            id=scan_id
        )

    context = {
        'scan': scan,
    }

    # ---------------------------------------------------------
    # COMPLAINT / REPORT NAVIGATION
    # ---------------------------------------------------------

    existing_complaint = None

    if request.user.is_authenticated:
        existing_complaint = (
            Complaint.objects
            .filter(
                user=request.user,
                scan=scan
            )
            .order_by('-submitted')
            .first()
        )

    context['existing_complaint'] = existing_complaint

    # True when report was opened from Complaint Details
    context['from_complaint'] = (
        request.GET.get('from_complaint') == '1'
    )

    # True when report was opened from the Complaint Form
    context['from_complaint_form'] = (
        request.GET.get('from_complaint_form') == '1'
    )

    # True when report was opened from History
    context['from_history'] = (
        request.GET.get('from_history') == '1'
    )

    # ---------------------------------------------------------
    # NEEDS MORE IMAGES
    # ---------------------------------------------------------

    if scan.status == 'NEEDS_MORE_IMAGES':
        context['needs_more_images'] = True

        context['coverage_message'] = (
            "We couldn't locate enough of the mandatory declarations "
            "across the photo(s) provided to judge compliance fairly. "
            "Please rescan with photos covering the whole pack - front, "
            "back, and the ingredients/nutrition panel."
        )

        return render(
            request,
            'result.html',
            context
        )

    # ---------------------------------------------------------
    # OCR / COMPLIANCE PROCESSING
    # ---------------------------------------------------------

    extracted = getattr(
        scan,
        'extracted_data',
        None
    )

    report = getattr(
        scan,
        'compliance_report',
        None
    )

    if report is None or extracted is None:
        context['processing'] = True

        return render(
            request,
            'result.html',
            context
        )

    # ---------------------------------------------------------
    # VIOLATIONS
    # ---------------------------------------------------------

    violations = list(
        report.violations
        .select_related('rule')
        .all()
    )

    context['violation_count'] = len(violations)

    context['violations'] = [
        {
            'index': i + 1,
            'title': v.rule.title,
            'details': v.details,
            'rule_citation': v.rule.description,
        }
        for i, v in enumerate(violations)
    ]

    # ---------------------------------------------------------
    # COMPLIANCE RESULT
    # ---------------------------------------------------------

    context['is_compliant'] = report.is_compliant
    context['overall_score'] = report.overall_score

    # ---------------------------------------------------------
    # NUTRITION
    # ---------------------------------------------------------

    context['nutrition_rows'] = (
        extracted.nutritional_info or []
    )

    # ---------------------------------------------------------
    # ADDITIVES
    # ---------------------------------------------------------

    additives = extracted.additives_info or []

    context['additives'] = list(additives)

    context['has_banned_additive'] = any(
        a.get('is_banned')
        for a in additives
    )

    context['no_additives_detected'] = (
        len(additives) == 0
    )

    # ---------------------------------------------------------
    # PRODUCT NAME
    # ---------------------------------------------------------

    context['product_name_display'] = (
        extracted.product_name_declared
        or scan.product_name
        or "Unnamed Product"
    )

    return render(
        request,
        'result.html',
        context
    )

def result_json_view(request, scan_id):
    """
    Full JSON dump for a scan: every individual OCR line with its
    box/label/confidence (exactly what labeler.py produced, before
    aggregation), plus the final structured fields and compliance
    violations. Navigate to /result/<scan_id>/json/ in a browser to
    view/download it directly - built specifically so you don't have
    to keep pulling fields one at a time through `manage.py shell`.
    Uses the labeled_lines_json saved at scan time, so viewing this is
    instant - it does NOT re-run OCR.
    """
    if request.user.is_authenticated:
        scan = get_object_or_404(ProductScan, id=scan_id, user=request.user)
    else:
        scan = get_object_or_404(ProductScan, id=scan_id)

    extracted = getattr(scan, 'extracted_data', None)
    report = getattr(scan, 'compliance_report', None)

    data = {
        'scan_id': scan.id,
        'status': scan.status,
        'product_name': scan.product_name,
        'scanned_at': scan.scanned_at.isoformat() if scan.scanned_at else None,
    }

    if extracted is None:
        data['note'] = 'No extraction data yet for this scan.'
        return JsonResponse(data, json_dumps_params={'indent': 2})

    # This is the raw labeler.py output - every OCR line, whichever
    # image it came from, with its box/label/confidence. Scans run
    # before this field existed won't have it (labeled_lines_json will
    # be null) - only newly-run scans include it.
    data['labeled_lines'] = extracted.labeled_lines_json

    data['structured_fields'] = {
        'product_name_declared': extracted.product_name_declared,
        'manufacturer_name': extracted.manufacturer_name,
        'manufacturer_address': extracted.manufacturer_address,
        'net_quantity_value': extracted.net_quantity_value,
        'net_quantity_unit': extracted.net_quantity_unit,
        'net_quantity_raw': extracted.net_quantity_raw,
        'mrp_value': extracted.mrp_value,
        'mrp_raw': extracted.mrp_raw,
        'consumer_contact_raw': extracted.consumer_contact_raw,
        'manufacturing_date_raw': extracted.manufacturing_date_raw,
        'expiry_date_raw': extracted.expiry_date_raw,
        'batch_number': extracted.batch_number,
        'fssai_license_no': extracted.fssai_license_no,
        'nutritional_info': extracted.nutritional_info,
        'additives_info': extracted.additives_info,
    }

    if report is not None:
        violations = list(report.violations.select_related('rule').all())
        data['compliance'] = {
            'is_compliant': report.is_compliant,
            'overall_score': report.overall_score,
            'violations': [
                {'rule_code': v.rule.rule_code, 'title': v.rule.title, 'details': v.details}
                for v in violations
            ],
        }

    return JsonResponse(data, json_dumps_params={'indent': 2})


@login_required(login_url='login')
def history_view(request):
    scans = ProductScan.objects.filter(user=request.user).order_by('-scanned_at')
    return render(request, 'history.html', {'scans': scans})


def rules_view(request):
    rules = ComplianceRule.objects.filter(is_active=True)
    return render(request, 'rules.html', {'rules': rules})