import re
import io
from typing import Dict, Any, List, Optional
from PIL import Image, ImageOps
import numpy as np

# Lazy global OCR engine instance to avoid cold-start overhead per request
_ocr_engine = None

def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception as e:
            print(f"[Recognizer] RapidOCR init error: {e}")
            _ocr_engine = False
    return _ocr_engine if _ocr_engine is not False else None


def clean_id_candidate(text: str) -> Optional[str]:
    """
    Cleans up candidate text:
    - Strips common prefixes like 'ID:', 'S/N:', 'SN:', 'NO:', 'P/N:', 'TAG:'
    - Removes trailing punctuation and invalid characters
    """
    t = text.strip()
    if not t:
        return None

    # Check for prefix stripping
    prefix_patterns = [
        r'^(?:ID|I\.D\.|资产编号|编号|条形码|SN|S/N|SERIAL|SERIAL NO\.?|NO|NO\.|PN|P/N|TAG|TAG NO\.?)[:：\s_-]+(.+)$',
    ]
    for pattern in prefix_patterns:
        m = re.match(pattern, t, re.IGNORECASE)
        if m:
            t = m.group(1).strip()
            break

    # Strip wrapping quotes, brackets, colons
    t = t.strip("\"'[](){}:;，。")
    if len(t) < 2 or len(t) > 60:
        return None
    return t


def score_candidate(candidate: str, conf: float, is_barcode: bool = False) -> float:
    """
    Heuristic scoring to pick the most likely Asset ID:
    - Barcodes get highest priority.
    - Alphanumeric strings with dots/hyphens (e.g. PU.023, AST-2026, C02G1234) score high.
    - Descriptive words (Line, ONLY, Warning, Caution, Made in, etc.) are down-weighted.
    """
    if is_barcode:
        return 100.0 + conf * 10

    score = conf * 10.0
    cand_len = len(candidate)

    # Ideal ID length: 3 to 20 chars
    if 3 <= cand_len <= 20:
        score += 4.0
    elif cand_len > 30:
        score -= 4.0

    has_alpha = any(c.isalpha() for c in candidate)
    has_digit = any(c.isdigit() for c in candidate)

    # Mixed letters and numbers (e.g., PU.023, AST01)
    if has_alpha and has_digit:
        score += 6.0
    elif has_digit and not has_alpha:
        # Pure numeric (e.g. 100234)
        score += 3.0

    # Punctuation commonly used in asset tags (., -, _, /)
    if any(c in '.-_/' for c in candidate):
        score += 3.0

    # All-uppercase letters or capitalized tokens are standard for tags
    if candidate.isupper():
        score += 2.0

    # Down-weight common instructional or secondary label text
    lower = candidate.lower()
    penalties = [
        'only', 'line', 'warning', 'caution', 'danger', 'notice',
        'made in', 'date', 'type', 'voltage', 'model', 'hz', 'vac'
    ]
    for p in penalties:
        if p in lower:
            score -= 5.0

    return score


def recognize_asset_id_from_image(image_bytes: bytes) -> Dict[str, Any]:
    """
    Analyzes an uploaded image and extracts candidate Asset IDs:
    1. Checks for 1D/2D barcodes (QR, Code128, Code39, DataMatrix) via zxing-cpp.
    2. Runs high-accuracy OCR via RapidOCR (ONNX).
    3. Ranks candidates and returns the best matching Asset ID along with alternatives.
    """
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
    except Exception as e:
        return {
            "success": False,
            "error": f"无法读取图片数据: {str(e)}",
            "best_id": "",
            "candidates": [],
            "details": [],
        }

    detected_items: List[Dict[str, Any]] = []
    seen_texts = set()

    # 1. Barcode & QR Code Recognition (Fast & High Precision)
    try:
        import zxingcpp
        barcodes = zxingcpp.read_barcodes(pil_img)
        for b in barcodes:
            raw_text = (b.text or "").strip()
            if raw_text and raw_text not in seen_texts:
                seen_texts.add(raw_text)
                detected_items.append({
                    "text": raw_text,
                    "type": "barcode",
                    "format": str(b.format),
                    "confidence": 1.0,
                    "score": score_candidate(raw_text, 1.0, is_barcode=True),
                })
    except Exception as e:
        print(f"[Recognizer] Barcode scanning error: {e}")

    # 2. Optical Character Recognition (OCR)
    ocr_engine = get_ocr_engine()
    if ocr_engine:
        try:
            # Convert PIL Image to RGB Numpy Array
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            np_img = np.array(pil_img)

            ocr_results, _ = ocr_engine(np_img)
            if ocr_results:
                for item in ocr_results:
                    raw_text = item[1]
                    conf = float(item[2])
                    cleaned = clean_id_candidate(raw_text)
                    if cleaned and cleaned not in seen_texts and conf >= 0.5:
                        seen_texts.add(cleaned)
                        detected_items.append({
                            "text": cleaned,
                            "raw_text": raw_text,
                            "type": "ocr",
                            "confidence": round(conf, 4),
                            "score": score_candidate(cleaned, conf, is_barcode=False),
                        })
        except Exception as e:
            print(f"[Recognizer] OCR execution error: {e}")

    # Sort candidates by calculated score descending
    detected_items.sort(key=lambda x: x["score"], reverse=True)

    candidates = [item["text"] for item in detected_items]
    best_id = candidates[0] if candidates else ""

    return {
        "success": True,
        "best_id": best_id,
        "candidates": candidates[:6],  # Top 6 candidate tags
        "details": detected_items[:10],
    }
