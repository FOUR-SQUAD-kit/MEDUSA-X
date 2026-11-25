"""
reconciliation.py  --  MEDUSA-X  (Developer 3: Prajwal)

Compares records across documents and produces a structured conflict report.

Principles
----------
* The module REPORTS disagreements; it never decides which record is correct.
  Every item has requires_clinician_review=True and resolution=None.
* The latest document is NOT assumed correct.
* Historical medicines are NOT assumed active (and NOT assumed stopped either).
* No medical-knowledge inference: two different diagnosis names are linked
  only if a record explicitly says so (changed_from / supersedes).

kind values:  conflict | difference | missing | verification | change
review_priority:  high | medium | low   (data-review priority, NOT clinical severity)
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import date
from typing import Any, Dict, List, Optional

try:
    from .timeline import Timeline, TimelineEvent, norm_dose, norm_frequency
except ImportError:  # running as flat files
    from timeline import Timeline, TimelineEvent, norm_dose, norm_frequency

SYSTEM_NOTE = ("System reports the disagreement only; it does not determine which record is correct.")
ACTIVE_DIAG = {"suspected", "confirmed", "documented", "revised"}
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def event_ref(e: TimelineEvent) -> Dict[str, Any]:
    """Evidence block for one event (document name, page, original text, both dates)."""
    ref = {"event_id": e.event_id, "document_name": e.document_name,
           "document_type": e.evidence.document_type if e.evidence else None,
           "page": e.evidence.page if e.evidence else None,
           "evidence_text": e.evidence.text if e.evidence else None,
           "event_date": _iso(e.event_date), "recorded_date": _iso(e.recorded_date)}
    if e.category == "diagnosis":
        ref["status"] = e.status
        if e.changed_from:
            ref["changed_from"] = e.changed_from
    elif e.category == "medication":
        ref.update({"action": e.action, "context": e.context, "dose": e.dose, "frequency": e.frequency})
    else:
        ref["result"] = e.result
    return ref


def _dedupe(refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in refs:
        if r["event_id"] not in seen:
            seen.add(r["event_id"])
            out.append(r)
    return out


class _Collector:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, *, category: str, kind: str, ctype: str, subject: str, subject_key: str,
            priority: str, summary: str, events: List[TimelineEvent],
            details: Optional[Dict[str, Any]] = None, chronology_certain: bool = True) -> None:
        self.items.append({
            "conflict_id": "", "category": category, "kind": kind, "conflict_type": ctype,
            "subject": subject, "subject_key": subject_key, "review_priority": priority,
            "summary": summary, "details": details or {},
            "evidence": _dedupe([event_ref(e) for e in events]),
            "chronology_certain": chronology_certain,
            "requires_clinician_review": True, "resolution": None, "system_note": SYSTEM_NOTE,
        })


def _docs_str(events: List[TimelineEvent]) -> str:
    out = []
    for e in events:
        pg = f", p.{e.evidence.page}" if e.evidence and e.evidence.page is not None else ""
        out.append(f"{e.document_name}{pg}")
    return "; ".join(OrderedDict.fromkeys(out))


# ==========================================================================
# DIAGNOSES
# ==========================================================================
def detect_diagnosis_discrepancies(tl: Timeline, col: _Collector) -> None:
    diags = tl.by_category("diagnosis")
    groups: Dict[str, List[TimelineEvent]] = defaultdict(list)
    for e in diags:
        groups[e.name_key].append(e)

    for key, evs in groups.items():
        display = evs[0].name
        ruled = [e for e in evs if e.status == "ruled_out"]
        superseders = [s for s in diags if s.changed_from_key == key]
        against = ruled + superseders
        active = [e for e in evs if e.status in ACTIVE_DIAG]
        if not against:
            continue
        first_against = min(against, key=lambda e: (e.recorded_date or date.max))
        later_active, certain = [], True
        for a in active:
            if a.recorded_date is None or first_against.recorded_date is None:
                certain = False
                later_active.append(a)       # cannot order -> cannot dismiss
            elif a.recorded_date >= first_against.recorded_date:
                later_active.append(a)
        if later_active:
            how = "ruled out" if ruled else "recorded as changed to another diagnosis"
            col.add(category="diagnosis", kind="conflict",
                    ctype="diagnosis_listed_after_ruled_out_or_changed",
                    subject=display, subject_key=key,
                    priority="high" if certain else "medium",
                    summary=(f"'{display}' is {how} in {_docs_str(against)}, but is also listed as "
                             f"'{later_active[0].status}' in {_docs_str(later_active)}."
                             + ("" if certain else " Record order could not be confirmed (missing recorded date).")),
                    events=against + later_active,
                    details={"against_documents": [e.document_name for e in against],
                             "later_listing_documents": [e.document_name for e in later_active]},
                    chronology_certain=certain)
        else:
            col.add(category="diagnosis", kind="change", ctype="diagnosis_change_documented",
                    subject=display, subject_key=key, priority="low",
                    summary=(f"'{display}' was documented as active in earlier record(s) and later "
                             f"ruled out / changed in {_docs_str(against)}."),
                    events=active + against)

    # --- diagnosis present in earlier documents but absent from a later discharge-type document
    for doc in tl.documents:
        dtype = (doc.get("document_type") or "").lower()
        if "discharge" not in dtype:
            continue
        dname = doc["document_name"]
        d_events = [e for e in diags if e.document_name == dname]
        if not d_events:
            continue
        d_keys = {e.name_key for e in d_events}
        d_rec = d_events[0].recorded_date
        for key, evs in groups.items():
            if key in d_keys:
                continue
            earlier = [e for e in evs if e.document_name != dname
                       and (d_rec is None or e.recorded_date is None or e.recorded_date <= d_rec)]
            if not earlier:
                continue
            latest = earlier[-1]
            superseded = any(s.changed_from_key == key for s in diags)
            if latest.status in ("ruled_out", "resolved") or superseded:
                continue  # expected to be absent
            col.add(category="diagnosis", kind="verification", ctype="diagnosis_not_carried_forward",
                    subject=evs[0].name, subject_key=key, priority="medium",
                    summary=(f"'{evs[0].name}' appears in {_docs_str(earlier)} but is not listed in "
                             f"discharge document '{dname}'. Absence may be deliberate or an omission."),
                    events=earlier, details={"discharge_document": dname},
                    chronology_certain=d_rec is not None)


# ==========================================================================
# MEDICATIONS
# ==========================================================================
def _latest_with(evs: List[TimelineEvent], attr: str) -> Optional[TimelineEvent]:
    for e in reversed(evs):
        if getattr(e, attr):
            return e
    return None


def detect_medication_discrepancies(tl: Timeline, col: _Collector) -> Dict[str, Any]:
    meds = tl.by_category("medication")
    groups: "OrderedDict[str, List[TimelineEvent]]" = OrderedDict()
    for e in meds:
        groups.setdefault(e.name_key, []).append(e)

    view: Dict[str, Any] = {}
    for key, evs in groups.items():
        display = evs[0].name
        hist = [e for e in evs if e.context == "historical"]
        cur = [e for e in evs if e.context != "historical"]

        # ---- action sequence (current-context records only, chronological)
        state, state_ev, flagged = None, None, set()
        change_events = [e for e in cur if e.action == "changed"]
        for e in cur:
            asserts_active = e.action in ("started", "continued", "changed") or \
                             (e.action == "listed" and e.context == "current")
            if asserts_active and state in ("stopped", "withheld") and e.event_id not in flagged:
                flagged.add(e.event_id)
                uncertain = any(x.sort_basis != "event_date" for x in (e, state_ev))
                col.add(category="medication", kind="conflict",
                        ctype="active_after_stop_or_withhold_without_restart_record",
                        subject=display, subject_key=key, priority="high",
                        summary=(f"'{display}' is recorded as {state} in {_docs_str([state_ev])} and later as "
                                 f"'{e.action}' in {_docs_str([e])} with no restart/resume record in between."),
                        events=[state_ev, e], chronology_certain=not uncertain,
                        details={"earlier_action": state, "later_action": e.action})
            if e.action in ("started", "continued", "restarted", "changed") or \
               (e.action == "listed" and e.context == "current"):
                state, state_ev = "active", e
            elif e.action == "stopped":
                state, state_ev = "stopped", e
            elif e.action == "withheld":
                state, state_ev = "withheld", e

        # ---- dose / frequency disagreement among current records
        for attr, norm, label in (("dose", norm_dose, "dose"), ("frequency", norm_frequency, "frequency")):
            vals = OrderedDict()
            for e in cur:
                v = norm(getattr(e, attr))
                if v:
                    vals.setdefault(v, []).append(e)
            if len(vals) > 1:
                involved = [x for lst in vals.values() for x in lst]
                if change_events:
                    col.add(category="medication", kind="change", ctype=f"{label}_change_documented",
                            subject=display, subject_key=key, priority="low",
                            summary=f"'{display}' {label} differs across records and a change action is documented.",
                            events=involved + change_events,
                            details={f"{label}_values": list(vals.keys())})
                else:
                    col.add(category="medication", kind="conflict", ctype=f"{label}_mismatch_across_documents",
                            subject=display, subject_key=key, priority="medium",
                            summary=(f"'{display}' has different {label} values "
                                     f"({', '.join(getattr(v[0], attr) for v in vals.values())}) across documents "
                                     f"with no documented change."),
                            events=involved, details={f"{label}_values": list(vals.keys())})

        # ---- historical vs current comparison
        if hist and not cur:
            col.add(category="medication", kind="verification", ctype="historical_only_no_current_record",
                    subject=display, subject_key=key, priority="medium",
                    summary=(f"'{display}' appears only as a historical record ({_docs_str(hist)}). "
                             f"No current record found in the provided documents; current status is "
                             f"not established (not assumed active, not assumed stopped)."),
                    events=hist)
        if hist and cur:
            for attr, norm, label in (("dose", norm_dose, "dose"), ("frequency", norm_frequency, "frequency")):
                h, c = _latest_with(hist, attr), _latest_with(cur, attr)
                if h and c and norm(getattr(h, attr)) != norm(getattr(c, attr)):
                    col.add(category="medication", kind="difference", ctype=f"historical_vs_current_{label}_difference",
                            subject=display, subject_key=key, priority="medium",
                            summary=(f"'{display}' {label}: historical record says '{getattr(h, attr)}' "
                                     f"({_docs_str([h])}); current record says '{getattr(c, attr)}' ({_docs_str([c])})."),
                            events=[h, c])

        # ---- missing information (per record)
        for e in evs:
            others = [o for o in evs if o is not e]
            if e.action != "stopped":
                for attr, label, ctype in (("dose", "dosage", "missing_dosage"),
                                           ("frequency", "frequency", "missing_frequency")):
                    if not getattr(e, attr):
                        known = [{"document_name": o.document_name,
                                  "page": o.evidence.page if o.evidence else None,
                                  attr: getattr(o, attr), "context": o.context,
                                  "note": "Documented in another record; NOT verified as applying to this record."}
                                 for o in others if getattr(o, attr)]
                        col.add(category="medication", kind="missing", ctype=ctype,
                                subject=display, subject_key=key,
                                priority="low" if e.context == "historical" else "medium",
                                summary=f"'{display}': {label} not stated in {_docs_str([e])}.",
                                events=[e], details={"field": label, "values_in_other_records": known})
            if e.action == "withheld" and not e.restart_info:
                col.add(category="medication", kind="missing", ctype="missing_restart_information",
                        subject=display, subject_key=key, priority="high",
                        summary=(f"'{display}' is recorded as withheld in {_docs_str([e])} but no restart / "
                                 f"resume plan or date is documented; restart status unknown."),
                        events=[e], details={"field": "restart_information"})
            if e.action in ("started", "stopped", "changed", "withheld", "restarted") and e.event_date is None:
                col.add(category="medication", kind="missing", ctype="missing_event_date",
                        subject=display, subject_key=key, priority="low",
                        summary=(f"'{display}': '{e.action}' event has no event date in {_docs_str([e])} "
                                 f"(only the recorded date is known)."),
                        events=[e], details={"field": "event_date"})

        view[key] = {
            "name": display, "has_historical_records": bool(hist), "has_current_records": bool(cur),
            "event_ids": [e.event_id for e in evs],
            "actions_in_order": [{"event_id": e.event_id, "action": e.action, "context": e.context,
                                  "event_date": _iso(e.event_date), "recorded_date": _iso(e.recorded_date),
                                  "document_name": e.document_name} for e in evs],
            "last_documented_state": state if cur else "not_established",
            "note": "last_documented_state is the last documented action only; it is NOT verified current status.",
        }

    # ---- medication in earlier documents but absent from a later discharge-type document
    meds_by_doc: Dict[str, List[TimelineEvent]] = defaultdict(list)
    for e in meds:
        meds_by_doc[e.document_name].append(e)
    for doc in tl.documents:
        if "discharge" not in (doc.get("document_type") or "").lower():
            continue
        dname = doc["document_name"]
        d_events = meds_by_doc.get(dname, [])
        if not d_events:
            continue
        d_keys = {e.name_key for e in d_events}
        d_rec = d_events[0].recorded_date
        for key, evs in groups.items():
            if key in d_keys:
                continue
            earlier = [e for e in evs if e.document_name != dname and e.context != "historical"
                       and (d_rec is None or e.recorded_date is None or e.recorded_date <= d_rec)]
            if not earlier or earlier[-1].action == "stopped":
                continue
            col.add(category="medication", kind="verification", ctype="medication_not_carried_forward",
                    subject=evs[0].name, subject_key=key, priority="medium",
                    summary=(f"'{evs[0].name}' is recorded ({earlier[-1].action}) in {_docs_str(earlier)} but is not "
                             f"mentioned in discharge document '{dname}'. Status at discharge is not documented."),
                    events=earlier, details={"discharge_document": dname},
                    chronology_certain=d_rec is not None)
    return view


# ==========================================================================
# ENTRY POINT
# ==========================================================================
def reconcile(tl: Timeline) -> Dict[str, Any]:
    col = _Collector()
    detect_diagnosis_discrepancies(tl, col)
    medication_view = detect_medication_discrepancies(tl, col)

    items = sorted(col.items, key=lambda c: (c["category"], PRIORITY_RANK[c["review_priority"]], c["conflict_type"]))
    for i, c in enumerate(items, 1):
        c["conflict_id"] = f"C-{i:03d}"

    by_kind: Dict[str, int] = defaultdict(int)
    by_priority: Dict[str, int] = defaultdict(int)
    for c in items:
        by_kind[c["kind"]] += 1
        by_priority[c["review_priority"]] += 1
    return {"patient": tl.patient, "conflicts": items,
            "counts": {"total": len(items), "by_kind": dict(by_kind), "by_review_priority": dict(by_priority)},
            "medication_view": medication_view,
            "disclaimer": SYSTEM_NOTE + " All items require clinician review."}


if __name__ == "__main__":
    import json
    import sys
    try:
        from .timeline import build_timeline
    except ImportError:
        from timeline import build_timeline
    print(json.dumps(reconcile(build_timeline(sys.argv[1])), indent=2))
