# Import views to make them easily accessible
from .auth_views import (
    FacultyRegistrationView,
    verify_email,
    login_view,
    user_profile_view,
    FacultyProfileView
)
from .upload_views import (
    DocumentUploadView,
    user_uploads_list
)
from .admin_views import (
    admin_dashboard_stats,
    admin_users_list,
    admin_user_documents
)

from .analytics_views import (
    faculty_gap_analysis
)

# Define what gets imported with "from .views import *"
__all__ = [
    'FacultyRegistrationView',
    'verify_email',
    'login_view',
    'user_profile_view',
    'FacultyProfileView',
    'DocumentUploadView',
    'user_uploads_list',
    'admin_dashboard_stats',
    'admin_users_list',
    'admin_user_documents',
    'faculty_gap_analysis'
]