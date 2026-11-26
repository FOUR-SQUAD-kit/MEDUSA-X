
import re
import json
import sys
from pathlib import Path

from document_processor import process_document


# --------------------------------------------------
# 1. TEXT AND DATE HELPERS
# --------------------------------------------------

def clean_line(line):
    """Remove Markdown formatting without changing the text."""

    line = re.sub(r"[*#`]", "", line)
    return line.strip()


def convert_date(date_text):

    if not date_text:
        return None

    from datetime import datetime

    date_text = date_text.strip()

    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                date_text, fmt
            ).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def find_date(text):

    if not text:
        return None

    patterns = [
        r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b"
    ]

    for pattern in patterns:
        match = re.search(
            pattern, text, re.IGNORECASE
        )

        if match:
            return convert_date(match.group(0))

    return None


# --------------------------------------------------
# 2. DOCUMENT SECTION HELPERS
# --------------------------------------------------

SECTION_NAMES = [
    "Date of Admission",
    "Admission Medication",
    "Admission Date",
    "Initial Diagnosis",
    "Laboratory Findings",
    "Laboratory Finding",
    "Laboratory Result",
    "Discharge Summary",
    "Progress Note",
    "Doctor's Notes",
    "Medical History",
    "Final Diagnosis",
    "Patient Name",
    "Patient ID",
    "Chief Complaint",
    "Lab Findings",
    "Lab Finding",
    "Lab Result",
    "Diagnosis",
    "Treatment",
    "Hospital",
    "Age"
]


def parse_section_line(line):
    """
    Identify a section heading or an inline section value.

    Examples:
    Progress Note — 21 November 2026:
    Initial Diagnosis: Suspected bacterial pneumonia.
    """

    cleaned = clean_line(line)

    for label in sorted(SECTION_NAMES, key=len, reverse=True):

        pattern = (
            r"^" + re.escape(label)
            + r"\b\s*(.*?)\s*$"
        )

        match = re.match(
            pattern, cleaned, re.IGNORECASE
        )

        if not match:
            continue

        remainder = match.group(1).strip()

        # Inline value after a colon.
        if remainder.startswith(":"):
            value = remainder[1:].strip()

            return {
                "label": label,
                "heading": cleaned,
                "value": value,
                "is_heading": False
            }

        # Heading with an optional date or dash.
        if remainder == "":
            return {
                "label": label,
                "heading": cleaned,
                "value": "",
                "is_heading": True
            }

        if re.match(r"^[—-]\s*.*:?$", remainder):
            return {
                "label": label,
                "heading": cleaned,
                "value": "",
                "is_heading": True
            }

    return None


def is_section_heading(line):

    parsed = parse_section_line(line)

    return (
        parsed is not None
        and parsed["is_heading"]
    )


def get_section_value(text, labels):
    """
    Extract a section's content.
    Stop when the next recognized section begins.
    """

    lines = text.splitlines()

    for index, line in enumerate(lines):

        parsed = parse_section_line(line)

        if not parsed:
            continue

        if parsed["label"].lower() not in [
            label.lower() for label in labels
        ]:
            continue

        values = []

        if parsed["value"]:
            values.append(parsed["value"])

        for next_line in lines[index + 1:]:

            next_cleaned = clean_line(next_line)

            if not next_cleaned:
                continue

            if parse_section_line(next_cleaned):
                break

            values.append(next_cleaned)

        value = " ".join(values).strip()

        if value:
            return value, parsed["heading"]

    return None, None


# --------------------------------------------------
# 3. MEDICATION EXTRACTION
# --------------------------------------------------

def extract_medication_events(pages):

    events = []

    medicine_pattern = re.compile(
        r"\bMedicine\s+[A-Z0-9]+\b|"
        r"\bAntibiotic\s+[A-Z0-9]+\b",
        re.IGNORECASE
    )

    dosage_pattern = re.compile(
        r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\b",
        re.IGNORECASE
    )

    for page in pages:

        page_number = page.get("page_number", 1)
        lines = page.get("text", "").splitlines()

        current_section_date = None

        for index, line in enumerate(lines):

            cleaned = clean_line(line)

            if not cleaned:
                continue

            parsed = parse_section_line(cleaned)

            # Update the date when entering a dated section.
            if parsed and parsed["is_heading"]:

                if parsed["label"].lower() in [
                    "progress note",
                    "discharge summary"
                ]:
                    current_section_date = find_date(
                        parsed["heading"]
                    )

                continue

            # Do not treat verification instructions as medication events.
            if re.search(
                r"restart instructions|clinician verification",
                cleaned,
                re.IGNORECASE
            ):
                continue

            medicines = medicine_pattern.findall(cleaned)

            if not medicines:
                continue

            # Join a wrapped sentence when the next line
            # clearly completes the unfinished phrase.
            evidence = cleaned

            if re.search(r"\bnot\s*$", cleaned, re.IGNORECASE):

                if index + 1 < len(lines):

                    next_line = clean_line(lines[index + 1])

                    if re.match(
                        r"^(documented|available|specified)\b",
                        next_line,
                        re.IGNORECASE
                    ):
                        evidence += " " + next_line

            for medicine in medicines:

                dosage_match = dosage_pattern.search(evidence)

                dosage = (
                    dosage_match.group(1)
                    if dosage_match else None
                )

                unit = (
                    dosage_match.group(2).lower()
                    if dosage_match else None
                )

                if re.search(
                    r"temporarily withheld|withheld",
                    evidence, re.IGNORECASE
                ):
                    action = "temporarily_withheld"

                elif re.search(
                    r"\bstopped\b|\bdiscontinued\b",
                    evidence, re.IGNORECASE
                ):
                    action = "stopped"

                elif re.search(
                    r"\bstarted\b|\bprescribed\b",
                    evidence, re.IGNORECASE
                ):
                    action = "started"

                elif re.search(
                    r"\bchanged\b|\badjusted\b",
                    evidence, re.IGNORECASE
                ):
                    action = "changed"

                elif re.search(
                    r"\bcontinued\b",
                    evidence, re.IGNORECASE
                ):
                    action = "continued"

                else:
                    action = "unknown"

                if re.search(
                    r"historical|previously|past prescription",
                    evidence,
                    re.IGNORECASE
                ):
                    status = "historical"
                else:
                    status = "documented"

                events.append({
                    "event_type": "medication",
                    "medication_name": medicine,
                    "dosage": dosage,
                    "unit": unit,
                    "frequency": None,
                    "action": action,
                    "event_date": (
                        find_date(evidence)
                        or current_section_date
                    ),
                    "recorded_date": None,
                    "source_page": page_number,
                    "evidence": evidence,
                    "status": status
                })

    return events


# --------------------------------------------------
# 4. MAIN INFORMATION EXTRACTION
# --------------------------------------------------

def extract_information(document):

    pages = document.get("pages", [])

    full_text = "\n".join(
        page.get("text", "")
        for page in pages
    )

    cleaned_text = "\n".join(
        clean_line(line)
        for line in full_text.splitlines()
    )

    events = []

    # Patient ID
    patient_match = re.search(
        r"\bPatient\s*ID\s*:\s*([A-Za-z0-9_-]+)",
        cleaned_text,
        re.IGNORECASE
    )

    patient_id = (
        patient_match.group(1)
        if patient_match else None
    )

    # Document ID
    document_match = re.search(
        r"\bDocument\s*ID\s*:\s*([A-Za-z0-9_-]+)",
        cleaned_text,
        re.IGNORECASE
    )

    document_id = (
        document_match.group(1)
        if document_match else None
    )

    # Admission date
    admission_text, _ = get_section_value(
        cleaned_text,
        ["Date of Admission", "Admission Date"]
    )

    admission_date = find_date(admission_text or "")

    # Initial diagnosis
    diagnosis_text, diagnosis_heading = get_section_value(
        cleaned_text,
        ["Initial Diagnosis", "Final Diagnosis", "Diagnosis"]
    )

    if diagnosis_text:

        events.append({
            "event_type": "diagnosis",
            "value": diagnosis_text,
            "event_date": (
                find_date(diagnosis_text)
                or admission_date
            ),
            "recorded_date": None,
            "source_page": 1,
            "evidence": (
                (diagnosis_heading or "")
                + " " + diagnosis_text
            ).strip(),
            "status": "documented"
        })

    # Laboratory findings
    lab_text, lab_heading = get_section_value(
        cleaned_text,
        [
            "Laboratory Findings",
            "Laboratory Finding",
            "Lab Findings",
            "Lab Finding",
            "Lab Result",
            "Laboratory Result"
        ]
    )

    if lab_text:

        events.append({
            "event_type": "lab_finding",
            "value": lab_text,
            "event_date": find_date(lab_text),
            "recorded_date": None,
            "source_page": 1,
            "evidence": (
                (lab_heading or "")
                + " " + lab_text
            ).strip(),
            "status": "documented"
        })

    # Progress note
    progress_text, progress_heading = get_section_value(
        cleaned_text,
        ["Progress Note"]
    )

    if progress_text:

        events.append({
            "event_type": "clinical_update",
            "value": progress_text,
            "event_date": (
                find_date(progress_text)
                or find_date(progress_heading or "")
            ),
            "recorded_date": None,
            "source_page": 1,
            "evidence": (
                (progress_heading or "")
                + " " + progress_text
            ).strip(),
            "status": "documented"
        })

    # Discharge summary
    discharge_text, discharge_heading = get_section_value(
        cleaned_text,
        ["Discharge Summary"]
    )

    if discharge_text:

        events.append({
            "event_type": "discharge",
            "value": discharge_text,
            "event_date": (
                find_date(discharge_text)
                or find_date(discharge_heading or "")
            ),
            "recorded_date": None,
            "source_page": 1,
            "evidence": (
                (discharge_heading or "")
                + " " + discharge_text
            ).strip(),
            "status": "documented"
        })

    # Medication events
    events.extend(
        extract_medication_events(pages)
    )

    # Medication verification warning
    verification_match = re.search(
        r"restart instructions[\s\S]{0,150}?not available|"
        r"clinician verification required",
        full_text,
        re.IGNORECASE
    )

    if verification_match:

        medicine_match = re.search(
            r"\b(?:Medicine|Antibiotic)\s+[A-Z0-9]+\b",
            full_text,
            re.IGNORECASE
        )

        events.append({
            "event_type": "medication_verification",
            "medication_name": (
                medicine_match.group(0)
                if medicine_match else None
            ),
            "value": "Restart instructions unavailable",
            "event_date": None,
            "recorded_date": None,
            "source_page": 1,
            "evidence": verification_match.group(0),
            "status": "pending_verification"
        })

    return {
        "patient_id": patient_id,
        "document_id": document_id,
        "document_name": document.get("document_name"),
        "document_type": document.get("document_type"),
        "events": events
    }


# --------------------------------------------------
# 5. RUN EXTRACTOR
# --------------------------------------------------

def main():

    if len(sys.argv) < 2:

        print(
            "Usage: python backend/extractor.py <file_path>"
        )

        return

    file_path = Path(sys.argv[1])

    if not file_path.exists():

        print(f"Error: File not found: {file_path}")

        return

    try:

        document = process_document(str(file_path))

        result = extract_information(document)

        print(
            json.dumps(
                result,
                indent=4,
                ensure_ascii=False
            )
        )

    except Exception as error:

        print(f"Error processing document: {error}")


if __name__ == "__main__":
    main()
