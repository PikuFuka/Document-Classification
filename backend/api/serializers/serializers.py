from rest_framework import serializers
from api.models import User, FacultyProfile, DocumentUpload


class FacultyRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            is_staff=False
        )
        return user


class FacultyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacultyProfile
        fields = '__all__'
        read_only_fields = ['user']

class DocumentUploadSerializer(serializers.ModelSerializer):
    success = serializers.SerializerMethodField()

    class Meta:
        model = DocumentUpload
        fields = [
            'id', 'google_drive_link', 'status', 'created_at', 'google_sheet_link',
            'equivalent_percentage', 'total_score',
            'primary_kra', 'kra_confidence', 'criteria', 'sub_criteria', 'explanation',
            'error_message', 'page_count', 'extracted_text_preview', 'source_filename',
            'extracted_json', # Add this line to include the field in the API response
            'success'
        ]
        read_only_fields = [
            'user', 'status', 'created_at', 'google_sheet_link',
            'equivalent_percentage', 'total_score',
            'primary_kra', 'kra_confidence', 'criteria', 'sub_criteria', 'explanation',
            'error_message', 'page_count', 'extracted_text_preview', 'source_filename'
            # 'extracted_json' is also read-only, you might want to add it here if it's never set via API input
        ]

    def get_success(self, obj):
        return obj.status == 'completed' and (
            obj.equivalent_percentage is not None or obj.total_score is not None or obj.primary_kra is not None
        )

class AdminUserSerializer(serializers.ModelSerializer):
    faculty_profile = FacultyProfileSerializer(read_only=True)
    total_uploads = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'faculty_profile', 'date_joined', 'total_uploads']

    def get_total_uploads(self, obj):
        return obj.document_uploads.count()

class UserSerializer(serializers.ModelSerializer):
    faculty_profile = FacultyProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'faculty_profile', 'is_staff', 'email_verified']

class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=100)
