import json
from pathlib import Path

from backend.rag_engine import rag_engine


def index_extraction(extraction: dict) -> dict:
    if not isinstance(extraction, dict):
        raise ValueError("Extraction must be a dictionary.")

    patient_id = extraction.get("patient_id")
    if not patient_id:
        raise ValueError("Patient ID is missing.")

    document_name = extraction.get("document_name") or "unknown_document"
    document_id = extraction.get("document_id") or document_name
    events = extraction.get("events", [])

    if not isinstance(events, list):
        raise ValueError("Events must be a list.")

    # Remove previously indexed passages for this same document.
    rag_engine.collection.delete(
        where={
            "$and": [
                {"patient_id": patient_id},
                {"document_id": document_id}
            ]
        }
    )

    indexed = 0
    skipped = 0

    for event in events:
        if not isinstance(event, dict):
            skipped += 1
            continue

        evidence = event.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            skipped += 1
            continue

        source_page = event.get("source_page") or 1
        if not isinstance(source_page, int) or source_page < 1:
            source_page = 1

        event_type = event.get("event_type") or "clinical_event"
        status = event.get("status") or "documented"

        searchable_evidence = (
            f"Event type: {event_type}. "
            f"Record status: {status}. "
            f"Clinical evidence: {evidence.strip()}"
        )

        rag_engine.add_evidence(
            patient_id=patient_id,
            document_id=document_id,
            document_name=document_name,
            source_page=source_page,
            evidence=searchable_evidence,
            event_date=event.get("event_date"),
            recorded_date=event.get("recorded_date"),
        )

        indexed += 1

    return {
        "patient_id": patient_id,
        "document_name": document_name,
        "indexed_passages": indexed,
        "skipped_events": skipped,
        "status": "success"
    }


def index_json_file(file_path: str) -> dict:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        extraction = json.load(file)

    return index_extraction(extraction)
