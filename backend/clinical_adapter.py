from typing import Any


def _combine_dose(dosage: Any, unit: Any) -> str | None:
    if dosage is None or not str(dosage).strip():
        return None

    dose = str(dosage).strip()

    if unit is not None and str(unit).strip():
        dose = f"{dose} {str(unit).strip()}"

    return dose


def adapt_extraction(extraction: dict) -> dict:
    """
    Convert Meghana's flat extraction output into the document structure
    expected by Prajwal's timeline and reconciliation modules.

    Original supporting events and quality warnings are preserved separately.
    No missing clinical information is inferred.
    """
    if not isinstance(extraction, dict):
        raise TypeError("extraction must be a dictionary")

    patient_id = extraction.get("patient_id")

    if not patient_id:
        raise ValueError("Patient ID is missing from extraction")

    diagnoses = []
    medications = []
    tests = []
    supporting_events = []
    other_events = []

    for event in extraction.get("events", []):
        if not isinstance(event, dict):
            continue

        event_type = event.get("event_type")

        common = {
            "event_date": event.get("event_date"),
            "recorded_date": event.get("recorded_date"),
            "page": event.get("source_page"),
            "evidence": event.get("evidence"),
        }

        if event_type == "diagnosis":
            diagnoses.append({
                **common,
                "name": event.get("value"),
                "status": event.get("status"),
                "changed_from": event.get("changed_from"),
            })

        elif event_type == "lab_finding":
            tests.append({
                **common,
                "name": "Laboratory finding",
                "result": event.get("value"),
            })

        elif event_type == "medication":
            context = (
                "historical"
                if str(event.get("status", "")).lower() == "historical"
                else None
            )

            medications.append({
                **common,
                "name": event.get("medication_name"),
                "dose": _combine_dose(
                    event.get("dosage"),
                    event.get("unit")
                ),
                "frequency": event.get("frequency"),
                "action": event.get("action"),
                "context": context,
                "restart_info": event.get("restart_info"),
            })

        elif event_type in (
            "clinical_update",
            "discharge",
            "medication_verification",
        ):
            supporting_events.append(dict(event))

        else:
            other_events.append(dict(event))

    document = {
        "document_name": extraction.get("document_name"),
        "document_type": extraction.get("document_type"),
        "recorded_date": None,
        "diagnoses": diagnoses,
        "medications": medications,
        "tests": tests,
    }

    return {
        "patient": {
            "patient_id": patient_id,
            "patient_name": extraction.get("patient_name"),
        },
        "documents": [document],
        "supporting_events": supporting_events,
        "other_events": other_events,
        "quality_warnings": extraction.get("quality_warnings", []),
    }
