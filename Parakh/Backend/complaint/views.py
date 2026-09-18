from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from products.models import ProductScan
from users.models import CompanyProfile

from .forms import ComplaintForm
from .models import Complaint


# ============================================================
# PROFILE CHECK
# ============================================================

def _profile_is_complete(user):
    """
    Customer must have:
        - email
        - mobile number
    """

    if not user.email or not user.email.strip():
        return False

    if not hasattr(user, 'profile'):
        return False

    if not user.profile.mobile_number:
        return False

    if not user.profile.mobile_number.strip():
        return False

    return True


# ============================================================
# COMPANY NAME NORMALIZATION
# ============================================================

def _normalize_company_name(value):
    """
    Normalize company/manufacturer names before comparison.

    Example:

        BALAJI WAFERS
        Balaji Wafers
        Balaji Wafers Pvt. Ltd.

    become easier to compare.

    This is deliberately conservative. We do not want to
    accidentally assign a complaint to the wrong company.
    """

    if not value:
        return ''

    value = str(value).strip().lower()

    replacements = [
        ('.', ' '),
        (',', ' '),
        ('-', ' '),
        ('_', ' '),
        ('&', ' and '),
    ]

    for old, new in replacements:
        value = value.replace(old, new)

    company_suffixes = [
        'private limited',
        'pvt ltd',
        'pvt. ltd',
        'pvt ltd.',
        'limited',
        'ltd',
        'ltd.',
        'llp',
    ]

    for suffix in company_suffixes:
        if value.endswith(suffix):
            value = value[:-len(suffix)]

    return ' '.join(value.split())


# ============================================================
# FIND REGISTERED COMPANY
# ============================================================

def _find_company(company_name):
    """
    Try to associate a complaint with a registered
    CompanyProfile.

    Returns:
        CompanyProfile instance
        OR
        None
    """

    normalized_name = _normalize_company_name(
        company_name
    )

    if not normalized_name:
        return None

    companies = CompanyProfile.objects.all()

    for company in companies:

        registered_name = _normalize_company_name(
            company.company_name
        )

        if not registered_name:
            continue

        # Exact normalized match.
        if normalized_name == registered_name:
            return company

        # Conservative containment match for cases such as:
        #
        # "balaji wafers"
        # "balaji wafers pvt ltd"
        #
        # Only accept this when one is clearly contained in
        # the other.
        if (
            normalized_name in registered_name
            or registered_name in normalized_name
        ):
            return company

    return None


# ============================================================
# COMPLAINT SUBMISSION
# ============================================================

@login_required(login_url='login')
def submit_complaint(request):

    user = request.user

    scan_id = (
        request.GET.get('scan_id')
        or request.POST.get('scan_id')
    )

    if not scan_id:
        messages.error(
            request,
            'No compliance report was selected for this complaint.'
        )
        return redirect('dashboard')

    complaint_url = (
        reverse('complaint_home')
        + '?'
        + urlencode({
            'scan_id': scan_id
        })
    )

    # --------------------------------------------------------
    # PROFILE CHECK
    # --------------------------------------------------------

    if not _profile_is_complete(user):

        messages.warning(
            request,
            'Please complete your email address and mobile number '
            'before filing a complaint.'
        )

        profile_url = (
            reverse('profile')
            + '?'
            + urlencode({
                'next': complaint_url
            })
        )

        return redirect(profile_url)

    # --------------------------------------------------------
    # GET SCAN
    # --------------------------------------------------------

    scan = get_object_or_404(
        ProductScan.objects.select_related('user'),
        id=scan_id
    )

    if scan.user is not None and scan.user != user:

        messages.error(
            request,
            'You cannot file a complaint using another user\'s scan.'
        )

        return redirect('dashboard')

    # --------------------------------------------------------
    # CLAIM GUEST SCAN
    # --------------------------------------------------------

    if scan.user is None:

        scan.user = user

        scan.save(
            update_fields=['user']
        )

    # --------------------------------------------------------
    # GET REPORT
    # --------------------------------------------------------

    report = getattr(
        scan,
        'compliance_report',
        None
    )

    if report is None:

        messages.error(
            request,
            'The compliance report for this scan is not available yet.'
        )

        return redirect(
            'result',
            scan_id=scan.id
        )

    # --------------------------------------------------------
    # ONLY NON-COMPLIANT PRODUCTS
    # --------------------------------------------------------

    if report.is_compliant:

        messages.info(
            request,
            'A complaint can only be filed for a non-compliant product.'
        )

        return redirect(
            'result',
            scan_id=scan.id
        )

    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    existing_complaint = (
        Complaint.objects
        .filter(
            user=user,
            scan=scan
        )
        .order_by('-submitted')
        .first()
    )

    if existing_complaint:

        display_number = (
            existing_complaint.complaint_number
            or existing_complaint.complaint_id
        )

        messages.info(
            request,
            f'Jaanch #{display_number} has already been filed '
            'for this product.'
        )

        return redirect(
            'complaint_detail',
            complaint_id=existing_complaint.complaint_id
        )

    # --------------------------------------------------------
    # OCR DATA
    # --------------------------------------------------------

    extracted = getattr(
        scan,
        'extracted_data',
        None
    )

    # --------------------------------------------------------
    # VIOLATIONS
    # --------------------------------------------------------

    violations = list(
        report.violations
        .select_related('rule')
        .all()
    )

    # --------------------------------------------------------
    # VIOLATION CATEGORY
    # --------------------------------------------------------

    violation_titles = []

    for violation in violations:

        rule = getattr(
            violation,
            'rule',
            None
        )

        title = getattr(
            rule,
            'title',
            None
        )

        if title:
            violation_titles.append(title)

    violation_category = ', '.join(
        violation_titles
    )

    if not violation_category:
        violation_category = (
            'Legal Metrology Compliance Violation'
        )

    # --------------------------------------------------------
    # COMPLIANCE REPORT TEXT
    # --------------------------------------------------------

    report_sections = []

    for index, violation in enumerate(
        violations,
        start=1
    ):

        rule = getattr(
            violation,
            'rule',
            None
        )

        rule_title = getattr(
            rule,
            'title',
            'Compliance Violation'
        )

        details = getattr(
            violation,
            'details',
            ''
        )

        rule_description = getattr(
            rule,
            'description',
            ''
        )

        section = (
            f'Violation {index}: {rule_title}\n'
            f'Details: {details}\n'
            f'Applicable Rule: {rule_description}'
        )

        report_sections.append(section)

    compliance_report_text = '\n\n'.join(
        report_sections
    )

    if not compliance_report_text:

        compliance_report_text = (
            'Parakh identified this product as non-compliant. '
            'Please review the original scan and compliance report.'
        )

    # --------------------------------------------------------
    # PRODUCT NAME
    # --------------------------------------------------------

    product_name = (
        getattr(
            extracted,
            'product_name_declared',
            None
        )
        if extracted
        else None
    )

    product_name = (
        product_name
        or scan.product_name
        or 'Unnamed Product'
    )

    # --------------------------------------------------------
    # COMPANY / MANUFACTURER
    # --------------------------------------------------------

    detected_company_name = (
        getattr(
            extracted,
            'manufacturer_name',
            None
        )
        if extracted
        else None
    )

    if isinstance(detected_company_name, str):
        detected_company_name = (
            detected_company_name.strip()
        )

    detected_company_name = (
        detected_company_name
        or 'Manufacturer not detected'
    )

    # --------------------------------------------------------
    # PREPARE FORM DATA
    # --------------------------------------------------------

    parakh_scan = {
        'scan_id': scan.id,
        'product_name': product_name,
        'company_name': detected_company_name,
        'violation_category': violation_category,
        'subject': 'Non-Compliant Product Report',
        'description': '',
        'compliance_report': compliance_report_text,
    }

    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    if request.method == 'POST':

        form = ComplaintForm(
            request.POST,
            parakh_scan=parakh_scan
        )

        if form.is_valid():

            last_number = (
                Complaint.objects
                .filter(
                    user=user
                )
                .aggregate(
                    max_number=Max(
                        'complaint_number'
                    )
                )['max_number']
            )

            next_number = (
                last_number or 0
            ) + 1

            complaint = form.save(
                commit=False
            )

            # ------------------------------------------------
            # SECURITY / OWNERSHIP
            # ------------------------------------------------

            complaint.user = user
            complaint.scan = scan

            # ------------------------------------------------
            # COMPLAINT NUMBER
            # ------------------------------------------------

            complaint.complaint_number = (
                next_number
            )

            # ------------------------------------------------
            # PRODUCT
            # ------------------------------------------------

            complaint.product_name = (
                product_name
            )

            # ------------------------------------------------
            # COMPANY NAME
            # ------------------------------------------------

            if (
                detected_company_name
                == 'Manufacturer not detected'
            ):

                complaint.company_name = (
                    form.cleaned_data['company_name']
                )

            else:

                complaint.company_name = (
                    detected_company_name
                )

            # ------------------------------------------------
            # FIND REGISTERED COMPANY
            # ------------------------------------------------

            complaint.company = _find_company(
                complaint.company_name
            )

            # ------------------------------------------------
            # VIOLATION
            # ------------------------------------------------

            complaint.violation_category = (
                violation_category
            )

            # ------------------------------------------------
            # ORIGINAL PARAKH REPORT
            # ------------------------------------------------

            complaint.compliance_report = (
                compliance_report_text
            )

            # ------------------------------------------------
            # INITIAL STAGE
            # ------------------------------------------------

            complaint.status = 'REGISTERED'

            complaint.save()

            messages.success(
                request,
                f'Jaanch #{complaint.complaint_number} '
                'submitted successfully.'
            )

            return redirect(
                'complaint_list'
            )

    else:

        form = ComplaintForm(
            parakh_scan=parakh_scan
        )

    # --------------------------------------------------------
    # ORIGINAL PRODUCT IMAGES
    # --------------------------------------------------------

    scan_images = scan.images.all()

    # --------------------------------------------------------
    # CONTEXT
    # --------------------------------------------------------

    context = {
        'form': form,
        'scan': scan,
        'scan_images': scan_images,
        'parakh_scan': parakh_scan,
        'compliance_report': compliance_report_text,
        'violations': violations,
        'company_detected': (
            detected_company_name
            != 'Manufacturer not detected'
        ),
    }

    return render(
        request,
        'complaint.html',
        context
    )


# ============================================================
# CUSTOMER COMPLAINT TRACKING
# ============================================================

@login_required(login_url='login')
def complaint_list(request):

    complaints = (
        Complaint.objects
        .filter(
            user=request.user
        )
        .select_related(
            'scan',
            'company'
        )
        .prefetch_related(
            'scan__images'
        )
        .order_by(
            '-submitted'
        )
    )

    return render(
        request,
        'complaint_tracking.html',
        {
            'complaints': complaints,
        }
    )


# ============================================================
# CUSTOMER COMPLAINT DETAIL
# ============================================================

@login_required(login_url='login')
def complaint_detail(request, complaint_id):

    complaint = get_object_or_404(
        Complaint.objects
        .select_related(
            'scan',
        )
        .prefetch_related(
            'scan__images'
        ),
        complaint_id=complaint_id,
        user=request.user
    )

    scan_images = []

    if complaint.scan:

        scan_images = (
            complaint.scan
            .images
            .all()
        )

    # --------------------------------------------------------
    # FOUR-STAGE TRACKING
    # --------------------------------------------------------

    stages = [
        {
            'key': 'REGISTERED',
            'label': 'Registered',
            'timestamp': complaint.submitted,
        },
        {
            'key': 'FORWARDED',
            'label': 'Forwarded to Company',
            'timestamp': complaint.forwarded_at,
        },
        {
            'key': 'RESPONDED',
            'label': 'Initial Response',
            'timestamp': complaint.initial_response_at,
        },
        {
            'key': 'COMPLETED',
            'label': 'Completion',
            'timestamp': complaint.completed_at,
        },
    ]

    stage_order = [
        'REGISTERED',
        'FORWARDED',
        'RESPONDED',
        'COMPLETED',
    ]

    try:

        current_stage_index = (
            stage_order.index(
                complaint.status
            )
        )

    except ValueError:

        current_stage_index = 0

    for index, stage in enumerate(stages):

        stage['completed'] = (
            index <= current_stage_index
        )

        stage['active'] = (
            index == current_stage_index
        )

    context = {
        'complaint': complaint,
        'scan_images': scan_images,
        'tracking_stages': stages,
        'current_stage_index': current_stage_index,
    }

    return render(
        request,
        'complaint_detail.html',
        context
    )


# ============================================================
# COMPANY COMPLAINT DASHBOARD
# ============================================================

@login_required(login_url='login')
def company_complaint_list(request):
    """
    Company users see only complaints associated with
    their CompanyProfile.
    """

    if not hasattr(request.user, 'companyprofile'):

        messages.error(
            request,
            'Company access is required to view company complaints.'
        )

        return redirect('dashboard')

    company = request.user.companyprofile

    complaints = (
        Complaint.objects
        .filter(
            company=company
        )
        .select_related(
            'user',
            'scan',
            'company'
        )
        .order_by(
            '-submitted'
        )
    )

    return render(
        request,
        'company_complaints.html',
        {
            'complaints': complaints,
            'company': company,
        }
    )


# ============================================================
# COMPANY COMPLAINT DETAIL / JAANCH
# ============================================================

@login_required(login_url='login')
def company_complaint_detail(request, complaint_id):
    """
    Company-side complaint detail.

    A company can ONLY access complaints assigned to its
    CompanyProfile.
    """

    if not hasattr(request.user, 'companyprofile'):

        messages.error(
            request,
            'Company access is required.'
        )

        return redirect('dashboard')

    company = request.user.companyprofile

    complaint = get_object_or_404(
        Complaint.objects
        .select_related(
            'user',
            'scan',
            'company'
        )
        .prefetch_related(
            'scan__images'
        ),
        complaint_id=complaint_id,
        company=company
    )

    scan_images = []

    if complaint.scan:

        scan_images = (
            complaint.scan
            .images
            .all()
        )

    return render(
        request,
        'company_complaint_detail.html',
        {
            'complaint': complaint,
            'company': company,
            'scan_images': scan_images,
        }
    )


# ============================================================
# COMPANY INITIAL RESPONSE
# ============================================================

@login_required(login_url='login')
def company_initial_response(request, complaint_id):
    """
    Company submits its first response.

    REGISTERED / FORWARDED
            ↓
        RESPONDED
    """

    if not hasattr(request.user, 'companyprofile'):

        messages.error(
            request,
            'Company access is required.'
        )

        return redirect('dashboard')

    company = request.user.companyprofile

    complaint = get_object_or_404(
        Complaint,
        complaint_id=complaint_id,
        company=company
    )

    if request.method != 'POST':

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    response_text = (
        request.POST.get(
            'initial_response',
            ''
        )
        .strip()
    )

    if not response_text:

        messages.error(
            request,
            'Please enter your initial response.'
        )

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    complaint.initial_response = response_text

    complaint.initial_response_at = timezone.now()

    complaint.status = 'RESPONDED'

    complaint.save(
        update_fields=[
            'initial_response',
            'initial_response_at',
            'status',
        ]
    )

    messages.success(
        request,
        'Initial response submitted successfully.'
    )

    return redirect(
        'company_complaint_detail',
        complaint_id=complaint.complaint_id
    )


# ============================================================
# COMPANY VERIFICATION
# ============================================================

@login_required(login_url='login')
def company_verification(request, complaint_id):
    """
    Company submits verification/correction details.

    RESPONDED
        ↓
    VERIFICATION
    """

    if not hasattr(request.user, 'companyprofile'):

        messages.error(
            request,
            'Company access is required.'
        )

        return redirect('dashboard')

    company = request.user.companyprofile

    complaint = get_object_or_404(
        Complaint,
        complaint_id=complaint_id,
        company=company
    )

    if request.method != 'POST':

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    verification_details = (
        request.POST.get(
            'verification_details',
            ''
        )
        .strip()
    )

    if not verification_details:

        messages.error(
            request,
            'Please enter the verification details.'
        )

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    complaint.verification_details = (
        verification_details
    )

    complaint.verification_at = (
        timezone.now()
    )

    complaint.status = 'VERIFICATION'

    complaint.save(
        update_fields=[
            'verification_details',
            'verification_at',
            'status',
        ]
    )

    messages.success(
        request,
        'Verification submitted successfully.'
    )

    return redirect(
        'company_complaint_detail',
        complaint_id=complaint.complaint_id
    )


# ============================================================
# COMPANY COMPLETE COMPLAINT
# ============================================================

@login_required(login_url='login')
def company_complete_complaint(
    request,
    complaint_id
):
    """
    Company marks a verified complaint as completed.

    VERIFICATION
        ↓
    COMPLETED
    """

    if not hasattr(request.user, 'companyprofile'):

        messages.error(
            request,
            'Company access is required.'
        )

        return redirect('dashboard')

    company = request.user.companyprofile

    complaint = get_object_or_404(
        Complaint,
        complaint_id=complaint_id,
        company=company
    )

    if request.method != 'POST':

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    if not complaint.verification_details:

        messages.error(
            request,
            'Verification must be submitted before completion.'
        )

        return redirect(
            'company_complaint_detail',
            complaint_id=complaint.complaint_id
        )

    complaint.status = 'COMPLETED'

    complaint.completed_at = (
        timezone.now()
    )

    complaint.save(
        update_fields=[
            'status',
            'completed_at',
        ]
    )

    messages.success(
        request,
        'Jaanch marked as completed.'
    )

    return redirect(
        'company_complaint_detail',
        complaint_id=complaint.complaint_id
    )