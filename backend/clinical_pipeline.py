
from typing import Any

from backend.clinical_adapter import adapt_extraction
from backend.timeline import build_timeline
from backend.reconciliation import reconcile
from backend.truth_ledger import (
    build_truth_ledger,
    LedgerStatus,
    _entry,
)


def run_clinical_pipeline(extraction: dict) -> dict:
    """
    Connect document extraction, timeline, reconciliation,
    and Clinical Truth Ledger.

    Original teammate modules remain unchanged.
    """

    # Step 1: Adapt extracted data to the shared timeline format.
    adapted = adapt_extraction(extraction)

    # Step 2: Build the patient's clinical timeline.
    timeline = build_timeline(adapted)

    # Step 3: Detect contradictions and missing information.
    report = reconcile(timeline)

    # Step 4: Generate the initial Truth Ledger.
    ledger = build_truth_ledger(timeline, report)

    medication_events = timeline.by_category("medication")

    # Step 5: Keep historical medication records separate.
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

    # Step 6: Group medication events by medicine.
    medication_groups = {}

    for event in medication_events:
        medication_groups.setdefault(event.name_key, []).append(event)

    # Step 7: An unresolved withholding must not appear confirmed.
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
            # Preserve an actual contradiction if one was already identified.
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

    # Step 8: Assign fresh ledger IDs and recalculate status counts.
    for index, entry in enumerate(ledger["entries"], 1):
        entry["ledger_id"] = f"L-{index:03d}"

    counts = {
        status.value: 0
        for status in LedgerStatus
    }

    for entry in ledger["entries"]:
        counts[entry["status"]] += 1

    ledger["status_counts"] = counts

    # Step 9: Return the complete patient analysis.
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
