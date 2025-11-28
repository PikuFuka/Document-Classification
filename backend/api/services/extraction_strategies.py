# api/services/extraction_strategies.py
import re
import uuid
from .opti import _generate_name_variants, _find_section_blocks, _find_name_near_role, _extract_academic_year, _extract_project_level

def extract_kra1a_evaluation(raw_text, debug_dump=False, faculty_name=None):
    print("INFO: Using existing logic for KRA 1A evaluation extraction.")
    if not raw_text or not raw_text.strip():
        return []

    norm_text = (
        raw_text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00A0", " ")
    )
    norm_text = re.sub(r"[ \t\f\v]+", " ", norm_text)
    norm_text = re.sub(r"\r", "\n", norm_text)

    percentages = re.findall(r"\b\d{1,3}(?:\.\d+)?%", norm_text)

    eq_match = re.search(
        r"Equivalent\s*Percentage\s*(?:[:\-–—]?\s*)?(\d{1,3}(?:\.\d+)?%)",
        norm_text,
        re.IGNORECASE | re.DOTALL,
    )
    equivalent_percentage = (
        eq_match.group(1) if eq_match else (percentages[0] if percentages else None)
    )

    semester_ay = None
    sem_match = re.search(
        r"\b\d{1,2}(?:st|nd|rd|th)\s+semester\s+(?:A\.Y\.|A\.Y)\s*\d{4}\s*[-–—]\s*\d{4}",
        norm_text,
        re.IGNORECASE,
    )
    if sem_match:
        semester_ay = sem_match.group(0).strip()
    else:
        sem_match2 = re.search(
            r"\b(first|second|1st|2nd)\s+semester\s+(?:A\.Y\.|A\.Y)\s*\d{4}\s*[-–—]\s*\d{4}",
            norm_text,
            re.IGNORECASE,
        )
        if sem_match2:
            semester_ay = sem_match2.group(0).strip()

    found = []
    student_patterns = [
        r"\bstudents?['’]?\s*evaluation\b",
        r"\bstudent\s+evaluation\b",
        r"\bevaluation\s+by\s+students?\b",
        r"\bstudents?\s+evaluation\s+on\b",
    ]
    supervisor_patterns = [
        r"\bsupervisors?['’]?\s*evaluation\b",
        r"\bsupervisor\s+evaluation\b",
        r"\bevaluation\s+by\s+supervisors?\b",
        r"\bsupervisors?\s+evaluation\s+on\b",
    ]

    def smart_search(patterns, text_to_search):
        for p in patterns:
            if re.search(p, text_to_search, re.IGNORECASE):
                return True
        for p in patterns:
            fallback = re.sub(r"\\s\+", r"\\W{0,6}", p)
            if re.search(fallback, text_to_search, re.IGNORECASE):
                return True
        return False

    if smart_search(student_patterns, norm_text):
        found.append("Student's Evaluation")
    if smart_search(supervisor_patterns, norm_text):
        found.append("Supervisor's Evaluation")

    if "student" in raw_text.lower() and "Student's Evaluation" not in found:
        found.append("Student's Evaluation")
    if "supervisor" in raw_text.lower() and "Supervisor's Evaluation" not in found:
        found.append("Supervisor's Evaluation")

    evaluation_type = ", ".join(found) if found else None

    if debug_dump and not found:
        try:
            dump_path = f"debug_{uuid.uuid4()}.txt"
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
            print(f"Wrote debug text dump to {dump_path}")
        except Exception as e:
            print(f"Failed to write debug dump: {e}")

    total_score = None
    if equivalent_percentage:
        try:
            total_score = float(equivalent_percentage.replace("%", ""))
        except Exception:
            total_score = None

    return [{
        "evidence_type": "kra1a_evaluation",
        "equivalent_percentage": equivalent_percentage,
        "semester_ay": semester_ay,
        "evaluation_type": evaluation_type,
        "percentages": percentages,
        "raw_text_preview": raw_text[:500] + "..." if len(raw_text) > 500 else raw_text,
        "total_score": total_score,
    }]

def extract_kra1c_adviser(text, faculty_name=None):
    print(f"EXTRACTOR: extract_kra1c_adviser called for faculty: {faculty_name}")
    if not faculty_name:
        print("Warning: Faculty name not provided for adviser extraction.")
        return []

    items = []
    faculty_name_clean = faculty_name.strip()
    name_parts = faculty_name_clean.split()
    if len(name_parts) < 2:
        print(f"Warning: Faculty name '{faculty_name}' seems incomplete.")
        return []
    first_name = ' '.join(name_parts[:-1])
    last_name = name_parts[-1]

    name_variants = _generate_name_variants(first_name, last_name)
    print(f"DEBUG: Generated name variants for matching: {name_variants}")


    sections = _find_section_blocks(text, section_headers=['adviser', 'approved by', 'committee', 'signatures'])
    print(f"DEBUG: Found sections: {list(sections.keys())}")
    relevant_text = sections.get('adviser', sections.get('approved by', sections.get('committee', text)))
    print(f"DEBUG: Using text of length {len(relevant_text)} for adviser search.")

    adviser_role_keywords = [
        r'adviser', r'advisor', r'co[-\s]?adviser', r'co[-\s]?advisor',
        r'major[-\s]?adviser', r'major[-\s]?advisor', r'thesis[-\s]?adviser',
        r'dissertation[-\s]?adviser', r'undergraduate[-\s]?thesis[-\s]?adviser',
        r'master[\'’]?\s*thesis[-\s]?adviser', r'd\.?i\.?t\.?\s*thesis\s*adviser'
    ]
    found_name, context_found = _find_name_near_role(relevant_text, name_variants, adviser_role_keywords)

    if not found_name:
        print(f"INFO: Faculty name '{faculty_name}' not found near adviser role keywords in the relevant text section.")
        return [] 

    print(f"SUCCESS: Found faculty name '{found_name}' in adviser context.")

    academic_year = _extract_academic_year(context_found or relevant_text)
    if not academic_year:
        academic_year = _extract_academic_year(relevant_text)

    level = _extract_project_level(context_found or relevant_text)
    if not level:
        level = _extract_project_level(relevant_text)

    if not academic_year or not level:
        print(f"WARNING: Could not determine Academic Year or Level from the text for faculty '{faculty_name}'. AY: {academic_year}, Level: {level}")
        return [] 

   
    item_count = 1 

    from .scoring_rules import SCORING_RULES
    base_points_dict = SCORING_RULES.get("kra1c_adviser", {})
    base_value = base_points_dict.get(level, 0) 
    total_score = base_value * item_count 

    item = {
        "type": "adviser",
        "academic_year": academic_year,
        "level": level,
        "count": item_count,
        "total_score": total_score,
        "title": f"Adviser Service ({level}) {academic_year}",
        "contribution_percent": 100, 
        "matched_name": found_name,
        "context_found_in": context_found[:200] + "..." if context_found and len(context_found) > 200 else context_found
    }
    items.append(item)
    print(f"DEBUG: Successfully extracted adviser item: {item}")

    return items


def extract_kra1c_panel(text, faculty_name=None):
    """
    Extract Panel services from text.
    Returns a list of items, each representing one unique AY/Level combination found,
    with the count of instances for that combination and the total score.
    """
    print(f"EXTRACTOR: extract_kra1c_panel called for faculty: {faculty_name}")
    if not faculty_name:
        print("Warning: Faculty name not provided for panel extraction.")
        return []

    items = []
    faculty_name_clean = faculty_name.strip()
    name_parts = faculty_name_clean.split()
    if len(name_parts) < 2:
        print(f"Warning: Faculty name '{faculty_name}' seems incomplete.")
        return []
    first_name = ' '.join(name_parts[:-1])
    last_name = name_parts[-1]

    name_variants = _generate_name_variants(first_name, last_name)
    print(f"DEBUG: Generated name variants for matching: {name_variants}")

    sections = _find_section_blocks(text, section_headers=['panel', 'committee', 'approved by', 'signatures'])
    print(f"DEBUG: Found sections: {list(sections.keys())}")
    relevant_text = sections.get('panel', sections.get('committee', sections.get('approved by', text)))
    print(f"DEBUG: Using text of length {len(relevant_text)} for panel search.")

    panel_role_keywords = [
        r'panel[-\s]?member', r'panelist', r'member', r'external[-\s]?reader',
        r'committee', r'oral[-\s]?examination', r'examiner'
    ]
    found_name, context_found = _find_name_near_role(relevant_text, name_variants, panel_role_keywords)

    if not found_name:
        print(f"INFO: Faculty name '{faculty_name}' not found near panel role keywords in the relevant text section.")
        return []

    print(f"SUCCESS: Found faculty name '{found_name}' in panel context.")

    academic_year = _extract_academic_year(context_found or relevant_text)
    if not academic_year:
        academic_year = _extract_academic_year(relevant_text)

    level = _extract_project_level(context_found or relevant_text)
    if not level:
        level = _extract_project_level(relevant_text)

    if not academic_year or not level:
        print(f"WARNING: Could not determine Academic Year or Level from the text for faculty '{faculty_name}'. AY: {academic_year}, Level: {level}")
        return []

    item_count = 1

    from .scoring_rules import SCORING_RULES
    base_points_dict = SCORING_RULES.get("kra1c_panel", {})
    base_value = base_points_dict.get(level, 0)
    total_score = base_value * item_count

    item = {
        "type": "panel",
        "academic_year": academic_year,
        "level": level, 
        "count": item_count,
        "total_score": total_score,
        "title": f"Panel Member Service ({level}) {academic_year}",
        "contribution_percent": 100,
        "matched_name": found_name,
        "context_found_in": context_found[:200] + "..." if context_found and len(context_found) > 200 else context_found
    }
    items.append(item)
    print(f"DEBUG: Successfully extracted panel item: {item}")

    return items

def extract_kra1b_sole(text, faculty_name=None):
    print("INFO: Placeholder for KRA 1B Sole extraction.")
    return [{"type": "textbook", "title": "Placeholder Title", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra1b_co(text, faculty_name=None):
    print("INFO: Placeholder for KRA 1B Co extraction.")
    return [{"type": "textbook", "title": "Placeholder Title", "contribution_percent": 50, "calculated_score": 0}]

def extract_kra1b_program_leadAndContri(text, faculty_name=None):
    print("INFO: Placeholder for KRA 1B Program Lead/Contributor extraction.")
    return [{"type": "program_development", "role": "lead", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2a_sole(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A Sole extraction.")
    return [{"type": "book", "title": "Placeholder Title", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2a_co(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A Co extraction.")
    return [{"type": "book", "title": "Placeholder Title", "contribution_percent": 50, "calculated_score": 0}]

def extract_kra2a_research_to_project_lead(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A Research-to-Project Lead extraction.")
    return [{"type": "research_to_project", "role": "lead", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2a_research_to_project_contributor(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A Research-to-Project Contributor extraction.")
    return [{"type": "research_to_project", "role": "contributor", "contribution_percent": 50, "calculated_score": 0}]

def extract_kra2a_citation_local(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A Local Citation extraction.")
    return [{"type": "citation", "scope": "local", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2a_citation_international(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2A International Citation extraction.")
    return [{"type": "citation", "scope": "international", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_invention(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Invention extraction.")
    return [{"type": "invention", "subtype": "patent", "stage": "grant", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_utility(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Utility Model extraction.")
    return [{"type": "invention", "subtype": "utility_model", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_industrial(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Industrial Design extraction.")
    return [{"type": "invention", "subtype": "industrial_design", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_commercialized(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Commercialized extraction.")
    return [{"type": "commercialized", "scope": "local", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_new_software(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B New Software extraction.")
    return [{"type": "software", "subtype": "new", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_updated_software(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Updated Software extraction.")
    return [{"type": "software", "subtype": "updated", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_biological_sole(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Biological Sole extraction.")
    return [{"type": "biological", "role": "sole", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2b_biological_co(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2B Biological Co extraction.")
    return [{"type": "biological", "role": "co", "contribution_percent": 50, "calculated_score": 0}]

def extract_kra2c_performing_art(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2C Performing Art extraction.")
    return [{"type": "performing_art", "subtype": "own", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2c_exhibition(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2C Exhibition extraction.")
    return [{"type": "exhibition", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2c_juried_design(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2C Juried Design extraction.")
    return [{"type": "juried_design", "contribution_percent": 100, "calculated_score": 0}]

def extract_kra2c_literary(text, faculty_name=None):
    print("INFO: Placeholder for KRA 2C Literary extraction.")
    return [{"type": "literary", "subtype": "novel", "contribution_percent": 100, "calculated_score": 0}]


EXTRACTORS = {
    "kra1a_evaluation": extract_kra1a_evaluation,
    "kra1b_sole": extract_kra1b_sole,
    "kra1b_co": extract_kra1b_co,
    "kra1b_program_leadAndContri": extract_kra1b_program_leadAndContri,
    "kra1c_adviser": extract_kra1c_adviser,
    "kra1c_panel": extract_kra1c_panel,
    "kra2a_sole": extract_kra2a_sole,
    "kra2a_co": extract_kra2a_co,
    "kra2a_research_to_project_lead": extract_kra2a_research_to_project_lead,
    "kra2a_research_to_project_contributor": extract_kra2a_research_to_project_contributor,
    "kra2a_citation_local": extract_kra2a_citation_local,
    "kra2a_citation_international": extract_kra2a_citation_international,
    "kra2b_invention": extract_kra2b_invention,
    "kra2b_utility": extract_kra2b_utility,
    "kra2b_industrial": extract_kra2b_industrial,
    "kra2b_commercialized": extract_kra2b_commercialized,
    "kra2b_new_software": extract_kra2b_new_software,
    "kra2b_updated_software": extract_kra2b_updated_software,
    "kra2b_biological_sole": extract_kra2b_biological_sole,
    "kra2b_biological_co": extract_kra2b_biological_co,
    "kra2c_performing_art": extract_kra2c_performing_art,
    "kra2c_exhibition": extract_kra2c_exhibition,
    "kra2c_juried_design": extract_kra2c_juried_design,
    "kra2c_literary": extract_kra2c_literary,
}

def route_extraction(evidence_type, raw_text, faculty_name=None):
    func = EXTRACTORS.get(evidence_type)
    if not func:
        print(f"Warning: No extractor found for evidence_type '{evidence_type}'. Returning empty list.")
        return []
    try:
        result = func(raw_text, faculty_name=faculty_name)
        if isinstance(result, list):
            return result
        else:
            print(f"Warning: Extractor for '{evidence_type}' did not return a list. Returning empty list.")
            return []
    except Exception as e:
        print(f"Error in extractor '{evidence_type}': {e}")
        return []
