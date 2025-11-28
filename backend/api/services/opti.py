import re

def _generate_name_variants(first_name, last_name):
    variants = set()
    first_name_lower = first_name.lower().strip()
    last_name_lower = last_name.lower().strip()

    variants.add(f"{first_name_lower} {last_name_lower}")
    variants.add(f"{last_name_lower}, {first_name_lower}")
    variants.add(last_name_lower)

    if ' ' in first_name:
        parts = first_name.split()
        if len(parts) >= 2:
            fn_base = parts[0]
            fn_initial = parts[1][0] if len(parts) > 1 and parts[1] else ''
            variants.add(f"{fn_base} {fn_initial}. {last_name_lower}")
            variants.add(f"{fn_base} {last_name_lower}")
            variants.add(f"{last_name_lower}, {fn_base} {fn_initial}.")

    if first_name_lower and last_name_lower:
        fn_first_letter = first_name_lower[0]
        variants.add(f"{fn_first_letter}. {last_name_lower}")
        variants.add(f"{last_name_lower}, {fn_first_letter}.")

    original_input = f"{first_name} {last_name}".lower().strip()
    variants.add(original_input)

    return [v for v in variants if v]

def _find_section_blocks(text, section_headers=['adviser', 'panel', 'approved by', 'committee', 'signatures']):
    lines = text.split('\n')
    sections = {}
    current_section = 'intro'
    sections[current_section] = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            sections[current_section].append(line)
            continue

        found_header = False
        for header in section_headers:
            if re.search(rf'\b{re.escape(header)}\b', line_stripped, re.IGNORECASE):
                current_section = header
                sections[current_section] = [line]
                found_header = True
                break

        if not found_header:
            sections[current_section].append(line)

    final_sections = {name: '\n'.join(lines) for name, lines in sections.items()}
    return final_sections

def _extract_academic_year(text):
    ay_patterns = [
        r"(?P<ay>(?:AY|A\.Y\.)\s*(?P<start>\d{4})\s*[-–—]\s*(?P<end>\d{4}))",
        r"(?P<ay>(?P<start>\d{4})\s*[-–—]\s*(?P<end>\d{4}))",
        r"\bAY\s*(?P<start>\d{4})\b",
        r"\b(?P<ay>(?P<start>(?:2019|2020|2021|2022|2023|2024|2025))\b)",
    ]

    for pattern in ay_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start_year = match.group("start")
            end_year = match.group("end") if match.lastindex >= 3 else None

            if end_year:
                try:
                    start_int = int(start_year)
                    end_int = int(end_year)
                    if end_int == start_int + 1:
                        return f"{start_year}-{end_year}"
                except ValueError:
                    continue
            else:
                try:
                    start_int = int(start_year)
                    if 2019 <= start_int <= 2025:
                        return f"{start_int - 1}-{start_int}"
                except ValueError:
                    continue

    return None

def _extract_project_level(text):
    level_keywords = {
        'SP': [r'\bspecial\s+project\b'],
        'CP': [r'\bcapstone\s+project\b', r'\bcapstone\b', r'\bcp\b'],
        'UT': [r'\bundergraduate\s+thesis\b', r'\bundergraduate\b', r'\but\b', r'\bbscs\b'],
        'MT': [r'\bmaster[\'’]?\s*thesis\b', r'\bmaster[\'’]?\b', r'\bmt\b', r'\bmit\b'],
        'DD': [r'\bdissertation\b', r'\bdd\b', r'\bdoctoral\b'],
    }

    text_lower = text.lower()
    for level, keywords in level_keywords.items():
        for keyword_pattern in keywords:
            if re.search(keyword_pattern, text_lower):
                return level

    return None

def _find_name_near_role(text, faculty_name_variants, role_keywords):
    text_lower = text.lower()
    for variant in faculty_name_variants:
        variant_lower = variant.lower()
        name_matches = list(re.finditer(re.escape(variant_lower), text_lower))
        for match in name_matches:
            start_window = max(0, match.start() - 200)
            end_window = min(len(text_lower), match.end() + 200)
            context_snippet = text_lower[start_window:end_window]
            original_context_snippet = text[start_window:end_window]

            for role_keyword in role_keywords:
                if re.search(rf'\b{re.escape(role_keyword)}\b', context_snippet):
                    return variant, original_context_snippet

    return None, None