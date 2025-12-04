# backend/api/views.py

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.services.analysis_engine import analyze_faculty_performance

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def faculty_gap_analysis(request):
    """
    Endpoint: /api/analytics/gap-analysis/
    Returns:
    - Raw Scores vs Caps
    - Weighted Scores & Promotion Projection
    - Strategic Recommendations
    """
    try:
        if not hasattr(request.user, 'faculty_profile'):
            return Response({"error": "Profile incomplete."}, status=400)
            
        profile = request.user.faculty_profile
        
        if not profile.sheet_url:
            return Response({"error": "No Google Sheet linked."}, status=400)
            
        # Get Rank (Default to Instructor I if missing)
        current_rank = profile.faculty_rank if profile.faculty_rank else "Instructor I"
        
        # Run Engine with Rank
        data = analyze_faculty_performance(profile.sheet_url, current_rank)
        
        return Response(data)
        
    except Exception as e:
        print(f"Gap Analysis Error: {e}")
        return Response({"error": "Analysis failed."}, status=500)