# api/services/extraction_strategies.py
import time
from datetime import time as datetime
import re
import random
import uuid
from .opti import _generate_name_variants, _find_section_blocks, _find_name_near_role, _extract_academic_year, _extract_project_level
import json
import logging
from groq import Groq
from django.conf import settings

logger = logging.getLogger(__name__)

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
    """
    Extracts multiple programs but returns ONLY ONE (the first found).
    This ensures the output is a single row with a single score.
    """
    print(f"EXTRACTOR: extract_kra1b_program_leadAndContri called for {faculty_name}.")
    
    results = []
    # Remove source tags and clean up whitespace
    clean_text = re.sub(r"<source>.*?<\/source>", "", text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # --- 1. Common Data Extraction (Board Reso & AY) ---
    
    # Board Resolution Pattern
    reso_match = re.search(r"(?:Board\s+)?Resolution\s+No\.?\s*([\w\d-]+)\s*(?:Series of|s\.)\s*(\d{4})", clean_text, re.IGNORECASE)
    board_reso = f"Resolution No. {reso_match.group(1)} s. {reso_match.group(2)}" if reso_match else "Pending/Not Found"

    # Academic Year Pattern
    # Captures only the digits (e.g., "2019-2020") for the dropdown
    ay_match = re.search(r"(?:A\.?Y\.?|Academic\s+Year)[\s:]*(\d{4}\s*[-–]\s*\d{4})", clean_text, re.IGNORECASE)
    acad_year = ay_match.group(1).replace("–", "-") if ay_match else "2019-2020"

    # --- 2. Determine Program Type (New vs Revised) ---
    
    # Keywords for "Revised"
    revised_keywords = [
        r"revis",        # revised, revision, revising
        r"enhanc",       # enhanced, enhancement
        r"amend",        # amended, amendment
        r"enrich",       # enriched, enrichment
        r"updat",        # updated, update
        r"modif",        # modified, modification
        r"curriculum\s+change"
    ]
    revised_pattern = r"(" + "|".join(revised_keywords) + r")"

    # Keywords for "New"
    new_keywords = [
        r"new",
        r"propos",       # proposal, proposed
        r"offer",        # offering
        r"creat",        # creation
        r"establish",    # establishment
        r"institut"      # institution of
    ]
    
    if re.search(revised_pattern, clean_text, re.IGNORECASE):
        program_type = "Revised Program"
    elif re.search(r"(" + "|".join(new_keywords) + r")", clean_text, re.IGNORECASE):
        program_type = "New Program"
    else:
        program_type = "Revised Program" 

    # --- 3. Determine Role (Lead vs Contributor) ---
    
    role = "Contributor" # Default
    
    if faculty_name:
        # Keywords for "Lead"
        lead_keywords = [
            r"lead",
            r"head",
            r"chair",
            r"manager",      # Project Manager
            r"proponent",    # Lead Proponent
            r"principal",    # Principal Author
            r"author",
            r"spearh"
        ]
        
        # Check strict proximity: Is the Faculty Name near a "Lead" keyword?
        if re.search(rf"{re.escape(faculty_name)}.*contributed", clean_text, re.IGNORECASE) or \
           re.search(rf"contributed.*{re.escape(faculty_name)}", clean_text, re.IGNORECASE):
            role = "Contributor"
        
        elif re.search(r"(" + "|".join(lead_keywords) + r")", clean_text, re.IGNORECASE):
            if re.search(rf"(?:Lead|Head|Chair|Manager|Proponent).*?{re.escape(faculty_name)}", clean_text, re.IGNORECASE):
                role = "Lead"
            elif re.search(rf"{re.escape(faculty_name)}.*?(?:Lead|Head|Chair|Manager|Proponent)", clean_text, re.IGNORECASE):
                role = "Lead"
            else:
                role = "Contributor"
    
    degree_pattern = r"(?:1\.|2\.|3\.|•)?\s*((?:Bachelor|Master|Doctor)\s+of\s+[\w\s]+(?:Major\s+in\s+[\w\s]+)?)"
    degree_matches = re.findall(degree_pattern, clean_text, re.IGNORECASE)

    programs = []
    for d in degree_matches:
        clean_name = re.sub(r'\s+', ' ', d).strip()
        if len(clean_name) > 10: 
            programs.append(clean_name)
    
    programs = sorted(list(set(programs))) # Remove duplicates

    if not programs:
        programs = ["Program Name Not Detected"]
    
    # --- LIMIT TO 1 PROGRAM ---
    # This logic takes the first sorted program and ignores the rest.
    programs = programs[:1]

    # --- 5. Build Result List ---
    for prog in programs:
        results.append({
            "program_name": prog.upper(),
            "program_type": program_type,
            "board_resolution": board_reso,
            "academic_year": acad_year,
            "role": role 
        })

    print(f"DEBUG: extract_kra1b_program_leadAndContri results: {results}")
    return results

# =========================================================
# KRA 2A: RESEARCH OUTPUTS (Sole & Co-Author)
# =========================================================
"""
def extract_kra2a_sole(text, faculty_name=None):
    print(f"EXTRACTOR: extract_kra2a_sole called.")
    return _extract_research_common(text, faculty_name, is_sole=True)

def extract_kra2a_co(text, faculty_name=None):
    print(f"EXTRACTOR: extract_kra2a_co called for {faculty_name}.")
    return _extract_research_common(text, faculty_name, is_sole=False)

def _extract_research_common(text, faculty_name, is_sole=True):
    results = []
    # Clean text
    clean_text = re.sub(r'\\', '', text).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    
    # --- STRATEGY A: IS THIS A CERTIFICATION? ---
    # Certifications usually follow a strict sentence structure.
    is_cert = "certify" in clean_text.lower() or "certification" in clean_text.lower()
    
    title = "Research Title Detected"
    journal = "N/A"
    
    if is_cert:
        print("DEBUG: Using Certification Extraction Logic")
        # Pattern: "certify that the research entitled [TITLE] authored by..."
        title_match = re.search(r"entitled\s+[:\"]?([^\"\.]{5,200})[:\"\.?]", clean_text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        
        # Pattern: "published in [JOURNAL] on..."
        journal_match = re.search(r"published\s+in\s+the\s+([^\.]+?)\s+(?:on|dated)", clean_text, re.IGNORECASE)
        if journal_match:
            journal = journal_match.group(1).strip()
            
    else:
        print("DEBUG: Using Research Paper Header Logic")
        # --- STRATEGY B: IS THIS THE PAPER HEADER? ---
        
        # 1. TITLE
        # Look for explicit label or the first long bold-like string (heuristically)
        explicit_title = re.search(r"(?:Title|Entitled)\s*[:\-\.]\s*([^\n\r]+)", clean_text, re.IGNORECASE)
        if explicit_title:
            title = explicit_title.group(1).strip()
        else:
            # Fallback: Assume the title is before the word "Abstract"
            pre_abstract = re.split(r"Abstract", clean_text, flags=re.IGNORECASE)[0]
            # Take the longest line in the pre-abstract text
            lines = [l.strip() for l in pre_abstract.split('.') if len(l) > 10]
            # Filter out author names or affiliations usually short or containing "University"
            valid_lines = [l for l in lines if "university" not in l.lower() and "college" not in l.lower() and len(l) > 20]
            if valid_lines:
                title = valid_lines[0]

        # 2. JOURNAL
        # Look for common header formats
        j_match = re.search(r"([A-Za-z\s]*Journal\s+of\s+[A-Za-z\s\-]*)", clean_text, re.IGNORECASE)
        if j_match:
            journal = j_match.group(1).strip()
        else:
            # Look for "Vol. X, No. Y" context
            vol_context = re.search(r"([A-Za-z\s]+)\s+Vol\.?\s?\d", clean_text, re.IGNORECASE)
            if vol_context:
                journal = vol_context.group(1).strip()

    # --- 3. DATE PUBLISHED (Common to both) ---
    date_published = "N/A"
    
    # Priority 1: Explicit Label
    explicit_date = re.search(r"(?:Date\s+Published|Published\s+on|Date)\s*[:\-]\s*([A-Za-z0-9,\s]+)", clean_text, re.IGNORECASE)
    
    # Priority 2: Pattern Matching
    # Matches: "January 1, 2023", "Jan 2023", "01/01/2023", "2023-01-01"
    date_patterns = [
        r"(\w+\s+\d{1,2},?\s+\d{4})", # Month DD, YYYY
        r"(\w+\s+\d{4})",             # Month YYYY
        r"(\d{2}[/\-]\d{2}[/\-]\d{4})" # MM/DD/YYYY
    ]
    
    raw_date = None
    if explicit_date:
        raw_date = explicit_date.group(1)
    else:
        for pat in date_patterns:
            # We search specifically near "Published" keywords if possible to avoid random dates
            match = re.search(pat, clean_text, re.IGNORECASE)
            if match:
                raw_date = match.group(0).strip()
                break
    
    # Convert to MM/DD/YYYY format
    if raw_date:
        try:
            # Try parsing various formats
            for fmt in ["%B %d, %Y", "%B %Y", "%m/%d/%Y", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(raw_date, fmt)
                    date_published = dt.strftime("%m/%d/%Y")
                    break
                except ValueError:
                    continue
            if date_published == "N/A": date_published = raw_date # Keep raw if parse fails
        except:
            date_published = raw_date

    # --- 4. INDEXING BODY ---
    indexing = "N/A"
    index_keywords = ["Scopus", "Web of Science", "Clarivate", "ASEAN Citation Index", "ACI", "CHED Recognized"]
    found_indices = [k for k in index_keywords if k.lower() in clean_text.lower()]
    if found_indices:
        indexing = ", ".join(found_indices)

    # --- 5. CONTRIBUTION % ---
    contribution = 100 if is_sole else 0
    
    if not is_sole and faculty_name:
        # Normalize name for search (Use Last Name)
        parts = faculty_name.split()
        lname = parts[-1] if parts else faculty_name
        
        # Pattern A: Tabular/List format "Name ..... 50%"
        # Matches: "Villarica ... 50%" or "Villarica - 50%" or "Villarica 50"
        pct_match = re.search(rf"{re.escape(lname)}[^\d\n]*?(\d{{1,3}})\s*%", clean_text, re.IGNORECASE)
        
        # Pattern B: Explicit Label "Contribution: 50%"
        generic_pct = re.search(r"(?:Contribution|Share)\s*[:\-]\s*(\d{1,3})%", clean_text, re.IGNORECASE)

        if pct_match:
            contribution = int(pct_match.group(1))
        elif generic_pct:
            contribution = int(generic_pct.group(1))

    # --- 6. TYPE HINTING ---
    res_type_hint = "Journal Article"
    if "book" in clean_text.lower() and "chapter" not in clean_text.lower(): res_type_hint = "Book"
    elif "chapter" in clean_text.lower(): res_type_hint = "Book Chapter"
    elif "monograph" in clean_text.lower(): res_type_hint = "Monograph"

    results.append({
        "title": title.strip("."),
        "type_hint": res_type_hint,
        "journal": journal.strip("."),
        "indexing": indexing,
        "date_published": date_published,
        "contribution": contribution
    })
    print(f"DEBUG: Extracted research item: {results[-1]}")
    return results
"""

def query_llm_for_json(prompt, text):
    """
    Sends text to Groq (Llama 3) with built-in Rate Limit protection.
    """
    if not hasattr(settings, 'GROQ_API_KEY') or not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY is missing.")
        return None

    # 1. PREVENT BURSTS (Crucial for Free Tier)
    # The free tier allows ~20 requests/min. A 3-second pause limits you to 20/min max.
    time.sleep(3) 

    client = Groq(api_key=settings.GROQ_API_KEY)
    
    safe_text = text[:20000] 
    
    system_prompt = """
    You are a strict data extraction API. 
    Output ONLY valid JSON. 
    Do not add Markdown formatting (like ```json).
    """

    # 2. RETRY LOOP
    max_retries = 3
    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{prompt}\n\nDOCUMENT TEXT:\n{safe_text}"}
                ],
                # Use Llama 3.1 8B Instant (Fastest, Lowest Cost)
                model="meta-llama/llama-4-scout-17b-16e-instruct", 
                
                # CRITICAL: JSON Mode
                response_format={"type": "json_object"}, 
                temperature=0.1, 
            )

            response_content = chat_completion.choices[0].message.content
            return json.loads(response_content)

        except Exception as e:
            error_str = str(e).lower()
            
            # If Rate Limit (429), wait and retry
            if "429" in error_str or "rate limit" in error_str:
                wait_time = (attempt + 1) * 10 + random.uniform(1, 3) # Wait 10s, 20s, 30s
                print(f"WARNING: Groq Rate Limit Hit. Cooling down for {wait_time:.1f}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Groq Error: {e}")
                return None # Fatal error, stop trying

    return None

def extract_kra2a_sole(text, faculty_name=None):
    print(f"EXTRACTOR: extract_kra2a_sole called (via Groq).")
    return _extract_research_llm(text, faculty_name, expected_mode="sole")

def extract_kra2a_co(text, faculty_name=None):
    print(f"EXTRACTOR: extract_kra2a_co called (via Groq).")
    return _extract_research_llm(text, faculty_name, expected_mode="co")

def _extract_research_llm(text, faculty_name, expected_mode="sole"):
    """
    Unified extraction prompt.
    """
    
    prompt = f"""
    Analyze the provided academic document.
    Target Faculty Member: "{faculty_name}"

    Step 1: Locate the list of authors.
    Step 2: Check if "{faculty_name}" is the SOLE author or a CO-AUTHOR.
    Step 3: Extract the specific contribution percentage if available.

    Rules for 'contribution':
    - If "{faculty_name}" is the ONLY author: Set contribution = 100.
    - If multiple authors: Look for "{faculty_name} ... 40%" or "Contribution: 30%".
    - If multiple authors but NO percentage: Set 0.
    - extract date in MM/DD/YYYY format if possible.
    - if 2 authors and no percentage, set 50.
    - Do not hallucinate data. If unsure, use ' '.

    Extract into JSON:
    {{
        "title": "Full title",
        "journal": "Journal Name (or ' ')",
        "reviewer": "Name of Reviewer (ONLY if type is 'Other Peer-Reviewed Output', else ' ')",
        "date_published": "Date in MM/DD/YYYY format",
        "indexing": "Scopus, etc. (or ' ')",
        "contribution": Integer (0-100)
    }}
    """

    data = query_llm_for_json(prompt, text)
    print(f"DEBUG: Groq returned data: {data}")
    
    # Fallback if Groq fails
    if not data:
        print("Groq failed (Max Retries). Returning defaults.")
        return [{
            "title": "Extraction Failed", 
            "journal": "N/A", 
            "reviewer": "N/A",
            "date_published": "N/A", 
            "contribution": 0
        }]

    return [{
        "title": data.get("title", "Untitled").upper(),
        "journal": data.get("journal", "N/A"),
        "reviewer": data.get("reviewer", "N/A"),
        "indexing": data.get("indexing", "N/A"),
        "date_published": data.get("date_published", "N/A"),
        "contribution": int(data.get("contribution", 0))
    }]

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
    "kra2a_research": extract_kra2a_co,
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
