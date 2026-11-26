import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REGISTRY_FILE = BASE_DIR / "data" / "patients.json"

DEFAULT_PATIENTS = [
    {"patient_id": "P001", "patient_name": "Ananya"},
    {"patient_id": "P002", "patient_name": "Kiran"},
]


def load_patients():
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not REGISTRY_FILE.exists():
        save_patients(DEFAULT_PATIENTS)

    with REGISTRY_FILE.open("r", encoding="utf-8") as file:
        patients = json.load(file)

    if not isinstance(patients, list):
        raise ValueError("Patient registry must contain a list")

    return patients


def save_patients(patients):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with REGISTRY_FILE.open("w", encoding="utf-8") as file:
        json.dump(patients, file, indent=4, ensure_ascii=False)


def register_patient(patient_name):
    name = patient_name.strip()

    if not name:
        raise ValueError("Patient name cannot be empty")

    patients = load_patients()

    next_number = max(
        (int(p["patient_id"][1:]) for p in patients
         if p.get("patient_id", "").startswith("P")
         and p["patient_id"][1:].isdigit()),
        default=0
    ) + 1

    patient = {
        "patient_id": f"P{next_number:03d}",
        "patient_name": name
    }

    patients.append(patient)
    save_patients(patients)

    return patient
