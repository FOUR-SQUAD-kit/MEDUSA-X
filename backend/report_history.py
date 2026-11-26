import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "data" / "report_history.json"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"


def load_report_history():
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]", encoding="utf-8")

    with HISTORY_FILE.open("r", encoding="utf-8") as file:
        history = json.load(file)

    if not isinstance(history, list):
        raise ValueError("Report history must be a list")

    return history


def archive_report(patient_id, patient_name, source_path, original_filename,
                   summary="", status="processed"):
    report_id = str(uuid.uuid4())
    patient_folder = UPLOAD_DIR / patient_id
    patient_folder.mkdir(parents=True, exist_ok=True)

    safe_name = Path(original_filename).name
    stored_name = f"{report_id}_{safe_name}"
    destination = patient_folder / stored_name

    shutil.copy2(source_path, destination)

    record = {
        "report_id": report_id,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "filename": safe_name,
        "stored_path": str(destination.relative_to(BASE_DIR)),
        "uploaded_at": datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).isoformat(),
        "summary": summary,
        "status": status
    }

    history = load_report_history()
    history.append(record)

    HISTORY_FILE.write_text(
        json.dumps(history, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )

    return record


def get_patient_history(patient_id):
    return [
        record for record in load_report_history()
        if record.get("patient_id") == patient_id
    ]


def get_all_report_history():
    return sorted(
        load_report_history(),
        key=lambda item: item.get("uploaded_at", ""),
        reverse=True
    )



def get_report_by_id(report_id):
    for record in load_report_history():
        if record.get("report_id") == report_id:
            return record
    return None
