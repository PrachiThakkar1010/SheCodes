from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from .models import ProductScan, ScanViolation
from .compliance_engine import audit_compliance_vision
from django.contrib.auth.decorators import login_required
from compliance.models import ComplianceRule

def home_view(request):
    return render(request, 'index.html')


def scan_view(request):
    if request.method == 'POST':
        primary_image = request.FILES.get('image')
        all_images = request.FILES.getlist('images')

        if not primary_image and not all_images:
            return JsonResponse({'error': 'No image provided'}, status=400)

        main_image = primary_image or all_images[0]
        user = request.user if request.user.is_authenticated else None

        scan = ProductScan.objects.create(
            user=user,
            image=main_image,
            product_name="Analyzing Product...",
            status='PENDING'
        )

        images_to_audit = all_images if all_images else [main_image]
        audit_report = audit_compliance_vision(images_to_audit)

        scan.product_name = audit_report.get('product_name', 'Packaged Product')
        scan.status = 'COMPLIANT' if audit_report.get('is_compliant') else 'NON_COMPLIANT'
        scan.report_data = audit_report
        scan.save()

        redirect_url = reverse('result', kwargs={'scan_id': scan.id})
        return JsonResponse({'redirect_url': redirect_url})

    return render(request, 'scan.html')

def result_view(request, scan_id):
    scan = get_object_or_404(ProductScan, id=scan_id)
    report = scan.report_data or {}
    return render(request, 'result.html', {'scan': scan, 'report': report})


@login_required(login_url='login')
def history_view(request):
    scans = ProductScan.objects.filter(user=request.user).order_by('-scanned_at')
    return render(request, 'history.html', {'scans': scans})


def rules_view(request):
    rules = ComplianceRule.objects.filter(is_active=True)
    return render(request, 'rules.html', {'rules': rules})


