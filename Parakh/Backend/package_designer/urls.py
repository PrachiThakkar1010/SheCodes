from django.urls import path
from . import views

urlpatterns = [
    path('', views.studio_view, name='studio'),
    path('<int:project_id>/', views.studio_view, name='studio_project'),
    path('api/calculate-pdp/', views.api_calculate_pdp, name='api_calculate_pdp'),
    path('api/generate-spec/', views.api_generate_spec, name='api_generate_spec'),
    path('api/chat/', views.api_chat_assistant, name='api_chat_assistant'),
    path('api/upload-asset/', views.api_upload_asset, name='api_upload_asset'),
    path('spec-sheet/', views.spec_sheet_view, name='spec_sheet_default'),
    path('spec-sheet/<int:project_id>/', views.spec_sheet_view, name='spec_sheet'),
]

