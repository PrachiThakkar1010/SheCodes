from django.urls import path
from . import views


urlpatterns = [

    # ========================================================
    # CUSTOMER
    # ========================================================

    path(
        'complaint/',
        views.submit_complaint,
        name='complaint_home'
    ),

    path(
        'submit/',
        views.submit_complaint,
        name='submit_complaint'
    ),

    path(
        'complaint_tracking/',
        views.complaint_list,
        name='complaint_list'
    ),

    path(
        'complaint/<int:complaint_id>/',
        views.complaint_detail,
        name='complaint_detail'
    ),

    # ========================================================
    # COMPANY
    # ========================================================

    path(
        'company/',
        views.company_complaint_list,
        name='company_complaint_list'
    ),

    path(
        'company/<int:complaint_id>/',
        views.company_complaint_detail,
        name='company_complaint_detail'
    ),

    path(
        'company/<int:complaint_id>/response/',
        views.company_initial_response,
        name='company_initial_response'
    ),

    path(
        'company/<int:complaint_id>/verification/',
        views.company_verification,
        name='company_verification'
    ),

    path(
        'company/<int:complaint_id>/complete/',
        views.company_complete_complaint,
        name='company_complete_complaint'
    ),
]