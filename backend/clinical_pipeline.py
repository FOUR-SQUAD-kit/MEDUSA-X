
from typing import Any

from backend.clinical_adapter import adapt_extraction
from backend.timeline import build_timeline
from backend.reconciliation import reconcile
from backend.truth_ledger import (
    build_truth_ledger,
    LedgerStatus,
    _entry,
)


def _finalize_pipeline(adapted: dict) -> dict:
    """
    Shared timeline, reconciliation, and Truth Ledger processing.
    Supports one or multiple documents for the same patient.
    """

    timeline = build_timeline(adapted)
    report = reconcile(timeline)
    ledger = build_truth_ledger(timeline, report)

    medication_events = timeline.by_category("medication")

    # Keep historical medication records separate.
    historical_groups = {}

    for event in medication_events:
        if event.context == "historical":
            historical_groups.setdefault(event.name_key, []).append(event)

    current_groups = {
        event.name_key
        for event in medication_events
        if event.context != "historical"
    }

    for key, events in historical_groups.items():
        if key not in current_groups:
            continue

        name = events[0].name

        ledger["entries"].append(
            _entry(
                "medication",
                f"{name} - historical record",
                f"'{name}' is documented as historical. "
                "Its historical dosage is not assumed to be current.",
                LedgerStatus.HISTORICAL,
                events,
                [],
                ["Is this medicine currently being taken?"],
            )
        )

    # Group medication events by medicine.
    medication_groups = {}

    for event in medication_events:
        medication_groups.setdefault(event.name_key, []).append(event)

    # Unresolved withholding must not appear confirmed.
    for key, events in medication_groups.items():

        unresolved_withheld = [
            event
            for event in events
            if event.action == "withheld" and not event.restart_info
        ]

        if not unresolved_withheld:
            continue

        name = unresolved_withheld[0].name

        related = [
            conflict
            for conflict in report["conflicts"]
            if conflict["category"] == "medication"
            and conflict["subject_key"] == key
            and conflict["conflict_type"] == "missing_restart_information"
        ]

        main_entry = next(
            (
                entry
                for entry in ledger["entries"]
                if entry["subject_type"] == "medication"
                and entry["subject"] == name
            ),
            None,
        )

        if main_entry is not None:

            if main_entry["status"] == LedgerStatus.CONFIRMED_DOCUMENTED.value:
                main_entry["status"] = (
                    LedgerStatus.PENDING_VERIFICATION.value
                )

                main_entry["statement"] = (
                    f"'{name}' was documented as withheld. "
                    "A later listing does not establish that it was restarted."
                )

                main_entry["open_questions"] = [
                    "Has the medication been restarted?",
                    "What dose and frequency were confirmed by the clinician?",
                ]

            existing_ids = main_entry.get("related_conflict_ids", [])

            for item in related:
                conflict_id = item["conflict_id"]

                if conflict_id not in existing_ids:
                    existing_ids.append(conflict_id)

            main_entry["related_conflict_ids"] = existing_ids

    # Assign ledger IDs and recalculate status counts.
    for index, entry in enumerate(ledger["entries"], 1):
        entry["ledger_id"] = f"L-{index:03d}"

    counts = {
        status.value: 0
        for status in LedgerStatus
    }

    for entry in ledger["entries"]:
        counts[entry["status"]] += 1

    ledger["status_counts"] = counts

    return {
        "patient": timeline.patient,
        "timeline": timeline.to_dict(),
        "conflict_report": report,
        "truth_ledger": ledger,
        "supporting_events": adapted["supporting_events"],
        "other_events": adapted["other_events"],
        "quality_warnings": adapted["quality_warnings"],
        "summary": {
            "timeline_events": len(timeline.events),
            "conflicts": report["counts"],
            "ledger_status_counts": counts,
        },
    }


def run_clinical_pipeline(extraction: dict) -> dict:
    """
    Original single-document clinical pipeline.
    """

    adapted = adapt_extraction(extraction)
    return _finalize_pipeline(adapted)


def run_multi_document_pipeline(extractions: list[dict]) -> dict:
    """
    Analyse multiple extracted reports belonging to the same patient.

    Each report is adapted independently so its document name,
    evidence, and page references remain associated with that report.
    """

    if not isinstance(extractions, list) or not extractions:
        raise ValueError("At least one report extraction is required")

    adapted_reports = [
        adapt_extraction(extraction)
        for extraction in extractions
    ]

    first_patient = adapted_reports[0]["patient"]
    patient_id = first_patient["patient_id"]

    for adapted in adapted_reports[1:]:
        if adapted["patient"]["patient_id"] != patient_id:
            raise ValueError(
                "All reports must belong to the same patient"
            )

    combined = {
        "patient": first_patient,
        "documents": [],
        "supporting_events": [],
        "other_events": [],
        "quality_warnings": [],
    }

    for adapted in adapted_reports:
        combined["documents"].extend(adapted["documents"])
        combined["supporting_events"].extend(
            adapted["supporting_events"]
        )
        combined["other_events"].extend(
            adapted["other_events"]
        )
        combined["quality_warnings"].extend(
            adapted["quality_warnings"]
        )

    return _finalize_pipeline(combined)
