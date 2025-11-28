from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User

from ..models import DocumentUpload
from ..serializers import (
    DocumentUploadSerializer,
    UserSerializer
)
from ..services.document_processing_service import process_document_upload

class DocumentUploadView(generics.ListCreateAPIView):
    serializer_class = DocumentUploadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DocumentUpload.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # Save the upload record first
        upload = serializer.save(user=self.request.user)
        try:
            process_document_upload(upload)
        except Exception as e:
            print(f"Error processing upload {upload.id}: {e}")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_uploads_list(request):
    uploads = DocumentUpload.objects.filter(user=request.user).order_by('-created_at')
    serializer = DocumentUploadSerializer(uploads, many=True)
    return Response(serializer.data)