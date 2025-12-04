from django.urls import path
from . import views

urlpatterns = [
    # Auth URLs
    path('auth/faculty-register/', views.FacultyRegistrationView.as_view(), name='faculty-register'),
    path('auth/verify-email/', views.verify_email, name='verify-email'),
    path('auth/login/', views.login_view, name='login'),
    path('auth/profile/', views.user_profile_view, name='user-profile'),
    path('faculty/profile/', views.FacultyProfileView.as_view(), name='faculty-profile'),
    path('analytics/gap-analysis/', views.faculty_gap_analysis, name='gap-analysis'),

    # Upload URLs
    path('uploads/', views.DocumentUploadView.as_view(), name='document-uploads'),
    path('user/uploads/', views.user_uploads_list, name='user-uploads-list'),

    # Admin URLs
    path('admin/stats/', views.admin_dashboard_stats, name='admin-stats'),
    path('admin/users/', views.admin_users_list, name='admin-users-list'),
    path('admin/user/<int:user_id>/documents/', views.admin_user_documents, name='admin-user-documents'),
]