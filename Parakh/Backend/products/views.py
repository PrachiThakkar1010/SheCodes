from django.shortcuts import render

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import ProductScan
from compliance.models import ComplianceRule


def home_view(request):
    return render(request, 'index.html')


def scan_view(request):
    if request.method == 'POST' and request.FILES.get('image'):
        image = request.FILES.get('image')
        product_name = request.POST.get('product_name', '')
        category = request.POST.get('category', '')

        user = request.user if request.user.is_authenticated else None

        scan = ProductScan.objects.create(
            user=request.user,
            product_name=product_name,
            category=category,
            image=image,
            status='PENDING'
        )
        return redirect('result', scan_id=scan.id)

    return render(request, 'scan.html')


def result_view(request, scan_id):
    scan = get_object_or_404(ProductScan, id=scan_id, user=request.user)
    return render(request, 'result.html', {'scan': scan})


@login_required(login_url='login')
def history_view(request):
    scans = ProductScan.objects.filter(user=request.user).order_by('-scanned_at')
    return render(request, 'history.html', {'scans': scans})


def rules_view(request):
    rules = ComplianceRule.objects.filter(is_active=True)
    return render(request, 'rules.html', {'rules': rules})
