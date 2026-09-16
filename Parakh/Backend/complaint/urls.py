from django.urls import path
from . import views


urlpatterns = [

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
]