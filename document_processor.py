
import os
import sys
import json
import shutil
from pathlib import Path

import pymupdf
import pytesseract
from pytesseract import Output
from PIL import Image


# --------------------------------------------------
# TESSERACT CONFIGURATION
# --------------------------------------------------

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

if not shutil.which("tesseract"):
    for path in TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            break


# --------------------------------------------------
# OCR SETTINGS
# --------------------------------------------------

OCR_LOW_CONFIDENCE_LIMIT = 50
OCR_PAGE_WARNING_LIMIT = 60


# --------------------------------------------------
# DOCUMENT TYPE IDENTIFICATION
# --------------------------------------------------

def identify_document_type(text):

    text = text.lower()

    document_keywords = {
        "admission": [
            "admission note",
            "chief complaint",
            "date of admission",
            "admitting diagnosis",
        ],
        "laboratory": [
            "laboratory report",
            "lab report",
            "test result",
            "reference range",
            "specimen",
        ],
        "prescription": [
            "prescription",
            "prescribed",
            "dosage",
            "take one tablet",
            "medication order",
        ],
        "progress_note": [
            "progress note",
            "clinical progress",
            "daily assessment",
            "treatment plan",
        ],
        "discharge": [
            "discharge summary",
            "date of discharge",
            "discharge diagnosis",
            "discharge instructions",
        ],
    }

    scores = {}

    for document_type, keywords in document_keywords.items():
        scores[document_type] = sum(
            1 for keyword in keywords if keyword in text
        )

    best_type = max(scores, key=scores.get)

    if scores[best_type] == 0:
        return "unknown"

    return best_type


# --------------------------------------------------
# OCR WITH CONFIDENCE CHECKING
# --------------------------------------------------

def perform_ocr_with_quality(image):
    """
    Extract OCR text and calculate word recognition confidence.

    Original OCR text is preserved.
    Low-confidence words are flagged, never corrected.
    """

    try:

        text = pytesseract.image_to_string(
            image,
            lang="eng"
        )

        ocr_data = pytesseract.image_to_data(
            image,
            lang="eng",
            output_type=Output.DICT
        )

        confidence_values = []
        low_confidence_words = []

        for index, word in enumerate(ocr_data["text"]):

            word = word.strip()

            if not word:
                continue

            try:
                confidence = float(
                    ocr_data["conf"][index]
                )
            except (ValueError, TypeError):
                continue

            if confidence < 0:
                continue

            confidence_values.append(confidence)

            if confidence < OCR_LOW_CONFIDENCE_LIMIT:
                low_confidence_words.append({
                    "word": word,
                    "confidence": round(confidence, 2)
                })

        if confidence_values:

            average_confidence = round(
                sum(confidence_values) / len(confidence_values),
                2
            )

        else:
            average_confidence = None

        warnings = []

        if average_confidence is None:

            warnings.append(
                "OCR confidence could not be calculated. "
                "Manual review is recommended."
            )

        elif average_confidence < OCR_PAGE_WARNING_LIMIT:

            warnings.append(
                "Low average OCR confidence. "
                "Please manually verify extracted information."
            )

        if low_confidence_words:

            warnings.append(
                "Some words have low OCR recognition confidence. "
                "Check patient IDs, dates, diagnoses and medicines "
                "against the original document."
            )

        return {
            "text": text,
            "ocr_confidence": average_confidence,
            "ocr_low_confidence_words": low_confidence_words,
            "quality_warnings": warnings
        }

    except pytesseract.TesseractNotFoundError:

        raise RuntimeError(
            "Tesseract OCR is not installed or configured. "
            "Install Tesseract OCR separately to process "
            "scanned PDFs and images."
        )


def perform_ocr(image):
    """
    Compatibility helper.
    Returns only OCR text, as the earlier version did.
    """

    result = perform_ocr_with_quality(image)

    return result["text"]


# --------------------------------------------------
# PDF PROCESSING
# --------------------------------------------------

def process_pdf(file_path):

    pages = []

    pdf = pymupdf.open(file_path)

    try:

        for page_number, page in enumerate(pdf, start=1):

            text = page.get_text("text").strip()

            extraction_method = "pymupdf"

            page_result = {
                "page_number": page_number,
                "text": text,
                "extraction_method": extraction_method
            }

            # Use OCR when the page contains very little text.
            if len(text) < 20:

                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    alpha=False
                )

                image = Image.frombytes(
                    "RGB",
                    [pix.width, pix.height],
                    pix.samples
                )

                ocr_result = perform_ocr_with_quality(image)

                page_result["text"] = ocr_result["text"].strip()
                page_result["extraction_method"] = "ocr"
                page_result["ocr_confidence"] = (
                    ocr_result["ocr_confidence"]
                )
                page_result["ocr_low_confidence_words"] = (
                    ocr_result["ocr_low_confidence_words"]
                )
                page_result["quality_warnings"] = (
                    ocr_result["quality_warnings"]
                )

            pages.append(page_result)

    finally:
        pdf.close()

    return pages


# --------------------------------------------------
# IMAGE PROCESSING
# --------------------------------------------------

def process_image(file_path):

    with Image.open(file_path) as image:

        ocr_result = perform_ocr_with_quality(image)

    return [{
        "page_number": 1,
        "text": ocr_result["text"].strip(),
        "extraction_method": "ocr",
        "ocr_confidence": ocr_result["ocr_confidence"],
        "ocr_low_confidence_words": (
            ocr_result["ocr_low_confidence_words"]
        ),
        "quality_warnings": ocr_result["quality_warnings"]
    }]


# --------------------------------------------------
# COMPLETE DOCUMENT PROCESSING
# --------------------------------------------------

def process_document(file_path):

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    supported_images = {
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".bmp"
    }

    extension = path.suffix.lower()

    if extension == ".pdf":
        pages = process_pdf(path)

    elif extension in supported_images:
        pages = process_image(path)

    else:
        raise ValueError(
            "Unsupported file format. "
            "Please provide a PDF or image."
        )

    full_text = "\n".join(
        page["text"] for page in pages
    )

    result = {
        "patient_id": None,
        "document_id": None,
        "document_name": path.name,
        "document_type": identify_document_type(full_text),
        "pages": pages,
        "events": []
    }

    return result


# --------------------------------------------------
# RUN FROM TERMINAL
# --------------------------------------------------

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            "Usage: python backend/document_processor.py <file_path>"
        )

        sys.exit(1)

    input_file = sys.argv[1]

    try:

        output = process_document(input_file)

        print(
            json.dumps(
                output,
                indent=4,
                ensure_ascii=False
            )
        )

    except Exception as error:

        print(f"Error: {error}")
