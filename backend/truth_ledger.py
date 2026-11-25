"""
truth_ledger.py  --  MEDUSA-X  (Developer 3: Prajwal)

Builds the Clinical Truth Ledger from the timeline + conflict report and exposes
the single integration entry point:

    analyze_patient(data_or_path) -> dict      # timeline + conflict report + ledger

Ledger statuses
---------------
confirmed_documented   documented in the records, no disagreement found
historical             documented only as past / historical; NOT assumed active
contradicted           records disagree (see related_conflict_ids)
missing                a needed detail (dose, frequency, restart info...) is not documented
pending_verification   suspected / withheld / not carried forward -> needs a human to verify

"confirmed_documented" means "the document says so" -- it is NOT the system's clinical
judgement that the statement is true.

CLI:      python truth_ledger.py sample_inputs/ananya.json --out ananya_result.json
FastAPI:  from truth_ledger import build_router ; app.include_router(build_router())
          (add that line from your own code -- this module never touches main.py)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from enum import Enum
from typing import Any, Dict, List, Union
from pathlib import Path

try:
    from .timeline import Timeline, TimelineEvent, build_timeline
    from .reconciliation import event_ref, reconcile
except ImportError:  # flat-file use
    from timeline import Timeline, TimelineEvent, build_timeline
    from reconciliation import event_ref, reconcile

VERSION = "0.1.0"


class LedgerStatus(str, Enum):
    CONFIRMED_DOCUMENTED = "confirmed_documented"
    HISTORICAL = "historical"
    CONTRADICTED = "contradicted"
    MISSING = "missing"
    PENDING_VERIFICATION = "pending_verification"


def _entry(subject_type: str, subject: str, statement: str, status: LedgerStatus,
           events: List[TimelineEvent], conflict_ids: List[str], questions: List[str] = None) -> Dict[str, Any]:
    seen, evidence = set(), []
    for e in events:
        if e.event_id not in seen:
            seen.add(e.event_id)
            evidence.append(event_ref(e))
    return {"ledger_id": "", "subject_type": subject_type, "subject": subject, "statement": statement,
            "status": status.value, "evidence": evidence, "related_conflict_ids": conflict_ids,
            "open_questions": questions or []}


def _ids(conflicts: List[Dict[str, Any]], category: str, key: str, kinds=None) -> List[Dict[str, Any]]:
    return [c for c in conflicts if c["category"] == category and c["subject_key"] == key
            and (kinds is None or c["kind"] in kinds)]


# --------------------------------------------------------------------------
def _diagnosis_entries(tl: Timeline, conflicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    diags = tl.by_category("diagnosis")
    groups: Dict[str, List[TimelineEvent]] = defaultdict(list)
    for e in diags:
        groups[e.name_key].append(e)

    for key, evs in groups.items():
        name = evs[0].name
        superseders = [s for s in diags if s.changed_from_key == key]
        rel = _ids(conflicts, "diagnosis", key)
        conf = [c for c in rel if c["kind"] == "conflict"]
        verif = [c for c in rel if c["kind"] == "verification"]
        cids = [c["conflict_id"] for c in rel]
        statuses = [e.status for e in evs]
        per_doc = "; ".join(f"{e.document_name}: {e.raw_status_text or e.status}" for e in evs)

        if conf:
            out.append(_entry("diagnosis", name, f"Records disagree about '{name}' ({per_doc}).",
                              LedgerStatus.CONTRADICTED, evs + superseders, cids,
                              ["Which record reflects the clinician's intended diagnosis? (clinician review)"]))
        elif verif:
            out.append(_entry("diagnosis", name,
                              f"'{name}' is documented ({per_doc}) but is not carried into the discharge document.",
                              LedgerStatus.PENDING_VERIFICATION, evs, cids,
                              ["Was omission from the discharge document intentional?"]))
        elif superseders or "ruled_out" in statuses:
            by = (f"superseded by '{superseders[0].name}' in {superseders[0].document_name}"
                  if superseders else "ruled out")
            out.append(_entry("diagnosis", name, f"'{name}' is documented as {by}.",
                              LedgerStatus.CONFIRMED_DOCUMENTED, evs + superseders, cids))
        elif all(s == "resolved" for s in statuses) or all(e.context == "historical" for e in evs):
            out.append(_entry("diagnosis", name, f"'{name}' is documented only as past / resolved ({per_doc}).",
                              LedgerStatus.HISTORICAL, evs, cids))
        elif all(s == "suspected" for s in statuses):
            out.append(_entry("diagnosis", name,
                              f"'{name}' is documented as suspected; no record confirms or excludes it ({per_doc}).",
                              LedgerStatus.PENDING_VERIFICATION, evs, cids,
                              ["Is there a confirming or excluding record not included in these documents?"]))
        else:
            out.append(_entry("diagnosis", name, f"'{name}' is documented ({per_doc}).",
                              LedgerStatus.CONFIRMED_DOCUMENTED, evs, cids))
    return out


def _medication_entries(tl: Timeline, conflicts: List[Dict[str, Any]], view: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    groups: Dict[str, List[TimelineEvent]] = defaultdict(list)
    for e in tl.by_category("medication"):
        groups[e.name_key].append(e)

    for key, evs in groups.items():
        name = evs[0].name
        cur = [e for e in evs if e.context != "historical"]
        rel = _ids(conflicts, "medication", key)
        cids = [c["conflict_id"] for c in rel]
        conf = [c for c in rel if c["kind"] == "conflict"]
        verif = [c for c in rel if c["kind"] == "verification"]
        trail = "; ".join(f"{e.document_name}: {e.action}{' (historical)' if e.context == 'historical' else ''}"
                          for e in evs)
        last = cur[-1] if cur else None

        if conf:
            out.append(_entry("medication", name, f"Records disagree about '{name}' ({trail}).",
                              LedgerStatus.CONTRADICTED, evs, cids, ["Clinician to confirm actual status."]))
        elif last is not None and last.action == "withheld" and not last.restart_info:
            out.append(_entry("medication", name,
                              f"'{name}' is documented as withheld; no restart status is documented ({trail}).",
                              LedgerStatus.PENDING_VERIFICATION, evs, cids,
                              ["Has it been restarted, and with what dose/frequency?",
                               "Any historical dose is not verified as current."]))
        elif verif and cur:
            out.append(_entry("medication", name,
                              f"'{name}' is documented ({trail}) but not mentioned in the discharge document.",
                              LedgerStatus.PENDING_VERIFICATION, evs, cids,
                              ["What is its status at discharge?"]))
        elif not cur:
            out.append(_entry("medication", name,
                              f"'{name}' is documented only as a historical record ({trail}). "
                              f"Not treated as active; current status not established.",
                              LedgerStatus.HISTORICAL, evs, cids,
                              ["Is this medicine currently being taken? No current record exists."]))
        else:
            out.append(_entry("medication", name, f"'{name}' is documented ({trail}).",
                              LedgerStatus.CONFIRMED_DOCUMENTED, evs, cids))

    # one MISSING entry per missing detail
    ev_by_id = {e.event_id: e for e in tl.events}
    for c in conflicts:
        if c["category"] == "medication" and c["kind"] == "missing":
            src = ev_by_id[c["evidence"][0]["event_id"]]
            field_label = c["details"].get("field", c["conflict_type"])
            out.append(_entry("medication", f"{c['subject']} - {field_label}",
                              c["summary"], LedgerStatus.MISSING, [src], [c["conflict_id"]],
                              [f"Obtain {field_label} from the source record or clinician."]))
    return out


def _test_entries(tl: Timeline) -> List[Dict[str, Any]]:
    out = []
    for e in tl.by_category("test"):
        if e.result:
            out.append(_entry("test", e.name, f"Test '{e.name}' documented with result: {e.result}.",
                              LedgerStatus.CONFIRMED_DOCUMENTED, [e], []))
        else:
            out.append(_entry("test", e.name, f"Test '{e.name}' is listed but no result is documented.",
                              LedgerStatus.MISSING, [e], []))
    return out


def build_truth_ledger(tl: Timeline, report: Dict[str, Any]) -> Dict[str, Any]:
    conflicts = report["conflicts"]
    entries = (_diagnosis_entries(tl, conflicts)
               + _medication_entries(tl, conflicts, report["medication_view"])
               + _test_entries(tl))
    for i, ent in enumerate(entries, 1):
        ent["ledger_id"] = f"L-{i:03d}"
    counts = {s.value: 0 for s in LedgerStatus}
    for ent in entries:
        counts[ent["status"]] += 1
    return {"patient": tl.patient, "entries": entries, "status_counts": counts,
            "legend": {s.value: d for s, d in [
                (LedgerStatus.CONFIRMED_DOCUMENTED, "Documented in the records; no disagreement found. Not a clinical verification."),
                (LedgerStatus.HISTORICAL, "Documented only as past/historical; not assumed active."),
                (LedgerStatus.CONTRADICTED, "Records disagree; see related conflicts."),
                (LedgerStatus.MISSING, "A needed detail is not documented."),
                (LedgerStatus.PENDING_VERIFICATION, "Needs a human to verify.")]}}


# --------------------------------------------------------------------------
# integration entry point
# --------------------------------------------------------------------------
def analyze_patient(src: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
    """Single call for the backend. Input is Meghana's JSON (dict / path / JSON string)."""
    tl = build_timeline(src)
    report = reconcile(tl)
    ledger = build_truth_ledger(tl, report)
    return {
        "meta": {"module_version": VERSION, "owner": "Developer 3 (Prajwal)",
                 "note": "Reports documented disagreements only; no clinical conclusions are made."},
        "patient": tl.patient,
        "timeline": tl.to_dict(),
        "conflict_report": report,
        "truth_ledger": ledger,
        "summary": {"events": len(tl.events), "conflict_items": report["counts"],
                    "ledger_status_counts": ledger["status_counts"],
                    "data_quality_notes": len(tl.data_quality)},
    }


def build_router():
    """Optional FastAPI router. Harshitha: app.include_router(build_router())  -- main.py is not touched here."""
    from fastapi import APIRouter, Body
    router = APIRouter(prefix="/reconciliation", tags=["timeline-reconciliation"])

    @router.post("/analyze")
    def analyze(payload: dict = Body(...)):
        return analyze_patient(payload)

    return router


def _cli() -> None:
    ap = argparse.ArgumentParser(description="MEDUSA-X timeline + reconciliation + truth ledger")
    ap.add_argument("input", help="structured clinical JSON file")
    ap.add_argument("--out", help="write result JSON here (default: print)")
    args = ap.parse_args()
    text = json.dumps(analyze_patient(args.input), indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    _cli()
