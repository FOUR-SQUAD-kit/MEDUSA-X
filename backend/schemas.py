
from typing import Optional
from pydantic import BaseModel, Field


class ClinicalEvent(BaseModel):
    """One extracted clinical event with source evidence."""

    event_type: str

    value: Optional[str] = None

    # Diagnosis and symptom details
    diagnosis: Optional[str] = None

    # Medication details
    medication_name: Optional[str] = None
    dosage: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    action: Optional[str] = None

    # Lab details
    lab_test: Optional[str] = None
    lab_result: Optional[str] = None

    # Time information
    event_date: Optional[str] = None
    recorded_date: Optional[str] = None

    # Source evidence
    source_page: int = Field(ge=1)
    evidence: str

    # Reconciliation status
    status: str = "documented"


class ClinicalDocument(BaseModel):
    """Structured information extracted from one document."""

    patient_id: str
    document_id: str
    document_name: str
    document_type: str

    events: list[ClinicalEvent] = Field(default_factory=list)


class PatientRecord(BaseModel):
    """Collection of documents belonging to one patient."""

    patient_id: str
    documents: list[ClinicalDocument] = Field(default_factory=list)
