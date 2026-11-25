"""
timeline.py  --  MEDUSA-X  (Developer 3: Prajwal)

Reads the structured clinical JSON produced by Meghana and builds a
chronological patient timeline.

Rules this module follows
-------------------------
* event_date (when the clinical event happened) and recorded_date (when the
  document recorded it) are ALWAYS kept as two separate fields.
* Original document name, page number and evidence text travel with every event.
* Nothing is inferred clinically. Unknown stays unknown (None).
* The shared JSON schema is NOT changed. All key-name flexibility lives in the
  ALIASES table below -- if Meghana's real keys differ, edit ONLY that table.

Public API
----------
load_patient_json(src)  -> dict
build_timeline(src)     -> Timeline
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# --------------------------------------------------------------------------
# ADAPTER LAYER  (the only place that knows about input key names)
# --------------------------------------------------------------------------
ALIASES: Dict[str, Tuple[str, ...]] = {
    # containers
    "documents": ("documents", "docs", "records", "files"),
    "diagnoses": ("diagnoses", "diagnosis", "conditions", "problems"),
    "medications": ("medications", "medication", "meds", "medicines", "drugs"),
    "tests": ("tests", "lab_results", "investigations", "results"),
    "entities": ("entities", "extractions"),
    # document level
    "doc_name": ("document_name", "doc_name", "file_name", "filename", "source_document", "name"),
    "doc_type": ("document_type", "doc_type", "type"),
    "doc_recorded": ("recorded_date", "document_date", "date_recorded", "note_date", "date"),
    # item level
    "name": ("name", "diagnosis", "medication", "medicine", "drug", "test_name", "test", "condition", "term"),
    "status": ("status", "certainty", "diagnosis_status"),
    "action": ("action", "event_type", "medication_action", "med_action"),
    "context": ("context", "temporal_context", "record_context", "timeframe", "period"),
    "dose": ("dose", "dosage", "strength"),
    "frequency": ("frequency", "freq"),
    "event_date": ("event_date", "date_of_event", "onset_date", "start_date", "date"),
    "recorded_date": ("recorded_date", "date_recorded", "document_date", "note_date"),
    "page": ("page", "page_number", "page_no", "pg"),
    "evidence": ("evidence_text", "evidence", "source_text", "quote", "text"),
    "restart": ("restart_info", "restart_date", "restart_status", "resume_info", "restart"),
    "changed_from": ("changed_from", "supersedes", "previous_diagnosis", "replaces"),
    "result": ("result", "value", "interpretation"),
    "entity_type": ("entity_type", "category", "kind", "type"),
}

MISSING_TOKENS = {"", "n/a", "na", "none", "null", "unknown", "not documented",
                  "not stated", "not specified", "nil", "-", "--", "?"}

ORDERING_NOTE = (
    "Events are ordered by event_date. If an event has no event_date, "
    "recorded_date is used for ORDERING ONLY (see sort_basis). Events with no "
    "date at all come last. event_date and recorded_date are never merged."
)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return None if s.lower() in MISSING_TOKENS else s


def _pick(d: Dict[str, Any], alias_key: str) -> Any:
    for k in ALIASES[alias_key]:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d",
                 "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y")


def parse_date(value: Any) -> Optional[date]:
    """Parse a date. NOTE: numeric day/month strings are read as DD/MM/YYYY."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm_key(name: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (name or "").lower()).strip(" .,;:")


def norm_dose(dose: Optional[str]) -> Optional[str]:
    return None if dose is None else re.sub(r"\s+", "", dose.lower())


_FREQ_MAP = {"od": "once daily", "qd": "once daily", "bd": "twice daily", "bid": "twice daily",
             "tds": "three times daily", "tid": "three times daily", "qid": "four times daily"}


def norm_frequency(freq: Optional[str]) -> Optional[str]:
    if freq is None:
        return None
    f = re.sub(r"\s+", " ", freq.lower()).strip(" .")
    return _FREQ_MAP.get(f, f)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _page(v: Any) -> Any:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return str(v)


# --------------------------------------------------------------------------
# normalisers: free text -> controlled vocabulary (no clinical reasoning)
# --------------------------------------------------------------------------
_DIAG_STATUS = [
    ("ruled_out", r"rule[sd]?[ -]?out|excluded|disproved|unlikely|not consistent|negative for"),
    ("suspected", r"unconfirmed|not confirmed|suspect|provisional|probable|possible|likely|query|differential|working"),
    ("resolved", r"resolv|recovered|past history"),
    ("revised", r"revis|changed|updated|amended"),
    ("confirmed", r"confirm|diagnosed|established|positive"),
]


def norm_diag_status(raw: Optional[str]) -> str:
    if raw:
        low = raw.lower()
        for label, pat in _DIAG_STATUS:
            if re.search(pat, low):
                return label
    return "documented"


_MED_ACTION = [
    ("withheld", r"\bheld\b|withh|\bhold|suspend|paus|omit|temporar"),
    ("stopped", r"\bstop|discontinu|ceas|cancel"),
    ("restarted", r"restart|re-start|resum|re-?initiat"),
    ("started", r"\bstart|initiat|commenc|\bbegin|\bnew\b"),
    ("changed", r"chang|increas|decreas|titrat|adjust|reduc|switch|modif"),
    ("continued", r"continu|ongoing|maintain"),
]


def norm_med_action(raw: Optional[str]) -> str:
    if raw:
        low = raw.lower()
        for label, pat in _MED_ACTION:
            if re.search(pat, low):
                return label
    return "listed"  # mentioned, no action stated


def norm_context(raw_context: Optional[str], raw_action: Optional[str]) -> str:
    hist = r"histor|\bpast\b|previous|prior|former|\bold\b|earlier"
    for s in (raw_context, raw_action):
        if s and re.search(hist, s.lower()):
            return "historical"
    if raw_context and re.search(r"current|active|present|on admission|discharge", raw_context.lower()):
        return "current"
    return "unspecified"


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------
@dataclass
class Evidence:
    document_name: str
    page: Any
    text: Optional[str]
    document_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"document_name": self.document_name, "page": self.page,
                "evidence_text": self.text, "document_type": self.document_type}


@dataclass
class TimelineEvent:
    event_id: str
    category: str                 # diagnosis | medication | test
    name: str
    name_key: str
    status: Optional[str] = None  # diagnosis status
    action: Optional[str] = None  # medication action
    context: str = "unspecified"  # historical | current | unspecified (medications)
    dose: Optional[str] = None
    frequency: Optional[str] = None
    restart_info: Optional[str] = None
    result: Optional[str] = None
    changed_from: Optional[str] = None
    changed_from_key: Optional[str] = None
    event_date: Optional[date] = None
    event_date_raw: Optional[str] = None
    recorded_date: Optional[date] = None
    recorded_date_raw: Optional[str] = None
    sort_date: Optional[date] = None
    sort_basis: str = "undated"   # event_date | recorded_date | undated
    doc_index: int = 0
    evidence: Optional[Evidence] = None
    raw_status_text: Optional[str] = None

    @property
    def document_name(self) -> str:
        return self.evidence.document_name if self.evidence else "unknown"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "event_id": self.event_id, "category": self.category, "name": self.name,
            "event_date": _iso(self.event_date), "event_date_raw": self.event_date_raw,
            "recorded_date": _iso(self.recorded_date), "recorded_date_raw": self.recorded_date_raw,
            "sort_basis": self.sort_basis,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }
        if self.category == "diagnosis":
            d.update({"status": self.status, "changed_from": self.changed_from})
        elif self.category == "medication":
            d.update({"action": self.action, "context": self.context, "dose": self.dose,
                      "frequency": self.frequency, "restart_info": self.restart_info})
        else:
            d.update({"result": self.result})
        return d


@dataclass
class Timeline:
    patient: Dict[str, Any]
    documents: List[Dict[str, Any]]
    events: List[TimelineEvent]
    data_quality: List[Dict[str, Any]] = field(default_factory=list)

    def by_category(self, category: str) -> List[TimelineEvent]:
        return [e for e in self.events if e.category == category]

    def to_dict(self) -> Dict[str, Any]:
        return {"patient": self.patient, "documents": self.documents,
                "ordering_note": ORDERING_NOTE,
                "events": [e.to_dict() for e in self.events],
                "data_quality": self.data_quality}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def load_patient_json(src: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
    """Accept a dict, a path to a .json file, or a JSON string. Never mutates input."""
    if isinstance(src, dict):
        return copy.deepcopy(src)
    if isinstance(src, Path) or (isinstance(src, str) and not src.lstrip().startswith("{")):
        return json.loads(Path(src).read_text(encoding="utf-8"))
    return json.loads(src)


def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _extract_documents(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = _pick(data, "documents")
    if isinstance(raw, list):
        return raw
    flat = _pick(data, "entities")
    if isinstance(flat, list):  # flat entity list -> group by document
        grouped: Dict[str, Dict[str, Any]] = {}
        for ent in flat:
            dname = _clean(ent.get("document_name") or ent.get("doc_name")
                           or ent.get("file_name") or ent.get("filename")) or "unknown"
            doc = grouped.setdefault(dname, {"document_name": dname,
                                             "document_type": ent.get("document_type"),
                                             "recorded_date": ent.get("document_date") or ent.get("recorded_date"),
                                             "diagnoses": [], "medications": [], "tests": []})
            etype = (_clean(ent.get("entity_type") or ent.get("category") or ent.get("kind")) or "").lower()
            bucket = ("diagnoses" if "diag" in etype else "medications" if "med" in etype
                      else "tests" if ("test" in etype or "lab" in etype) else None)
            if bucket:
                doc[bucket].append(ent)
        return list(grouped.values())
    if any(k in data for k in ALIASES["diagnoses"] + ALIASES["medications"]):
        return [data]  # a single document passed directly
    return []


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build_timeline(src: Union[str, Path, Dict[str, Any]]) -> Timeline:
    data = load_patient_json(src)
    pat = data.get("patient") if isinstance(data.get("patient"), dict) else {}
    patient = {
        "patient_id": _clean(pat.get("patient_id") or pat.get("id") or data.get("patient_id")),
        "patient_name": _clean(pat.get("patient_name") or pat.get("name") or data.get("patient_name")),
    }

    dq: List[Dict[str, Any]] = []
    events: List[TimelineEvent] = []
    doc_summaries: List[Dict[str, Any]] = []
    seq = 0

    for d_idx, doc in enumerate(_extract_documents(data)):
        dname = _clean(_pick(doc, "doc_name"))
        if dname is None:
            dname = f"document_{d_idx + 1}"
            dq.append({"code": "missing_document_name", "document_name": dname,
                       "message": "Document has no name; placeholder used."})
        dtype = _clean(_pick(doc, "doc_type"))
        doc_rec_raw = _clean(_pick(doc, "doc_recorded"))
        doc_rec = parse_date(doc_rec_raw)
        if doc_rec_raw and doc_rec is None:
            dq.append({"code": "unparseable_date", "document_name": dname,
                       "message": f"Document recorded date '{doc_rec_raw}' could not be parsed."})
        doc_summaries.append({"document_name": dname, "document_type": dtype,
                              "recorded_date": _iso(doc_rec), "recorded_date_raw": doc_rec_raw})

        for category, alias_key in (("diagnosis", "diagnoses"), ("medication", "medications"), ("test", "tests")):
            for item in _as_list(_pick(doc, alias_key)):
                if isinstance(item, str):
                    item = {"name": item}
                if not isinstance(item, dict):
                    continue
                name = _clean(_pick(item, "name"))
                if name is None:
                    dq.append({"code": "missing_name", "document_name": dname,
                               "message": f"A {category} item has no name and was skipped."})
                    continue

                seq += 1
                raw_status = _clean(_pick(item, "status"))
                raw_action = _clean(_pick(item, "action"))
                ev_raw = _clean(_pick(item, "event_date"))
                rec_raw = _clean(_pick(item, "recorded_date")) or doc_rec_raw
                ev_date, rec_date = parse_date(ev_raw), parse_date(rec_raw)
                for label, raw, parsed in (("event_date", ev_raw, ev_date), ("recorded_date", rec_raw, rec_date)):
                    if raw and parsed is None:
                        dq.append({"code": "unparseable_date", "document_name": dname,
                                   "message": f"{label} '{raw}' for '{name}' could not be parsed."})

                if ev_date:
                    sort_date, basis = ev_date, "event_date"
                elif rec_date:
                    sort_date, basis = rec_date, "recorded_date"
                else:
                    sort_date, basis = None, "undated"

                text = _clean(_pick(item, "evidence"))
                if text is None:
                    dq.append({"code": "missing_evidence_text", "document_name": dname,
                               "message": f"No evidence text for {category} '{name}'."})
                page = _page(_pick(item, "page"))
                if page is None:
                    dq.append({"code": "missing_page", "document_name": dname,
                               "message": f"No page number for {category} '{name}'."})

                ev = TimelineEvent(
                    event_id=f"E{seq:03d}", category=category, name=name, name_key=norm_key(name),
                    event_date=ev_date, event_date_raw=ev_raw,
                    recorded_date=rec_date, recorded_date_raw=rec_raw,
                    sort_date=sort_date, sort_basis=basis, doc_index=d_idx,
                    evidence=Evidence(dname, page, text, dtype),
                )
                if category == "diagnosis":
                    ev.status = norm_diag_status(raw_status)
                    ev.raw_status_text = raw_status
                    ev.changed_from = _clean(_pick(item, "changed_from"))
                    ev.changed_from_key = norm_key(ev.changed_from) if ev.changed_from else None
                elif category == "medication":
                    ev.action = norm_med_action(raw_action or raw_status)
                    ev.raw_status_text = raw_action or raw_status
                    ev.context = norm_context(_clean(_pick(item, "context")), raw_action or raw_status)
                    ev.dose = _clean(_pick(item, "dose"))
                    ev.frequency = _clean(_pick(item, "frequency"))
                    ev.restart_info = _clean(_pick(item, "restart"))
                else:
                    ev.result = _clean(_pick(item, "result"))
                events.append(ev)

    events.sort(key=lambda e: (e.sort_date is None, e.sort_date or date.max,
                               e.recorded_date or date.max, e.doc_index, e.event_id))
    return Timeline(patient=patient, documents=doc_summaries, events=events, data_quality=dq)


if __name__ == "__main__":  # quick look:  python timeline.py patient.json
    import sys
    print(json.dumps(build_timeline(sys.argv[1]).to_dict(), indent=2))
