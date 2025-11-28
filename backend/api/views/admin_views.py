from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
User = get_user_model()

from ..models import FacultyProfile, DocumentUpload
from ..serializers import (
    AdminUserSerializer
)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_dashboard_stats(request):
    if not request.user.is_staff:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

    total_faculty = User.objects.filter(is_staff=False).count()
    total_documents = DocumentUpload.objects.count()

    return Response({
        'total_faculty': total_faculty,
        'total_documents': total_documents
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_users_list(request):
    if not request.user.is_staff:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

    # Get all faculty users with their profile
    faculty_users = User.objects.filter(is_staff=False).select_related('faculty_profile')
    serializer = AdminUserSerializer(faculty_users, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_user_documents(request, user_id):
    if not request.user.is_staff:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

    try:
        user = User.objects.get(id=user_id, is_staff=False)
        uploads = DocumentUpload.objects.filter(user=user).order_by('-created_at')

        # Format the response to include user info and their uploads
        user_data = {
            'user_id': user.id,
            'user_email': user.email,
            'user_name': f"{user.first_name} {user.last_name}",
            'user_sheet_url': user.faculty_profile.sheet_url if hasattr(user, 'faculty_profile') and user.faculty_profile.sheet_url else None,
            'uploads': [
                {
                    'id': upload.id,
                    'google_drive_link': upload.google_drive_link,
                    'status': upload.status,
                    'created_at': upload.created_at,
                    'google_sheet_link': upload.google_sheet_link
                }
                for upload in uploads
            ]
        }
        return Response(user_data)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)