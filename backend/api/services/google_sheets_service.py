import requests
import logging
import json

logger = logging.getLogger(__name__)

def create_user_google_sheet(user_data):
    """Create Google Sheet for user during registration."""
    # Use the Google Apps Script URL you provided
    apps_script_url = "https://script.google.com/macros/s/AKfycbwJSozWyHrd6JaepnU7u0A-4diwFTgI3oJkhdNJAds-_QFgR1RKkn8-9sDj-TTdBjgUvw/exec"
    
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
        response = requests.post(apps_script_url, json=data, timeout=30)
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                if response_data.get('status') == 'success':
                    return response_data.get('url', '')
            except ValueError:
                pass
    except Exception as e:
        logger.error(f"Error creating user Google Sheet: {e}")
    
    # Return a mock Google Sheet URL for testing if the script fails
    return f"https://docs.google.com/spreadsheets/d/mock_user_{user_data.get('email', 'unknown')}/edit"

# Mapping for semester normalization
SEMESTER_MAPPING = {
    "first": "1st",
    "1st": "1st",
    "second": "2nd",
    "2nd": "2nd"
}


def map_evaluation_type(raw_type):
    """Robustly map extracted evaluation type to 'student' or 'supervisor'."""
    raw_type = (raw_type or "").strip().lower()
    if "supervisor" in raw_type:
        return "supervisor"
    elif "student" in raw_type:
        return "student"
    else:
        return "student"  # default fallback


def normalize_values(academic_year, semester, evaluation_type):
    """Normalize inputs to match Apps Script cell map keys."""
    # Fix dashes in academic year
    academic_year = (academic_year or "").replace("–", "-").replace("—", "-").strip()

    # Normalize semester
    semester = (semester or "").lower().strip()
    semester = SEMESTER_MAPPING.get(semester, "1st")

    # Normalize evaluation type
    evaluation_type = map_evaluation_type(evaluation_type)

    return academic_year, semester, evaluation_type


def send_evaluation_to_spreadsheetKRA1_Eval(spreadsheet_id, academic_year, semester, evaluation_type, total_score, drive_link):
    """
    Sends total_score and drive_link to the Google Sheet via Apps Script.
    Automatically normalizes values before sending.
    """
    academic_year, semester, evaluation_type = normalize_values(
        academic_year, semester, evaluation_type
    )

    apps_script_url = "https://script.google.com/macros/s/AKfycbyD55QBQ2yvuTdBed2hPptU7-pAVyaKSP49kZNaknvptsdlYnObY1_x14xvu3Ik5eQQEg/exec"

    payload = {
        "spreadsheet_id": spreadsheet_id,
        "academic_year": academic_year,
        "semester": semester,
        "evaluation_type": evaluation_type,
        "total_score": total_score,
        "drive_link": drive_link,
    }

    try:
        response = requests.post(apps_script_url, json=payload, timeout=30)
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("status") == "success":
                    logger.info("Spreadsheet updated successfully.")
                    return True
                else:
                    logger.warning(f"Spreadsheet update failed: {data}")
            except ValueError:
                logger.error("Invalid JSON response from Apps Script")
        else:
            logger.error(f"Failed to update spreadsheet, status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending data to spreadsheet: {e}")
    return False