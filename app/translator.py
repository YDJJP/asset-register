import re
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone

# Built-in industry standard default abbreviations
DEFAULT_TRANSLATIONS: Dict[str, str] = {
    "CPR": "Capper",
    "PU": "Pump",
    "LBL": "Labeller",
    "VLV": "Valve",
    "VAL": "Valve",
    "MOT": "Motor",
    "MTR": "Motor",
    "CV": "Conveyor",
    "CONV": "Conveyor",
    "TNK": "Tank",
    "TK": "Tank",
    "FIL": "Filler",
    "FL": "Filler",
    "SEN": "Sensor",
    "PLC": "PLC",
    "FAN": "Fan",
    "CYL": "Cylinder",
    "ENG": "Engine",
    "ROB": "Robot",
}

def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_asset_id(asset_id: str) -> Tuple[str, str, str]:
    """
    Splits an Asset ID into (prefix, delimiter, suffix).
    Examples:
      'CPR001'    -> ('CPR', '', '001')
      'PU.023'    -> ('PU', '.', '023')
      'pu023'     -> ('PU', '', '023')
      'LBL-02'    -> ('LBL', '-', '02')
      'Line 2'    -> ('LINE', ' ', '2')
      'PUMP'      -> ('PUMP', '', '')
      '12345'     -> ('', '', '12345')
    """
    s = (asset_id or "").strip()
    if not s:
        return "", "", ""

    # Match leading English letters, optional separators, and trailing content (digits/letters)
    m = re.match(r'^([a-zA-Z]+)([\s._\-/]*)(.*)$', s)
    if m:
        prefix = m.group(1).upper()
        delimiter = m.group(2)
        suffix = m.group(3).strip()
        return prefix, delimiter, suffix
    return "", "", s


def translate_asset_id(asset_id: str, db_conn=None) -> Tuple[str, str]:
    """
    Translates an asset ID into a human-friendly name candidate.
    e.g.
      'CPR001' -> ('Capper 001', 'CPR -> Capper')
      'PU.023' -> ('Pump 023', 'PU -> Pump')
      'LBL02'  -> ('Labeller 02', 'LBL -> Labeller')
    Returns: (translated_name, rule_description)
    """
    prefix, delimiter, suffix = parse_asset_id(asset_id)
    if not prefix:
        return "", ""

    mapping_name = None

    # 1. First check user-learned and saved database rules
    if db_conn is not None:
        try:
            cur = db_conn.cursor()
            cur.execute("SELECT name_prefix FROM id_translations WHERE prefix = ?", (prefix,))
            row = cur.fetchone()
            if row:
                mapping_name = row["name_prefix"]
        except Exception as e:
            print(f"[Translator] DB lookup error: {e}")

    # 2. Check built-in dictionary
    if not mapping_name and prefix in DEFAULT_TRANSLATIONS:
        mapping_name = DEFAULT_TRANSLATIONS[prefix]

    if not mapping_name:
        return "", ""

    # Combine with suffix
    if suffix:
        clean_suffix = suffix.lstrip('._- ')
        translated = f"{mapping_name} {clean_suffix}".strip()
    else:
        translated = mapping_name

    return translated, f"{prefix} -> {mapping_name}"


def learn_translation(asset_id: str, asset_name: str, db_conn) -> Optional[Dict[str, Any]]:
    """
    Self-learning engine:
    When a user manually creates or edits an asset, extracts naming patterns
    and records them into id_translations so subsequent assets with the same
    prefix are automatically recognized and translated.

    e.g.
      ID: 'CPR001', Name: 'capper 001' -> learns 'CPR' -> 'capper' (or 'Capper')
      ID: 'PU.023', Name: '高压冲洗泵 023' -> learns 'PU' -> '高压冲洗泵'
    """
    if not asset_id or not asset_name or not db_conn:
        return None

    prefix, delimiter, suffix = parse_asset_id(asset_id)
    if not prefix or len(prefix) < 1 or len(prefix) > 20:
        return None

    # Don't learn from generic auto-generated ID prefix 'AST'
    if prefix == "AST":
        return None

    name = asset_name.strip()
    if not name:
        return None

    # Determine base name template by stripping suffix from name if present
    clean_suffix = suffix.lstrip('._- ')
    base_name = name
    if clean_suffix and clean_suffix in name:
        idx = name.rfind(clean_suffix)
        candidate_base = name[:idx].strip().rstrip('._-/:')
        if candidate_base and len(candidate_base) >= 2:
            base_name = candidate_base

    now = get_now_iso()
    try:
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO id_translations (prefix, name_prefix, example_id, example_name, is_system, updated_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(prefix) DO UPDATE SET
                name_prefix = excluded.name_prefix,
                example_id = excluded.example_id,
                example_name = excluded.example_name,
                updated_at = excluded.updated_at
        """, (prefix, base_name, asset_id, asset_name, now))
        return {
            "prefix": prefix,
            "name_prefix": base_name,
            "example_id": asset_id,
            "example_name": asset_name,
        }
    except Exception as e:
        print(f"[Translator] Failed to learn translation: {e}")
        return None
