from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, FacultyProfile, DocumentUpload

class FacultyProfileInline(admin.StackedInline):
    model = FacultyProfile
    can_delete = False
    verbose_name_plural = 'Faculty Profile'

class UserAdmin(BaseUserAdmin):
    inlines = [FacultyProfileInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'user_type', 'email_verified')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'user_type', 'email_verified')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('user_type', 'email_verified', 'verification_token', 'middle_initial')}),
    )

admin.site.register(User, UserAdmin)

@admin.register(DocumentUpload)
class DocumentUploadAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'google_drive_link', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'user__email', 'google_drive_link')
    readonly_fields = ('created_at',)
