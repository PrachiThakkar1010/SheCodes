from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from products.models import ProductScan

from .forms import ComplaintForm
from .models import Complaint


# ============================================================
# PROFILE CHECK
# ============================================================

def _profile_is_complete(user):
    """
    A user must have both:
        - email address
        - mobile number

    before filing a complaint.
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
# COMPLAINT SUBMISSION
# ============================================================

@login_required(login_url='login')
def submit_complaint(request):
    """
    Display and submit a complaint for a specific non-compliant scan.

    The scan is identified using:

        /complaint/?scan_id=<scan_id>

    The complaint is permanently linked to ProductScan.

    Original ProductScanImage objects automatically become
    the evidence associated with the complaint.
    """

    user = request.user

    # --------------------------------------------------------
    # 1. GET SCAN ID FIRST
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 2. BUILD RETURN URL
    # --------------------------------------------------------
    #
    # This URL is used when the user's profile is incomplete.
    #
    # Profile page will redirect the user back here after
    # successfully saving their email/mobile number.
    # --------------------------------------------------------

    complaint_url = (
        reverse('complaint_home')
        + '?'
        + urlencode({
            'scan_id': scan_id
        })
    )

    # --------------------------------------------------------
    # 3. PROFILE COMPLETENESS CHECK
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
    # 4. GET THE SCAN
    # --------------------------------------------------------
    #
    # Normal case:
    #     scan.user == current user
    #
    # Guest-scan case:
    #     scan.user == None
    #
    # A guest scan can be claimed by the authenticated user here.
    # This allows:
    #
    #     Guest Report
    #          ↓
    #     File a Complaint
    #          ↓
    #     Login
    #          ↓
    #     Complaint Form
    #
    # without losing the original scan.
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

        return redirect(
            'dashboard'
        )

    # --------------------------------------------------------
    # 5. CLAIM GUEST SCAN
    # --------------------------------------------------------
    #
    # If the scan was created while the user was logged out,
    # attach it to the authenticated user now.
    #
    # This also means the scan will subsequently appear in
    # the user's scan history.
    # --------------------------------------------------------

    if scan.user is None:

        scan.user = user
        scan.save(
            update_fields=['user']
        )

    # --------------------------------------------------------
    # 6. GET COMPLIANCE REPORT
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
    # 7. COMPLAINTS ONLY FOR NON-COMPLIANT PRODUCTS
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
    # 8. CHECK FOR EXISTING COMPLAINT
    # --------------------------------------------------------
    #
    # A user should not accidentally file multiple complaints
    # for the exact same scan.
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
    # 9. GET OCR DATA
    # --------------------------------------------------------

    extracted = getattr(
        scan,
        'extracted_data',
        None
    )

    # --------------------------------------------------------
    # 10. GET VIOLATIONS
    # --------------------------------------------------------

    violations = list(
        report.violations
        .select_related('rule')
        .all()
    )

    # --------------------------------------------------------
    # 11. BUILD VIOLATION CATEGORY
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
    # 12. BUILD COMPLIANCE REPORT TEXT
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # This is NOT placed into the user's complaint description.
    #
    # It is stored separately in:
    #
    #     complaint.compliance_report
    #
    # so that the report remains available to the complaint
    # without forcing Parakh's findings into the user's own
    # description.
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

        report_sections.append(
            section
        )

    compliance_report_text = '\n\n'.join(
        report_sections
    )

    if not compliance_report_text:

        compliance_report_text = (
            'Parakh identified this product as non-compliant. '
            'Please review the attached product scan images and '
            'the compliance findings.'
        )

    # --------------------------------------------------------
    # 13. PRODUCT NAME
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
    # 14. COMPANY / MANUFACTURER
    # --------------------------------------------------------

    company_name = (
        getattr(
            extracted,
            'manufacturer_name',
            None
        )
        if extracted
        else None
    )

    company_name = (
        company_name.strip()
        if isinstance(company_name, str)
        else company_name
    )

    company_name = (
        company_name
        or 'Manufacturer not detected'
    )

    # --------------------------------------------------------
    # 15. PREPARE PARAKH DATA FOR FORM
    # --------------------------------------------------------
    #
    # The important change here is:
    #
    # description = ''
    #
    # The user gets a clean complaint description field
    # instead of Parakh automatically writing the violation
    # findings into it.
    #
    # The findings are still stored separately in
    # compliance_report when the complaint is submitted.
    # --------------------------------------------------------

    parakh_scan = {
        'scan_id': scan.id,

        'product_name': product_name,

        'company_name': company_name,

        'violation_category': violation_category,

        'subject': 'Non-Compliant Product Report',

        'description': '',

        'compliance_report': compliance_report_text,
    }

    # --------------------------------------------------------
    # 16. HANDLE FORM SUBMISSION
    # --------------------------------------------------------

    if request.method == 'POST':

        form = ComplaintForm(
            request.POST,
            parakh_scan=parakh_scan
        )

        if form.is_valid():

            # ------------------------------------------------
            # PER-USER COMPLAINT NUMBER
            # ------------------------------------------------
            #
            # Example:
            #
            # User A:
            #     Jaanch #1
            #     Jaanch #2
            #
            # User B:
            #     Jaanch #1
            #     Jaanch #2
            #
            # complaint_id remains globally unique internally.
            # ------------------------------------------------

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
            # COMPLAINT NUMBER
            # ------------------------------------------------

            complaint.complaint_number = (
                next_number
            )

            # ------------------------------------------------
            # SECURITY
            # ------------------------------------------------

            complaint.user = user

            # ------------------------------------------------
            # LINK TO ACTUAL PRODUCT SCAN
            # ------------------------------------------------

            complaint.scan = scan

            # ------------------------------------------------
            # USE PARAKH-DERIVED PRODUCT DATA
            # ------------------------------------------------
            #
            # These values are not trusted from POST data.
            # ------------------------------------------------

            complaint.product_name = (
                product_name
            )

            # ------------------------------------------------
            # COMPANY NAME
            # ------------------------------------------------
            #
            # If Parakh detected the company, use its value.
            #
            # If not, use the company entered by the user.
            # ------------------------------------------------

            if company_name == 'Manufacturer not detected':

                complaint.company_name = (
                    form.cleaned_data[
                        'company_name'
                    ]
                )

            else:

                complaint.company_name = (
                    company_name
                )

            # ------------------------------------------------
            # VIOLATION CATEGORY
            # ------------------------------------------------

            complaint.violation_category = (
                violation_category
            )

            # ------------------------------------------------
            # STORE COMPLIANCE FINDINGS SEPARATELY
            # ------------------------------------------------
            #
            # The user's description stays their own text.
            #
            # Parakh's findings are stored here.
            # ------------------------------------------------

            complaint.compliance_report = (
                compliance_report_text
            )

            # ------------------------------------------------
            # INITIAL STATUS
            # ------------------------------------------------

            complaint.status = 'REGISTERED'

            # ------------------------------------------------
            # SAVE
            # ------------------------------------------------

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
    # 17. ORIGINAL PRODUCT IMAGES = EVIDENCE
    # --------------------------------------------------------

    scan_images = scan.images.all()

    # --------------------------------------------------------
    # 18. PAGE CONTEXT
    # --------------------------------------------------------

    context = {
        'form': form,

        'scan': scan,

        'scan_images': scan_images,

        'parakh_scan': parakh_scan,

        'compliance_report': compliance_report_text,

        'violations': violations,

        'company_detected': (
            company_name
            != 'Manufacturer not detected'
        ),
    }

    return render(
        request,
        'complaint.html',
        context
    )


# ============================================================
# COMPLAINT TRACKING DASHBOARD
# ============================================================

@login_required(login_url='login')
def complaint_list(request):
    """
    Complaint tracking dashboard.

    Users can only see complaints submitted by themselves.
    """

    complaints = (
        Complaint.objects
        .filter(
            user=request.user
        )
        .select_related(
            'scan'
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
# COMPLAINT DETAIL
# ============================================================

@login_required(login_url='login')
def complaint_detail(request, complaint_id):
    """
    Display one complaint.

    A complaint can only be viewed by the user who submitted it.
    """

    complaint = get_object_or_404(
        Complaint.objects
        .select_related(
            'scan',
            'user'
        )
        .prefetch_related(
            'scan__images'
        ),
        complaint_id=complaint_id,
        user=request.user
    )

    # --------------------------------------------------------
    # ORIGINAL SCAN IMAGES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CONTEXT
    # --------------------------------------------------------

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