# backend/api/services/analysis_engine.py

import pandas as pd
from googleapiclient.discovery import build
from django.conf import settings
import re

# =========================================================
# CONFIGURATION: NBC 461 RULES
# =========================================================

# Table 2.2 KRA Weights per Faculty Rank (NBC 461 C9)
NBC_461_WEIGHTS = {
    "Instructor":           {"KRA I": 0.60, "KRA II": 0.10, "KRA III": 0.20, "KRA IV": 0.10},
    "Assistant Professor":  {"KRA I": 0.50, "KRA II": 0.20, "KRA III": 0.20, "KRA IV": 0.10},
    "Associate Professor":  {"KRA I": 0.40, "KRA II": 0.30, "KRA III": 0.20, "KRA IV": 0.10},
    "Professor":            {"KRA I": 0.30, "KRA II": 0.40, "KRA III": 0.20, "KRA IV": 0.10},
    "College/University Professor": {"KRA I": 0.20, "KRA II": 0.50, "KRA III": 0.20, "KRA IV": 0.10}
}

# Table 3.2 Faculty Positions in SUCs (Ordered)
RANK_HIERARCHY = [
    "Instructor I", "Instructor II", "Instructor III",
    "Assistant Professor I", "Assistant Professor II", "Assistant Professor III", "Assistant Professor IV",
    "Associate Professor I", "Associate Professor II", "Associate Professor III", "Associate Professor IV", "Associate Professor V",
    "Professor I", "Professor II", "Professor III", "Professor IV", "Professor V", "Professor VI",
    "College/University Professor"
]

CAPS = {"KRA I": 100, "KRA II": 100, "KRA III": 100, "KRA IV": 100}

def get_google_sheet_client():
    return build('sheets', 'v4', developerKey=settings.GOOGLE_API_KEY)

def clean_score(value):
    try:
        if not value: return 0.0
        return float(str(value).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0

def get_major_rank(rank_str):
    """Extracts 'Instructor', 'Assistant Professor', etc. from 'Instructor I'"""
    if not rank_str: return "Instructor" # Default
    for key in NBC_461_WEIGHTS.keys():
        if rank_str.startswith(key):
            return key
    return "Instructor" # Fallback

def get_next_major_rank(current_major_rank):
    keys = list(NBC_461_WEIGHTS.keys())
    try:
        idx = keys.index(current_major_rank)
        if idx + 1 < len(keys):
            return keys[idx + 1]
    except ValueError:
        pass
    return current_major_rank

def calculate_increments(score):
    """Table 3.1 Score Bracket and Sub-rank Increment"""
    if score >= 91: return 6
    if score >= 81: return 5
    if score >= 71: return 4
    if score >= 61: return 3
    if score >= 51: return 2
    if score >= 41: return 1
    return 0

def get_promotion_projection(current_rank_str, weighted_score, raw_scores):
    """
    Calculates the projected rank based on NBC 461 rules, 
    including the re-computation rule for crossing ranks.
    """
    if current_rank_str not in RANK_HIERARCHY:
        current_rank_str = RANK_HIERARCHY[0] # Default to lowest if invalid

    current_idx = RANK_HIERARCHY.index(current_rank_str)
    
    # 1. Determine Increments based on Current Rank Weights
    increments = calculate_increments(weighted_score)
    
    # 2. Project Initial New Index
    projected_idx = current_idx + increments
    
    # 3. Check for Rank Crossing (e.g., Instructor III -> Asst Prof I)
    current_major = get_major_rank(current_rank_str)
    
    # Find the boundary of the current major rank
    max_idx_current_major = current_idx
    for i in range(current_idx, len(RANK_HIERARCHY)):
        if get_major_rank(RANK_HIERARCHY[i]) == current_major:
            max_idx_current_major = i
        else:
            break
            
    # Logic: If we cross the boundary, we must re-compute using Next Rank's weights
    final_projected_rank = ""
    promotion_status = ""
    recomputed_score = 0.0
    
    if projected_idx > max_idx_current_major:
        # We are crossing to the next major rank
        next_major = get_next_major_rank(current_major)
        next_weights = NBC_461_WEIGHTS[next_major]
        
        # Re-compute Score
        recomputed_score = (
            (raw_scores["KRA I"] * next_weights["KRA I"]) +
            (raw_scores["KRA II"] * next_weights["KRA II"]) +
            (raw_scores["KRA III"] * next_weights["KRA III"]) +
            (raw_scores["KRA IV"] * next_weights["KRA IV"])
        )
        
        # Check if they qualify for the next rank (Min 41 pts usually required to move)
        # NBC 461 8.3: "If faculty qualifies for next rank... if not, highest sub-rank of current."
        if calculate_increments(recomputed_score) >= 1: # Assuming 1 increment allows entry
             # Find the start of the next major rank
             final_projected_rank = RANK_HIERARCHY[max_idx_current_major + 1]
             promotion_status = f"Promoted to {final_projected_rank} (Cross-Rank Qualified)"
             final_score_display = recomputed_score
        else:
             # Capped at highest of current
             final_projected_rank = RANK_HIERARCHY[max_idx_current_major]
             promotion_status = f"Capped at {final_projected_rank} (Did not meet {next_major} threshold)"
             final_score_display = weighted_score
    else:
        # Normal increment within rank
        if projected_idx >= len(RANK_HIERARCHY):
            projected_idx = len(RANK_HIERARCHY) - 1
        
        final_projected_rank = RANK_HIERARCHY[projected_idx]
        final_score_display = weighted_score
        if increments > 0:
            promotion_status = f"+{increments} Sub-ranks"
        else:
            promotion_status = "No Movement (< 41 pts)"

    # Calculate Gap to next Bracket
    # Brackets: 41, 51, 61, 71, 81, 91
    brackets = [41, 51, 61, 71, 81, 91]
    next_bracket = next((b for b in brackets if b > final_score_display), None)
    points_to_next = next_bracket - final_score_display if next_bracket else 0

    return {
        "current_rank": current_rank_str,
        "projected_rank": final_projected_rank,
        "increments": increments,
        "weighted_score": final_score_display,
        "points_to_next_bracket": points_to_next,
        "status_message": promotion_status
    }

def fetch_range_data(service, spreadsheet_id, range_name):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_name
        ).execute()
        return result.get('values', [])
    except Exception as e:
        print(f"Error fetching range {range_name}: {e}")
        return []

# =========================================================
# MAIN ANALYZER FUNCTION
# =========================================================

def analyze_faculty_performance(sheet_url, current_rank="Instructor I"):
    """
    Analyzes performance with Rank-Aware weighting.
    """
    if not sheet_url or "docs.google.com" not in sheet_url:
        return {"error": "Invalid URL"}

    try:
        spreadsheet_id = sheet_url.split('/d/')[1].split('/')[0]
    except IndexError:
        return {"error": "Could not parse Spreadsheet ID"}

    service = get_google_sheet_client()
    
    # FETCH DATA (Same range as before)
    range_name = "'ISS-FACULTY'!P10:P30" 
    raw_data = fetch_range_data(service, spreadsheet_id, range_name)
    
    scores = {
        "KRA I": {"A": 0, "B": 0, "C": 0, "Total": 0},
        "KRA II": {"A": 0, "B": 0, "C": 0, "Total": 0},
        "KRA III": {"A": 0, "B": 0, "C": 0, "D": 0, "Total": 0},
        "KRA IV": {"A": 0, "B": 0, "C": 0, "D": 0, "Total": 0}
    }

    if raw_data:
        try:
            # Parsing logic remains same...
            scores["KRA I"]["A"] = clean_score(raw_data[0][0])
            scores["KRA I"]["B"] = clean_score(raw_data[1][0])
            scores["KRA I"]["C"] = clean_score(raw_data[2][0])
            scores["KRA I"]["Total"] = clean_score(raw_data[3][0])

            scores["KRA II"]["A"] = clean_score(raw_data[5][0])
            scores["KRA II"]["B"] = clean_score(raw_data[6][0])
            scores["KRA II"]["C"] = clean_score(raw_data[7][0])
            scores["KRA II"]["Total"] = clean_score(raw_data[8][0])

            scores["KRA III"]["A"] = clean_score(raw_data[10][0])
            scores["KRA III"]["B"] = clean_score(raw_data[11][0])
            scores["KRA III"]["C"] = clean_score(raw_data[12][0])
            scores["KRA III"]["D"] = clean_score(raw_data[13][0])
            scores["KRA III"]["Total"] = clean_score(raw_data[14][0])

            scores["KRA IV"]["A"] = clean_score(raw_data[16][0])
            scores["KRA IV"]["B"] = clean_score(raw_data[17][0])
            scores["KRA IV"]["C"] = clean_score(raw_data[18][0])
            scores["KRA IV"]["D"] = clean_score(raw_data[19][0])
            scores["KRA IV"]["Total"] = clean_score(raw_data[20][0])

        except (IndexError, ValueError) as e:
            print(f"Mapping Error: {e}")

    # =========================================================
    # NEW: WEIGHTED CALCULATION
    # =========================================================
    major_rank = get_major_rank(current_rank)
    weights = NBC_461_WEIGHTS.get(major_rank, NBC_461_WEIGHTS["Instructor"])

    raw_totals = {
        "KRA I": scores["KRA I"]["Total"],
        "KRA II": scores["KRA II"]["Total"],
        "KRA III": scores["KRA III"]["Total"],
        "KRA IV": scores["KRA IV"]["Total"],
    }

    # Calculate Weighted Score
    final_score = sum(raw_totals[kra] * weights[kra] for kra in raw_totals)

    # Determine Promotion Status
    promotion_data = get_promotion_projection(current_rank, final_score, raw_totals)

    return {
        "summary": scores,
        "caps": CAPS,
        "weights_used": weights, # Sending back weights so UI knows the multipliers
        "promotion": promotion_data,
        "raw_totals": raw_totals
    }