# api/services/scoring_rules.py

SCORING_RULES = {
    # KRA 1B: Instructional Materials
    "kra1b_sole": {
        "textbook": 30,
        "chapter": 16,
        "manual": 10,
        "multimedia": 10,
        "testing_material": 10,
    },
    "kra1b_co": {
        "textbook": 10,
        "chapter": 16,
        "manual": 10,
        "multimedia": 10,
        "testing_material": 10,
    },
    "kra1b_program": {"lead": 10, "contributor": 5},

    # KRA 1C: Services Rendered to Students
    "kra1c_adviser": {
        "SP": 3,
        "CP": 3,
        "UT": 5,
        "MT": 8,
        "DD": 10,
    },
    "kra1c_panel": {
        "SP": 1,
        "CP": 1,
        "UT": 1,
        "MT": 2,
        "DD": 2,
    },
    "kra1c_mentor": 3,

    # KRA 2A: Research Outputs
    "kra2a_sole": {
        "book": 100,
        "journal_article": 35,
        "book_chapter": 35,
        "monograph": 35,
        "other_peer_reviewed": 10,
    },
    "kra2a_co": {
        "book": 50,
        "journal_article": 35,
        "book_chapter": 35,
        "monograph": 35,
        "other_peer_reviewed": 10,
    },
    "kra2a_research_to_project": 35,
    "kra2a_citation": {"local": 5, "international": 10},

    # KRA 2B: Inventions & Innovations
    "kra2b_invention": {
        "acceptance": 10,
        "publication": 20,
        "grant": 80,
    },
    "kra2b_utility": 10,
    "kra2b_industrial": 10,
    "kra2b_commercialized": {"local": 20, "international": 30},
    "kra2b_new_software": 10,
    "kra2b_updated_software": 4,
    "kra2b_biological": 10,

    # KRA 2C: Creative Works
    "kra2c_performing_art": {"own": 20, "others": 10},
    "kra2c_exhibition": 20,
    "kra2c_juried_design": 20,
    "kra2c_literary": {"novel": 20, "short_story": 10, "essay": 10, "poetry": 10},
}

def calculate_score(evidence_type, subtype_or_stage, contribution_percent=100):
    base_points_dict = SCORING_RULES.get(evidence_type)
    if not base_points_dict:
        print(f"Warning: No base points found for evidence_type '{evidence_type}'. Returning 0.")
        return 0

    base_value = base_points_dict.get(subtype_or_stage)
    if isinstance(base_value, dict):
        print(f"Warning: Base points for '{evidence_type}.{subtype_or_stage}' is a dictionary. Need more specific key. Returning 0.")
        return 0
    elif base_value is None:
        print(f"Warning: No base points found for subtype/stage '{subtype_or_stage}' in '{evidence_type}'. Returning 0.")
        return 0

    score = base_value * (contribution_percent / 100.0)
    return score
