from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('scan/', views.scan_view, name='scan'),
    path('result/<int:scan_id>/', views.result_view, name='result'),
    path('result/<int:scan_id>/json/', views.result_json_view, name='result_json'),
    path('rules/', views.rules_view, name='rules'),
    # path('login/'),
]