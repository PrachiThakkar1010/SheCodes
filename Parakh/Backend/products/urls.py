from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('scan/', views.scan_view, name='scan'),
    path('result/<int:scan_id>/', views.result_view, name='result'),
    path('history/', views.history_view, name='history'),
    path('rules/', views.rules_view, name='rules'),
]