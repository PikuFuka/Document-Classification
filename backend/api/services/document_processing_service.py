import os
import uuid
import io
import pytesseract
import logging
import json
import fitz  # PyMuPDF
from datetime import datetime
from PIL import Image, ImageFilter, ImageOps
from django.conf import settings
from googleapiclient.discovery import build
from google.oauth2 import service_account  
from googleapiclient.http import MediaIoBaseDownload

from docx import Document
from .ml_processing_service import classify_document
from .google_sheets_service import send_evaluation_to_spreadsheetKRA1_Eval, normalize_values, send_research_to_sheet, send_program_contribution_to_sheet
from .extraction_strategies import route_extraction
from .scoring_rules import calculate_score, SCORING_RULES

logger = logging.getLogger(__name__)

# Scopes required for the Service Account
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    """Authenticates using Service Account Credentials."""
    try:
        if not hasattr(settings, 'GOOGLE_SERVICE_ACCOUNT_FILE'):
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE not found in settings.")
            
        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_FILE, 
            scopes=SCOPES
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to authenticate with Service Account: {e}")
        raise e

def extract_text_from_drive(drive_link):
    """
    Returns a list of file info dicts.
    Format: [{'text': str, 'page_count': int, 'file_name': str, 'file_id': str}, ...]
    """
    try:
        if 'drive.google.com' not in drive_link:
            raise ValueError("Invalid Google Drive link")

        file_id, folder_id = None, None

        if '/folders/' in drive_link:
            folder_id = drive_link.split('/folders/')[1].split('?')[0].split('/')[0]
        elif '/file/d/' in drive_link:
            file_id = drive_link.split('/file/d/')[1].split('/')[0]
        elif '/d/' in drive_link:
            file_id = drive_link.split('/d/')[1].split('/')[0]
        elif 'id=' in drive_link:
            possible_id = drive_link.split('id=')[1].split('&')[0]
            file_id = possible_id
        else:
            raise ValueError("Unsupported Google Drive link format")

        if folder_id:
            print(f"Detected folder ID: {folder_id}")
            return extract_files_from_drive_folder(folder_id)
        else:
            print(f"Detected file ID: {file_id}")
            file_info = extract_text_from_drive_file(file_id)
            return [file_info] if file_info else []

    except Exception as e:
        print(f"Error parsing Google Drive link: {e}")
        return []


def extract_text_from_drive_file(file_id):
    """Extract text from a single file and return file info dict."""
    # Use the new helper function for auth
    try:
        service = get_drive_service()
    except Exception as auth_error:
        print(f"Authentication failed: {auth_error}")
        return None

    try:
        file_metadata = service.files().get(fileId=file_id, fields="name, mimeType").execute()
        file_name = file_metadata['name']
        mime_type = file_metadata['mimeType']

        print(f"Processing file: {file_name} (MIME: {mime_type})")

        supported_mimes = {
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
            'image/jpeg',
            'image/png',
            'image/tiff',
            'image/gif',
            'image/bmp',
        }

        if mime_type not in supported_mimes:
            print(f"Unsupported file type: {mime_type}")
            return None

        # --- UPDATED DOWNLOAD LOGIC ---
        # Using MediaIoBaseDownload is more robust than request.execute() for files
        request = service.files().get_media(fileId=file_id)
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        temp_path = os.path.join(settings.MEDIA_ROOT, f"{uuid.uuid4()}_{file_name}")

        with io.FileIO(temp_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                # Optional: print(f"Download {int(status.progress() * 100)}%.")
        # ------------------------------

        # Extract text and page count based on file type
        text = ""
        page_count = 0
        
        try:
            if mime_type == 'application/pdf':
                text, page_count = extract_text_from_pdf_with_ocr(temp_path)
            elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                text = extract_text_from_word(temp_path)
                page_count = 0
            elif mime_type.startswith('image/'):
                text = extract_text_from_image(temp_path)
                page_count = 1
            else:
                text, page_count = "", 0
        except Exception as extract_error:
            print(f"Error during text extraction: {extract_error}")
            text, page_count = "", 0

        # Clean up temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as cleanup_error:
                print(f"Warning: Could not remove temp file: {cleanup_error}")

        return {
            'text': text,
            'page_count': page_count,
            'file_name': file_name,
            'file_id': file_id
        }

    except Exception as e:
        print(f"Error processing file {file_id}: {e}")
        # traceback.print_exc() # detailed logging
        return None


def extract_files_from_drive_folder(folder_id):
    """Extract files from folder and return list of file info dicts."""
    try:
        # Use the new helper function for auth
        service = get_drive_service()

        query = (
            f"'{folder_id}' in parents and "
            f"("
            f"mimeType = 'application/pdf' or "
            f"mimeType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' or "
            f"mimeType = 'application/msword' or "
            f"mimeType = 'image/jpeg' or "
            f"mimeType = 'image/png' or "
            f"mimeType = 'image/tiff' or "
            f"mimeType = 'image/gif' or "
            f"mimeType = 'image/bmp'"
            f") and trashed = false"
        )

        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType)"
        ).execute()
        files = results.get('files', [])

        if not files:
            print("No supported files found in folder.")
            return []

        file_info_list = []
        for idx, file in enumerate(files):
            print(f"Processing {idx+1}/{len(files)}: {file['name']} ({file['mimeType']})")
            file_info = extract_text_from_drive_file(file['id'])
            if file_info:
                file_info_list.append(file_info)

        return file_info_list

    except Exception as e:
        print(f"Error processing folder {folder_id}: {e}")
        # traceback.print_exc()
        return []


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Preprocess image for better OCR results."""
    try:
        gray = img.convert("L")
        gray = ImageOps.autocontrast(gray)
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
        threshold = gray.point(lambda x: 0 if x < 160 else 255, "1")
        return threshold
    except Exception as e:
        print(f"Preprocessing error: {e}, using original image")
        return img


def extract_text_from_pdf_with_ocr(file_path):
    """
    Extract text from PDF. Returns tuple (text, page_count).
    """
    try:
        doc = fitz.open(file_path)
        text = ""
        
        for page in doc:
            text += page.get_text()

        page_count = doc.page_count
        doc.close()

        # If no selectable text, use OCR
        if not text.strip():
            print("No text found. Using OCR...")
            text = extract_text_with_ocr(file_path)

        return text, page_count

    except Exception as e:
        print(f"PDF extraction error: {e}")
        import traceback
        traceback.print_exc()
        return "", 0


def extract_text_with_ocr(file_path):
    """Extract text from PDF using OCR. Returns string."""
    text = ""
    
    try:
        doc = fitz.open(file_path)
        
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            
            # Preprocess for better OCR
            processed = preprocess_for_ocr(img)
            page_text = pytesseract.image_to_string(processed, lang="eng")
            text += page_text + "\n"
        
        doc.close()
        
    except Exception as e:
        print(f"OCR error: {e}")
        import traceback
        traceback.print_exc()
    
    return text


def extract_text_from_word(file_path):
    """Extract text from Word document. Returns string."""
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Error reading .docx file: {e}")
        import traceback
        traceback.print_exc()
        return ""


def extract_text_from_image(file_path):
    """Extract text from image file using OCR. Returns string."""
    try:
        img = Image.open(file_path)
        
        # Preprocess for better OCR
        processed = preprocess_for_ocr(img)
        text = pytesseract.image_to_string(processed, lang="eng")
        
        return text
        
    except Exception as e:
        print(f"Error processing image file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return ""

def map_classification_to_evidence_type(classification_result):
    pk = classification_result.get("primary_kra")
    cr = classification_result.get("criterion")
    sc = classification_result.get("sub_criterion")

    if pk == "2" and cr == "A" and sc.startswith("1."):
        return "kra2a_research"

    mapping = {
        ("1", "A", "1.1"): "kra1a_evaluation",
        ("1", "A", "1.2"): "kra1a_evaluation",

        ("1", "B", "1.1"): "kra1b_sole",
        ("1", "B", "1.2"): "kra1b_co",
        ("1", "B", "1.3"): "kra1b_sole",
        ("1", "B", "1.4"): "kra1b_co",
        ("1", "B", "1.5"): "kra1b_sole",
        ("1", "B", "1.6"): "kra1b_co",
        ("1", "B", "1.7"): "kra1b_co",
        ("1", "B", "1.8"): "kra1b_co",

        ("1", "B", "2.1"): "kra1b_program_leadAndContri",
        ("1", "B", "2.2"): "kra1b_program_leadAndContri",

        ("1", "C", "1.1"): "kra1c_adviser",
        ("1", "C", "1.2"): "kra1c_panel",   
        ("1", "C", "2"): "kra1c_mentor",   

        ("2", "A", "2.1"): "kra2a_research_to_project_lead",
        ("2", "A", "2.2"): "kra2a_research_to_project_contributor",
        ("2", "A", "3.1"): "kra2a_citation_local",
        ("2", "A", "3.2"): "kra2a_citation_international",

        ("2", "B", "1.1.1"): "kra2b_invention",
        ("2", "B", "1.1.2"): "kra2b_utility",
        ("2", "B", "1.1.3"): "kra2b_industrial",
        ("2", "B", "1.2.1"): "kra2b_commercialized",
        ("2", "B", "1.2.2"): "kra2b_commercialized",
        ("2", "B", "2.1.1"): "kra2b_new_software",
        ("2", "B", "2.1.2"): "kra2b_updated_software",
        ("2", "B", "2.2.1"): "kra2b_biological_sole",
        ("2", "B", "2.2.2"): "kra2b_biological_co",

        ("2", "C", "1.1.1"): "kra2c_performing_art",
        ("2", "C", "1.1.2"): "kra2c_performing_art",
        ("2", "C", "1.2"): "kra2c_exhibition",
        ("2", "C", "1.3"): "kra2c_juried_design",
        ("2", "C", "1.4.1"): "kra2c_literary",
        ("2", "C", "1.4.2"): "kra2c_literary",
        ("2", "C", "1.4.3"): "kra2c_literary",
        ("2", "C", "1.4.4"): "kra2c_literary",
    }

    ev_type = mapping.get((pk, cr, sc))    
    return ev_type


def _process_kra1a_evaluation(text, classification_result, upload, extracted_items):
    """Process KRA 1A evaluation results."""
    info = extracted_items[0] if extracted_items else {}
    upload.total_score = info.get("total_score") or 0
    upload.equivalent_percentage = info.get("equivalent_percentage")
    return extracted_items

def _process_kra1c_services(text, classification_result, upload, extracted_items, evidence_type):
    """Process KRA 1C Adviser/Panel services results."""
    pass

def _process_kra1b_sole(text, classification_result, upload, extracted_items):
    """Process KRA 1B Sole Instructional Materials."""
    pass # Implement standard scoring loop

def _process_kra1b_co(text, classification_result, upload, extracted_items):
    """Process KRA 1B Co Instructional Materials."""
    pass # Implement standard scoring loop

def _process_kra1b_program_leadAndContri(text, classification_result, upload, extracted_items):
    if not extracted_items:
        return []

    base = extracted_items[0]
    sub_crit = str(classification_result.get("sub_criterion", "")).strip()
    
    final_role = "Contributor"
    final_points = 5
    
    if sub_crit == "2.1":
        final_role = "Lead"
        final_points = 10
    elif sub_crit == "2.2":
        final_role = "Contributor"
        final_points = 5
    else:
        raw_role = base.get("role", "Contributor")
        if raw_role.lower() == "lead":
            final_role = "Lead"
            final_points = 10

    upload.total_score = final_points

    processed_item = {
        "title": base["program_name"], 
        "description": f"{base['program_type']}. {base['board_resolution']}",
        "role": final_role, 
        "points": final_points,
        "evidence_type": "kra1b_program_leadAndContri",
        "auto_generated": True,
        
        "extracted_raw": {
            "program_name": base["program_name"],
            "program_type": base["program_type"],
            "board_resolution": base["board_resolution"],
            "academic_year": base["academic_year"],
            "role": final_role
        }
    }

    return [processed_item]

def _process_kra2a_research(text, classification_result, upload, extracted_items):
    """
    Unified Processor for KRA 2A (Research).
    STRICTLY determines Type based on Sub-criterion code.
    """
    if not extracted_items: return []
    item = extracted_items[0]
    
    # 1. Get the Sub-Criterion Code
    sub_crit = str(classification_result.get("sub_criterion", "")).strip()
    
    # 2. STRICT TYPE MAPPING (The Fix)
    # This dictionary maps the ML Code -> Exact String required by Google Sheets
    STRICT_TYPE_MAP = {
        "1.1": "Book",
        "1.2": "Book",
        "1.3": "Journal Article",
        "1.4": "Journal Article",
        "1.5": "Book Chapter",
        "1.6": "Book Chapter",
        "1.7": "Monograph",
        "1.8": "Monograph",
        "1.9": "Other Peer-Reviewed Output"
    }
    
    # Force the type. If code is unknown/missing, default to "Journal Article" (Safe fallback)
    # We DO NOT look at item['type_hint'] from the LLM anymore.
    final_research_type = STRICT_TYPE_MAP.get(sub_crit, "Journal Article")

    # 3. Determine Mode (Sole vs Co) logic... (Keep existing logic)
    extracted_contrib = item.get("contribution", 0)
    
    SOLE_CODES = ["1.1", "1.3", "1.5", "1.7"]
    CO_CODES   = ["1.2", "1.4", "1.6", "1.8"]
    
    if sub_crit in SOLE_CODES:
        mode = "sole"
        extracted_contrib = 100
    elif sub_crit in CO_CODES:
        mode = "co"
    elif sub_crit == "1.9":
        # 1.9 is flexible: Sole if ~100%, Co if less
        mode = "sole" if extracted_contrib >= 99 else "co"
    else:
        mode = "sole" if extracted_contrib == 100 else "co"

    # 4. Calculate Score (Keep existing logic)
    BASE_SCORES = {
        "1.1": 100, "1.3": 50, "1.5": 35, "1.7": 100,
        "1.2": 100, "1.4": 50, "1.6": 35, "1.8": 100,
        "1.9": 10
    }
    base_points = BASE_SCORES.get(sub_crit, 35)

    if mode == "sole":
        final_score = base_points
        role_display = "Sole Author"
        extracted_contrib = 100
    else:
        final_score = base_points * (extracted_contrib / 100.0)
        role_display = f"Co-Author ({extracted_contrib}%)"
    
    final_score = round(final_score, 2)
    upload.total_score = final_score
    
    # 5. Save Data (Including the FORCED Type)
    raw_data = item.copy()
    raw_data['author_mode'] = mode
    raw_data['contribution'] = extracted_contrib
    
    # CRITICAL: Save the forced type here so the Sheet Export uses it
    raw_data['final_research_type'] = final_research_type 

    processed_item = {
        "title": item["title"],
        "description": f"{role_display}. Type: {final_research_type}. Code: {sub_crit}",
        "role": role_display,
        "points": final_score,
        "evidence_type": "kra2a_research",
        "auto_generated": True,
        "extracted_raw": raw_data
    }
    
    return [processed_item]

def _process_kra2a_research_to_project_lead(text, classification_result, upload, extracted_items):
    """Process KRA 2A Lead Research-to-Project."""
    pass # Implement standard scoring loop

def _process_kra2a_research_to_project_contributor(text, classification_result, upload, extracted_items):
    """Process KRA 2A Contributor Research-to-Project."""
    pass # Implement standard scoring loop

def _process_kra2a_citation_local(text, classification_result, upload, extracted_items):
    """Process KRA 2A Local Citation."""
    pass # Implement standard scoring loop

def _process_kra2a_citation_international(text, classification_result, upload, extracted_items):
    """Process KRA 2A International Citation."""
    pass # Implement standard scoring loop

def _process_kra2b_invention(text, classification_result, upload, extracted_items):
    """Process KRA 2B Invention Patents."""
    pass # Implement standard scoring loop

def _process_kra2b_utility(text, classification_result, upload, extracted_items):
    """Process KRA 2B Utility Models."""
    pass # Implement standard scoring loop

def _process_kra2b_industrial(text, classification_result, upload, extracted_items):
    """Process KRA 2B Industrial Designs."""
    pass # Implement standard scoring loop

def _process_kra2b_commercialized(text, classification_result, upload, extracted_items):
    """Process KRA 2B Commercialized Patents."""
    pass # Implement standard scoring loop

def _process_kra2b_new_software(text, classification_result, upload, extracted_items):
    """Process KRA 2B New Software."""
    pass # Implement standard scoring loop

def _process_kra2b_updated_software(text, classification_result, upload, extracted_items):
    """Process KRA 2B Updated Software."""
    pass # Implement standard scoring loop

def _process_kra2b_biological_sole(text, classification_result, upload, extracted_items):
    """Process KRA 2B Biological - Sole."""
    pass # Implement standard scoring loop

def _process_kra2b_biological_co(text, classification_result, upload, extracted_items):
    """Process KRA 2B Biological - Co."""
    pass # Implement standard scoring loop

def _process_kra2c_performing_art(text, classification_result, upload, extracted_items):
    """Process KRA 2C Performing Art."""
    pass # Implement standard scoring loop

def _process_kra2c_exhibition(text, classification_result, upload, extracted_items):
    """Process KRA 2C Exhibition."""
    pass # Implement standard scoring loop

def _process_kra2c_juried_design(text, classification_result, upload, extracted_items):
    """Process KRA 2C Juried Design."""
    pass # Implement standard scoring loop

def _process_kra2c_literary(text, classification_result, upload, extracted_items):
    """Process KRA 2C Literary."""
    pass # Implement standard scoring loop

def _process_fallback(text, classification_result, upload, extracted_items):
    pass

# Maps evidence_type to the appropriate processing strategy function
PROCESSING_STRATEGIES = {
    "kra1a_evaluation": _process_kra1a_evaluation,
    "kra1c_adviser": lambda t, c, u, e: _process_kra1c_services(t, c, u, e, "kra1c_adviser"),
    "kra1c_panel": lambda t, c, u, e: _process_kra1c_services(t, c, u, e, "kra1c_panel"),
    "kra1b_sole": _process_kra1b_sole,
    "kra1b_co": _process_kra1b_co,
    "kra1b_program_leadAndContri": _process_kra1b_program_leadAndContri,
    "kra2a_research": _process_kra2a_research,
    "kra2a_research_to_project_lead": _process_kra2a_research_to_project_lead,
    "kra2a_research_to_project_contributor": _process_kra2a_research_to_project_contributor,
    "kra2a_citation_local": _process_kra2a_citation_local,
    "kra2a_citation_international": _process_kra2a_citation_international,
    "kra2b_invention": _process_kra2b_invention,
    "kra2b_utility": _process_kra2b_utility,
    "kra2b_industrial": _process_kra2b_industrial,
    "kra2b_commercialized": _process_kra2b_commercialized,
    "kra2b_new_software": _process_kra2b_new_software,
    "kra2b_updated_software": _process_kra2b_updated_software,
    "kra2b_biological_sole": _process_kra2b_biological_sole,
    "kra2b_biological_co": _process_kra2b_biological_co,
    "kra2c_performing_art": _process_kra2c_performing_art,
    "kra2c_exhibition": _process_kra2c_exhibition,
    "kra2c_juried_design": _process_kra2c_juried_design,
    "kra2c_literary": _process_kra2c_literary,
    # Add other specific types as they are implemented
}

def process_document_upload(upload):
    try:
        file_info_list = extract_text_from_drive(upload.google_drive_link)
        
        if not file_info_list:
            upload.status = "failed"
            upload.error_message = "No valid files found"
            upload.save()
            return False

        faculty_full_name = f"{upload.user.first_name} {upload.user.last_name}".strip()
        
        print(f"\n--- SCANNING {len(file_info_list)} FILES ---")

        priority_file = None
        supporting_files = []
        
        final_extraction_files = [] 

        for f in file_info_list:
            fname = f['file_name'].lower()
            text = f['text'].lower()
            
            is_cert = "certifi" in fname or "this is to certify" in text
            
            is_research = "abstract" in text or "introduction" in text and len(text) > 1000
            
            is_reso = "resolution" in text and ("board" in text or "no." in text)

            if is_cert:
                print(f"-> Found PRIORITY File: {f['file_name']}")
                if not priority_file:
                    priority_file = f
                final_extraction_files.append(f)
                
            elif is_research and not priority_file:
                print(f"-> Found PRIORITY File (Research): {f['file_name']}")
                priority_file = f
                final_extraction_files.append(f)
                
            elif is_reso:
                print(f"-> Found SUPPORTING File: {f['file_name']}")
                supporting_files.append(f)
                final_extraction_files.append(f)
                
            else:
                final_extraction_files.append(f)

        if not priority_file and file_info_list:
            priority_file = file_info_list[0]
            print(f"-> No specific priority detected. Using first file as anchor: {priority_file['file_name']}")

        print(f"\n--- CLASSIFYING SINGLE FILE: {priority_file['file_name']} ---")
        classification_result = classify_document(priority_file['text'])
        
        if classification_result.get('primary_kra') == "1":
            p_text = priority_file['text'].lower()
            if "degree" in p_text or "program" in p_text or "curriculum" in p_text:
                if classification_result.get('sub_criterion') != "2.1":
                    print("-> Correction: Detected 'Program/Degree' keywords. Forcing Evidence Type to Program.")
                    classification_result['criterion'] = "B"
                    classification_result['sub_criterion'] = "2.1"

        evidence_type = map_classification_to_evidence_type(classification_result)
        print(f"Determined Evidence Type: {evidence_type}")

        combined_text = ""
        total_pages = 0
        file_names = []
        
        sorted_files = [priority_file] + [f for f in final_extraction_files if f != priority_file]

        for f in sorted_files:
            combined_text += f"\n\n--- FILE: {f['file_name']} ---\n"
            combined_text += f['text']
            total_pages += f['page_count']
            file_names.append(f['file_name'])

        extracted_data = []
        upload.total_score = 0.0 

        if evidence_type:
            try:
                raw_items = route_extraction(evidence_type, combined_text, faculty_name=faculty_full_name)
                
                processor = PROCESSING_STRATEGIES.get(evidence_type, _process_fallback)
                extracted_data = processor(combined_text, classification_result, upload, raw_items)
            except Exception as e:
                print(f"Extraction error: {e}")
                import traceback
                traceback.print_exc()

        upload.status = "completed"
        upload.page_count = total_pages
        upload.primary_kra = classification_result.get("primary_kra")
        upload.kra_confidence = classification_result.get("confidence")
        upload.criteria = classification_result.get("criterion")
        upload.sub_criteria = classification_result.get("sub_criterion")
        
        upload.explanation = f"Classified using '{priority_file['file_name']}'. Extracted data from {len(sorted_files)} files."
        upload.extracted_text_preview = combined_text[:500] + "..."
        upload.error_message = None

        unified_result = {
            'file_name': f"Group: {', '.join(file_names)}",
            'file_id': "BATCH_GROUP",
            'page_count': total_pages,
            'classification': classification_result,
            'evidence_type': evidence_type,
            'extracted_data': extracted_data,
            'total_score': upload.total_score,
            'text_preview': combined_text[:200]
        }
        
        upload.extracted_json = json.dumps({
            'file_count': len(sorted_files),
            'files': [unified_result]
        }, indent=2)
        
        upload.save()

        if hasattr(upload.user, "faculty_profile") and getattr(upload.user.faculty_profile, "sheet_url", None):
                    sheet_url = upload.user.faculty_profile.sheet_url
                    spreadsheet_id = sheet_url.split("/d/")[1].split("/")[0] if "/d/" in sheet_url else sheet_url
                    folder_link = upload.google_drive_link

                    try:

                        if evidence_type == "kra1a_evaluation" and extracted_data:
                            print(f"-> Sending KRA 1A to Sheets...")
                            info = extracted_data[0] # Take first item
                            
                            parts = info.get("semester_ay", "").lower().replace("a.y.", "").split()
                            semester_raw = parts[0] if len(parts) > 0 else "1st"
                            ay_raw = parts[-1] if len(parts) > 0 else "2023-2024"
                            
                            ay, sem, eval_type = normalize_values(ay_raw, semester_raw, info.get("evaluation_type", ""))
                            
                            send_evaluation_to_spreadsheetKRA1_Eval(
                                spreadsheet_id=spreadsheet_id,
                                academic_year=ay,
                                semester=sem,
                                evaluation_type=eval_type,
                                total_score=info.get("total_score", 0),
                                drive_link=folder_link
                            )

                        elif evidence_type == "kra1b_program_leadAndContri" and extracted_data:
                            print(f"-> Sending KRA 1B (Program) to Sheets...")
                            
                            # Loop in case multiple items exist (though logic limits to 1)
                            for item in extracted_data:
                                raw = item.get("extracted_raw", {})
                                
                                send_program_contribution_to_sheet(
                                    spreadsheet_id=spreadsheet_id,
                                    program_name=item.get('title', 'Unknown Program'),
                                    program_type=raw.get('program_type', 'Revised Program'),
                                    board_reso=raw.get('board_resolution', 'N/A'),
                                    academic_year=raw.get('academic_year', 'N/A'),
                                    role=item.get('role', 'Contributor'),
                                    score=item.get('points', 0),
                                    drive_link=folder_link  # Points to the Folder
                                )

                        elif evidence_type == "kra2a_research" and extracted_data:
                            print(f"-> Sending KRA 2A Research to Sheets ({len(extracted_data)} items)...")
                            
                            for item in extracted_data:
                                raw = item.get("extracted_raw", {})
                                
                                mode = raw.get('author_mode', 'sole')
                                # Use the FORCED type from the processor
                                r_type = raw.get("final_research_type")
                                
                                # --- DATA SANITIZATION START ---
                                
                                # 1. Base Cleaning (N/A -> Empty)
                                reviewer_clean = raw.get('reviewer', '')
                                if reviewer_clean == "N/A": reviewer_clean = ""
                                
                                indexing_clean = raw.get('indexing', '')
                                if indexing_clean == "N/A": indexing_clean = ""
                                
                                journal_clean = raw.get('journal', '')
                                if journal_clean == "N/A": journal_clean = ""

                                # 2. RULE ENFORCER (The Fix)
                                # If type is Journal, Reviewer MUST be empty.
                                if r_type == "Journal Article":
                                    reviewer_clean = "" 
                                
                                # If type is Other Peer-Reviewed, Indexing MUST be empty.
                                if r_type == "Other Peer-Reviewed Output":
                                    indexing_clean = ""

                                # 3. Date Fix
                                date_clean = raw.get('date_published', '')
                                
                                try:
                                    if date_clean and date_clean != "N/A":
                                        # Check for YYYY-MM-DD
                                        if "-" in date_clean and len(date_clean.split("-")) == 3:
                                            date_obj = datetime.strptime(date_clean.strip(), "%Y-%m-%d")
                                            date_clean = date_obj.strftime("%m/%d/%Y")
                                        # Check for Month DD, YYYY
                                        elif "," in date_clean:
                                            date_obj = datetime.strptime(date_clean.strip(), "%B %d, %Y")
                                            date_clean = date_obj.strftime("%m/%d/%Y")
                                except Exception:
                                    pass # Keep original if parsing fails

                                if date_clean and len(date_clean.strip()) == 4 and date_clean.strip().isdigit():
                                    date_clean = f"01/01/{date_clean.strip()}"
                                elif date_clean == "N/A":
                                    date_clean = ""
                                
                                # --- DATA SANITIZATION END ---

                                send_research_to_sheet(
                                    spreadsheet_id=spreadsheet_id,
                                    title=item.get('title', 'Untitled Research'),
                                    research_type=r_type,
                                    journal=journal_clean,
                                    reviewer=reviewer_clean, # Sent as "" if Journal Article
                                    indexing=indexing_clean, # Sent as "" if Other Output
                                    date_published=date_clean,
                                    score=item.get('points', 0),
                                    drive_link=folder_link,
                                    author_mode=mode,
                                    contribution=raw.get('contribution', 0)
                                )

                    except Exception as sheet_error:
                        print(f"Error sending to Google Sheets: {sheet_error}")
                        import traceback
                        traceback.print_exc()

        print(f"Processing Complete. Score: {upload.total_score}")
        return True

    except Exception as e:
        upload.status = "failed"
        upload.error_message = str(e)
        upload.save()
        logger.error(f"Error processing upload {upload.id}: {e}")
        return False