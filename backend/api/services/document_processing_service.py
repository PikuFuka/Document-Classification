# api/services/document_processing_service.py
import os
import uuid
import io
import pytesseract
import uuid
from PIL import Image, ImageFilter, ImageOps
from django.conf import settings
from googleapiclient.discovery import build
from .ml_processing_service import classify_document
from .google_sheets_service import send_evaluation_to_spreadsheetKRA1_Eval, normalize_values
import logging
from docx import Document
import json
import fitz
from .extraction_strategies import route_extraction
from .scoring_rules import calculate_score, SCORING_RULES

logger = logging.getLogger(__name__)

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
    service = build('drive', 'v3', developerKey=settings.GOOGLE_API_KEY)

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

        request = service.files().get_media(fileId=file_id)
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        temp_path = os.path.join(settings.MEDIA_ROOT, f"{uuid.uuid4()}_{file_name}")

        with open(temp_path, 'wb') as f:
            downloader = request.execute()
            f.write(downloader)

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
        import traceback
        traceback.print_exc()
        return None


def extract_files_from_drive_folder(folder_id):
    """Extract files from folder and return list of file info dicts."""
    try:
        service = build('drive', 'v3', developerKey=settings.GOOGLE_API_KEY)

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
        import traceback
        traceback.print_exc()
        return []


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Preprocess image for better OCR results."""
    try:
        # Convert to grayscale
        gray = img.convert("L")
        # Increase contrast
        gray = ImageOps.autocontrast(gray)
        # Apply median filter to reduce noise
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
        # Binarize
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
    primary_kra = classification_result.get("primary_kra")
    criterion = classification_result.get("criterion")
    sub_criterion = classification_result.get("sub_criterion")

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

        ("2", "A", "1.1"): "kra2a_sole",
        ("2", "A", "1.2"): "kra2a_co",
        ("2", "A", "1.3"): "kra2a_sole",
        ("2", "A", "1.4"): "kra2a_co",
        ("2", "A", "1.5"): "kra2a_sole",
        ("2", "A", "1.6"): "kra2a_co",
        ("2", "A", "1.7"): "kra2a_sole",
        ("2", "A", "1.8"): "kra2a_co",
        ("2", "A", "1.9"): "kra2a_co",
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

    evidence_type = mapping.get((primary_kra, criterion, sub_criterion))

    if not evidence_type:
        print(f"Warning: No specific mapping found for KRA={primary_kra}, Criterion={criterion}, Sub={sub_criterion}. Using fallback or None.")
        text_sample = classification_result.get("text_sample", "")
        if primary_kra == "1" and criterion == "A":
             return "kra1a_evaluation"

    return evidence_type


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
    """Process KRA 1B lead and contri Academic Program."""
    pass # Implement standard scoring loop

def _process_kra2a_sole(text, classification_result, upload, extracted_items):
    """Process KRA 2A Sole Research Outputs."""
    pass # Implement standard scoring loop

def _process_kra2a_co(text, classification_result, upload, extracted_items):
    """Process KRA 2A Co Research Outputs."""
    pass # Implement standard scoring loop

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
    "kra2a_sole": _process_kra2a_sole,
    "kra2a_co": _process_kra2a_co,
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

def process_single_file(file_info, upload, faculty_full_name):
    """Process a single file and return its results."""
    text = file_info['text']
    page_count = file_info['page_count']
    file_name = file_info['file_name']
    file_id = file_info['file_id']

    try:
        classification_result = classify_document(text)
        print(f"Classification Result for {file_name}: {classification_result}")

        classification_result["text_sample"] = text
        evidence_type = map_classification_to_evidence_type(classification_result)
        print(f"Mapped Evidence Type: {evidence_type}")

        extracted_data = []
        total_score = 0.0

        if evidence_type:
            try:
                raw_extracted_items = route_extraction(evidence_type, text, faculty_name=faculty_full_name)
                
                # Create temporary upload object
                class TempUpload:
                    def __init__(self):
                        self.total_score = 0.0
                        self.equivalent_percentage = None
                
                temp_upload = TempUpload()
                
                # Get processing function
                processing_func = PROCESSING_STRATEGIES.get(evidence_type, _process_fallback)
                extracted_data = processing_func(text, classification_result, temp_upload, raw_extracted_items)
                total_score = temp_upload.total_score
                
            except Exception as extract_error:
                print(f"Error during extraction/processing: {extract_error}")
                import traceback
                traceback.print_exc()

        return {
            'file_name': file_name,
            'file_id': file_id,
            'page_count': page_count,
            'classification': classification_result,
            'evidence_type': evidence_type,
            'extracted_data': extracted_data,
            'total_score': total_score,
            'text_preview': text[:500] + "..." if len(text) > 500 else text
        }
        
    except Exception as e:
        print(f"Error processing single file {file_name}: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'file_name': file_name,
            'file_id': file_id,
            'page_count': page_count,
            'classification': {'error': str(e)},
            'evidence_type': None,
            'extracted_data': [],
            'total_score': 0.0,
            'text_preview': text[:500] if text else ""
        }


def process_document_upload(upload):
    """Process document upload with multiple files support."""
    try:
        # Extract files
        file_info_list = extract_text_from_drive(upload.google_drive_link)
        
        if not file_info_list:
            upload.status = "failed"
            upload.error_message = "No valid files found"
            upload.save()
            return False

        faculty_full_name = f"{upload.user.first_name} {upload.user.last_name}".strip()
        
        # Process each file
        all_results = []
        total_pages = 0
        combined_score = 0.0

        for idx, file_info in enumerate(file_info_list):
            print(f"\n{'='*60}")
            print(f"Processing file {idx+1}/{len(file_info_list)}: {file_info['file_name']}")
            print(f"{'='*60}\n")
            
            file_result = process_single_file(file_info, upload, faculty_full_name)
            all_results.append(file_result)
            total_pages += file_result['page_count']
            combined_score += file_result['total_score']

        # Update upload
        upload.status = "completed"
        upload.page_count = total_pages
        upload.total_score = combined_score
        
        if all_results:
            first_result = all_results[0]
            upload.primary_kra = first_result['classification'].get("primary_kra")
            upload.kra_confidence = first_result['classification'].get("confidence")
            upload.criteria = first_result['classification'].get("criterion")
            upload.sub_criteria = first_result['classification'].get("sub_criterion")
            upload.explanation = f"Processed {len(all_results)} file(s). First: {first_result['classification'].get('explanation', 'N/A')}"
            upload.extracted_text_preview = first_result['text_preview']

        upload.error_message = None
        
        # Save results as JSON
        upload.extracted_json = json.dumps({
            'file_count': len(all_results),
            'files': all_results
        }, indent=2)
        
        upload.save()

        # Send to Google Sheets
        if hasattr(upload.user, "faculty_profile") and getattr(upload.user.faculty_profile, "sheet_url", None):
            sheet_url = upload.user.faculty_profile.sheet_url
            spreadsheet_id = sheet_url.split("/d/")[1].split("/")[0] if "/d/" in sheet_url else sheet_url

            for file_result in all_results:
                if file_result['evidence_type'] == "kra1a_evaluation" and file_result['extracted_data']:
                    try:
                        info = file_result['extracted_data'][0]
                        semester_ay = info.get("semester_ay", "")
                        total_score = info.get("total_score", 0)
                        evaluation_type_raw = info.get("evaluation_type", "")

                        parts = semester_ay.lower().replace("a.y.", "").split()
                        semester_raw = parts[0] if len(parts) > 0 else "1st"
                        academic_year_raw = parts[-1] if len(parts) > 0 else "2022-2023"

                        academic_year, semester, evaluation_type = normalize_values(
                            academic_year_raw, semester_raw, evaluation_type_raw
                        )

                        send_evaluation_to_spreadsheetKRA1_Eval(
                            spreadsheet_id=spreadsheet_id,
                            academic_year=academic_year,
                            semester=semester,
                            evaluation_type=evaluation_type,
                            total_score=total_score,
                            drive_link=f"https://drive.google.com/file/d/{file_result['file_id']}/view",
                        )
                    except Exception as sheet_error:
                        print(f"Error sending to Google Sheets: {sheet_error}")
                        import traceback
                        traceback.print_exc()

        print(f"\n{'='*60}")
        print(f"Successfully processed {len(all_results)} file(s)")
        print(f"Total combined score: {combined_score}")
        print(f"{'='*60}\n")

        return True

    except Exception as e:
        upload.status = "failed"
        upload.error_message = str(e)
        upload.save()
        logger.error(f"Error processing upload {upload.id}: {e}")
        import traceback
        traceback.print_exc()
        return False