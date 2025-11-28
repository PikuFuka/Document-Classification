# api/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import json # Import json to handle field validation if needed

class User(AbstractUser):
    USER_TYPE_CHOICES = [
        ('faculty', 'Faculty'),
        ('admin', 'Admin'),
    ]

    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)
    email_verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True)
    middle_initial = models.CharField(max_length=3, blank=True)
    last_name = models.CharField(max_length=100, blank=True)

class FacultyProfile(models.Model):
    FACULTY_RANK_CHOICES = [
        ('Instructor I', 'Instructor I'),
        ('Instructor II', 'Instructor II'),
        ('Instructor III', 'Instructor III'),
        ('Assistant Professor I', 'Assistant Professor I'),
        ('Assistant Professor II', 'Assistant Professor II'),
        ('Assistant Professor III', 'Assistant Professor III'),
        ('Assistant Professor IV', 'Assistant Professor IV'),
        ('Assistant Professor V', 'Assistant Professor V'),
        ('Associate Professor I', 'Associate Professor I'),
        ('Associate Professor II', 'Associate Professor II'),
        ('Associate Professor III', 'Associate Professor III'),
        ('Associate Professor IV', 'Associate Professor IV'),
        ('Associate Professor V', 'Associate Professor V'),
        ('Professor I', 'Professor I'),
        ('Professor II', 'Professor II'),
        ('Professor III', 'Professor III'),
        ('Professor IV', 'Professor IV'),
        ('Professor V', 'Professor V'),
        ('Professor VI', 'Professor VI'),
        ('College/University Professor', 'College/University Professor'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='faculty_profile')
    degree_name = models.CharField(max_length=200)
    hei_name = models.CharField(max_length=200)
    year_graduated = models.IntegerField()
    faculty_rank = models.CharField(max_length=50, choices=FACULTY_RANK_CHOICES)
    mode_of_appointment = models.CharField(max_length=50, default='NBC 461')
    date_of_appointment = models.DateField()
    suc_name = models.CharField(max_length=200)
    campus = models.CharField(max_length=200)
    address = models.TextField()
    sheet_url = models.URLField(blank=True, null=True) 

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} - {self.faculty_rank}"

class DocumentUpload(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='document_uploads')
    google_drive_link = models.URLField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    google_sheet_link = models.URLField(blank=True, null=True)
    # Evaluation and classification results
    equivalent_percentage = models.CharField(max_length=20, blank=True, null=True)
    total_score = models.FloatField(blank=True, null=True)
    primary_kra = models.CharField(max_length=255, blank=True, null=True)
    kra_confidence = models.FloatField(blank=True, null=True)
    criteria = models.CharField(max_length=255, blank=True, null=True)
    sub_criteria = models.CharField(max_length=255, blank=True, null=True)
    explanation = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    # Extraction details
    page_count = models.IntegerField(blank=True, null=True)
    extracted_text_preview = models.TextField(blank=True, null=True)
    source_filename = models.CharField(max_length=255, blank=True, null=True)
    extracted_json = models.JSONField(default=list, blank=True) 

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Upload {self.id} by {self.user.username}"

    def get_extracted_items(self):
        """Helper method to safely get the extracted items list."""
        return self.extracted_json if isinstance(self.extracted_json, list) else []