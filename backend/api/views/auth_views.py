from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import authenticate
from api.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny

from ..models import FacultyProfile
from ..serializers import (
    FacultyRegistrationSerializer,
    UserSerializer,
    EmailVerificationSerializer,
    FacultyProfileSerializer
)
from ..services.email_service import generate_verification_token, send_verification_email
from ..services.google_sheets_service import create_user_google_sheet

class FacultyRegistrationView(generics.CreateAPIView):
    serializer_class = FacultyRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Create faculty profile from request data
        profile_data = {
            'user': user,
            'degree_name': request.data.get('degree_name', ''),
            'hei_name': request.data.get('hei_name', ''),
            'year_graduated': request.data.get('year_graduated', 2000),
            'faculty_rank': request.data.get('faculty_rank', ''),
            'mode_of_appointment': request.data.get('mode_of_appointment', 'NBC 461'),
            'date_of_appointment': request.data.get('date_of_appointment', timezone.now().date()),
            'suc_name': request.data.get('suc_name', ''),
            'campus': request.data.get('campus', ''),
            'address': request.data.get('address', ''),
        }

        # Create Google Sheet for the user using the provided script
        user_sheet_url = create_user_google_sheet({
            'first_name': request.data.get('first_name', ''),
            'middle_name': request.data.get('middle_name', ''),
            'last_name': request.data.get('last_name', ''),
            'degree_name': request.data.get('degree_name', ''),
            'hei_name': request.data.get('hei_name', ''),
            'year_graduated': request.data.get('year_graduated', ''),
            'faculty_rank': request.data.get('faculty_rank', ''),
            'mode_of_appointment': request.data.get('mode_of_appointment', 'NBC 461'),
            'date_of_appointment': str(request.data.get('date_of_appointment', '')),
            'suc_name': request.data.get('suc_name', ''),
            'campus': request.data.get('campus', ''),
            'address': request.data.get('address', ''),
            'email': request.data.get('email', ''),
        })

        profile_data['sheet_url'] = user_sheet_url
        FacultyProfile.objects.create(**profile_data)

        # Generate verification token
        verification_token = generate_verification_token()
        user.verification_token = verification_token
        user.save()

        # Send verification email
        send_verification_email(user.email, verification_token)

        headers = self.get_success_headers(serializer.data)
        return Response({
            'user_id': user.id,
            'email': user.email,
            'message': 'Registration successful. Please check your email for verification.'
        }, status=status.HTTP_201_CREATED, headers=headers)

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def verify_email(request):
    token = request.GET.get('token') or request.data.get('token')
    if not token:
        return Response({'error': 'Missing token'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(verification_token=token)
    except User.DoesNotExist:
        # Check if user is already verified
        already_verified = User.objects.filter(email_verified=True, verification_token__isnull=True).exists()
        if already_verified:
            return Response({'message': 'Email already verified!'}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid verification token'}, status=status.HTTP_400_BAD_REQUEST)

    user.email_verified = True
    user.verification_token = None
    user.save()
    return Response({'message': 'Email verified successfully!'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get('email')
    password = request.data.get('password')

    user = authenticate(request, email=email, password=password)
    print("Authenticated user:", user)

    if user:
        if not user.email_verified:
            return Response({'error': 'Please verify your email first'}, status=status.HTTP_400_BAD_REQUEST)

        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.id,
            'email': user.email,
            'is_staff': user.is_staff,
            'email_verified': user.email_verified
        })

    return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile_view(request):
    serializer = UserSerializer(request.user)
    return Response(serializer.data)

class FacultyProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = FacultyProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        profile, created = FacultyProfile.objects.get_or_create(user=self.request.user)
        return profile