from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .models import Complaint
from .forms import ComplaintForm


@login_required
def submit_complaint(request):

    # Get PARAKH scan information from session if available
    parakh_scan = request.session.get(
        'parakh_scan',
        {}
    )

    if request.method == 'POST':

        form = ComplaintForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            complaint = form.save(commit=False)

            # ------------------------------------------------
            # Attach the logged-in user to the complaint
            # ------------------------------------------------
            complaint.user = request.user

            # ------------------------------------------------
            # Automatically attach PARAKH scan information
            # ------------------------------------------------
            if parakh_scan:

                complaint.product_name = parakh_scan.get(
                    'product_name',
                    complaint.product_name
                )

                complaint.company_name = parakh_scan.get(
                    'company_name',
                    complaint.company_name
                )

                complaint.violation_category = parakh_scan.get(
                    'violation_category',
                    complaint.violation_category
                )

                complaint.compliance_report = parakh_scan.get(
                    'compliance_report',
                    ''
                )

            # Save complaint
            complaint.save()

            messages.success(
                request,
                f'Complaint #{complaint.complaint_id} submitted successfully!'
            )

            return redirect('complaint_list')

    else:

        form = ComplaintForm()

    return render(
        request,
        'complaint.html',
        {
            'form': form,
            'parakh_scan': parakh_scan,
        }
    )


@login_required
def complaint_list(request):

    # Show only complaints submitted by the logged-in user
    complaints = Complaint.objects.filter(
        user=request.user
    ).order_by('-submitted')

    return render(
        request,
        'complaint_tracking.html',
        {
            'complaints': complaints,
        }
    )


@login_required
def complaint_detail(request, complaint_id):

    complaint = get_object_or_404(
        Complaint,
        complaint_id=complaint_id,
        user=request.user
    )

    return render(
        request,
        'complaint_detail.html',
        {
            'complaint': complaint,
        }
    )