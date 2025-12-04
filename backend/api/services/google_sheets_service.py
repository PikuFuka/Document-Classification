import requests
import logging
import json

logger = logging.getLogger(__name__)

# =============================================================================
#  CONFIG
# =============================================================================

# REPLACE THIS WITH YOUR NEW DEPLOYMENT URL
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxvJJMd8j7reRaSNHbX7yZVMrntSIVW2Ne4hrHnozU3q3NOcnqWvpj53cXk3jviqFUQRQ/exec"

SEMESTER_MAPPING = {
    "first": "1st", "1st": "1st",
    "second": "2nd", "2nd": "2nd"
}

# =============================================================================
#  HELPER FUNCTIONS
# =============================================================================

def map_evaluation_type(raw_type):
    raw_type = (raw_type or "").strip().lower()
    if "supervisor" in raw_type:
        return "supervisor"
    return "student"

def normalize_values(academic_year, semester, evaluation_type):
    academic_year = (academic_year or "").replace("–", "-").replace("—", "-").strip()
    semester = (semester or "").lower().strip()
    semester = SEMESTER_MAPPING.get(semester, "1st")
    evaluation_type = map_evaluation_type(evaluation_type)
    return academic_year, semester, evaluation_type

# =============================================================================
#  EXPORT FUNCTIONS
# =============================================================================

def send_evaluation_to_spreadsheetKRA1_Eval(spreadsheet_id, academic_year, semester, evaluation_type, total_score, drive_link):
    """
    KRA 1A: Student/Supervisor Evaluation
    """
    academic_year, semester, evaluation_type = normalize_values(
        academic_year, semester, evaluation_type
    )

    payload = {
        "action": "kra1a_evaluation",  # ROUTING TAG
        "spreadsheet_id": spreadsheet_id,
        "academic_year": academic_year,
        "semester": semester,
        "evaluation_type": evaluation_type,
        "total_score": total_score,
        "drive_link": drive_link,
    }

    return _send_payload(payload, "KRA 1A")


def send_program_contribution_to_sheet(spreadsheet_id, program_name, program_type, board_reso, academic_year, role, score, drive_link):
    """
    KRA 1B Sender.
    """
    # Double check cleaning of AY to match "2019-2020" format
    if academic_year:
        academic_year = academic_year.replace("A.Y.", "").replace("Academic Year", "").strip()
        academic_year = academic_year.replace("–", "-").replace("—", "-") # Normalize hyphens

    payload = {
        "action": "kra1b_program", 
        "spreadsheet_id": spreadsheet_id,
        "program_name": program_name,
        "program_type": program_type,
        "board_reso": board_reso,
        "academic_year": academic_year, # Now strictly "2020-2021"
        "role": role,                   # Sent as "Contributor" or "Lead"
        "score": score,
        "drive_link": drive_link        # Passed from document_processing_service
    }

    return _send_payload(payload, "KRA 1B")


def send_research_to_sheet(spreadsheet_id, title, research_type, journal, reviewer, indexing, date_published, score, drive_link, author_mode, contribution=0):
    """
    Sends KRA 2A Research Data.
    author_mode: 'sole' (Row 12) or 'co' (Row 37)
    """
    payload = {
        "action": "kra2a_research", 
        "spreadsheet_id": spreadsheet_id,
        "author_mode": author_mode, # "sole" or "co"
        "title": title,
        "research_type": research_type,
        "journal": journal,
        "reviewer": reviewer,
        "indexing": indexing,
        "date_published": date_published,
        "contribution": contribution, # Sent even if 0/Sole (Script ignores it for Sole)
        "score": score,
        "drive_link": drive_link
    }

    return _send_payload(payload, f"KRA 2A ({author_mode})")

def _send_payload(payload, context_name):
    """Internal helper to send POST request."""
    try:
        response = requests.post(APPS_SCRIPT_URL, json=payload, timeout=30)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("status") == "success":
                    logger.info(f"{context_name} Spreadsheet updated successfully.")
                    return True
                else:
                    logger.warning(f"{context_name} Spreadsheet update failed: {data}")
            except ValueError:
                logger.error("Invalid JSON response from Apps Script")
        else:
            logger.error(f"Failed to update spreadsheet, status code: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending {context_name} data to spreadsheet: {e}")
        
    return False

# Function for user creation (kept from your original code)
def create_user_google_sheet(user_data):
    # This uses a DIFFERENT script URL for creation, keep as is or update if needed
    creation_script_url = "https://script.google.com/macros/s/AKfycbwJSozWyHrd6JaepnU7u0A-4diwFTgI3oJkhdNJAds-_QFgR1RKkn8-9sDj-TTdBjgUvw/exec"
    
    data = {
        'first_name': user_data.get('first_name', ''),
        'middle_name': user_data.get('middle_name', ''),
        'last_name': user_data.get('last_name', ''),
        'degree_name': user_data.get('degree_name', ''),
        'hei_name': user_data.get('hei_name', ''),
        'year_graduated': user_data.get('year_graduated', ''),
        'faculty_rank': user_data.get('faculty_rank', ''),
        'mode_of_appointment': user_data.get('mode_of_appointment', 'NBC 461'),
        'date_of_appointment': str(user_data.get('date_of_appointment', '')),
        'suc_name': user_data.get('suc_name', ''),
        'campus': user_data.get('campus', ''),
        'address': user_data.get('address', ''),
        'email': user_data.get('email', ''),
    }
    
    try:
        response = requests.post(creation_script_url, json=data, timeout=30)
        if response.status_code == 200:
            try:
                response_data = response.json()
                if response_data.get('status') == 'success':
                    return response_data.get('url', '')
            except ValueError:
                pass
    except Exception as e:
        logger.error(f"Error creating user Google Sheet: {e}")
    
    return f"https://docs.google.com/spreadsheets/d/mock_user_{user_data.get('email', 'unknown')}/edit"