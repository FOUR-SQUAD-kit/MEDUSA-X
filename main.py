from fastapi.responses import FileResponse

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from backend.qa_engine import qa_engine
from backend.clinical_agent import answer_patient_question
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.document_processor import process_document
from backend.extractor import extract_information
from backend.clinical_pipeline import run_clinical_pipeline
from backend.patient_registry import load_patients, register_patient
from backend.report_history import archive_report, get_patient_history, get_all_report_history, get_report_by_id
from backend.rag_indexer import index_extraction


# --------------------------------------------------
# APPLICATION
# --------------------------------------------------

app = FastAPI(
    title="MEDUSA-X",
    description="History-Aware Agentic Clinical Intelligence",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# FRONTEND CONFIGURATION
# --------------------------------------------------

class AskQuestionRequest(BaseModel):
    question: str
    top_k: int = 5


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend" / "nexus"


# --------------------------------------------------
# HOME AND HEALTH
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "project": "MEDUSA-X",
        "status": "running",
        "message": "Clinical Intelligence API is ready",
        "frontend": "/app/"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# --------------------------------------------------
# AVAILABLE SYNTHETIC PATIENTS
# --------------------------------------------------

PATIENT_FILES = {
    "P001": BASE_DIR / "data" / "patient_001" / "ananya_output.json",
    "P002": BASE_DIR / "data" / "patient_002" / "kiran_output.json",
}


@app.get("/api/patients")
def list_patients():
    return {"patients": load_patients()}


class RegisterPatientRequest(BaseModel):
    patient_name: str


@app.post("/api/patients/register")
def create_patient(request: RegisterPatientRequest):
    try:
        patient = register_patient(request.patient_name)
        return {
            "status": "success",
            "patient": patient,
            "message": "Patient registered. Clinical records can be uploaded separately."
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


# --------------------------------------------------
# ANALYZE EXISTING SYNTHETIC PATIENT
# --------------------------------------------------

@app.get("/api/patients/{patient_id}/analysis")
def analyze_existing_patient(patient_id: str):

    patient_id = patient_id.upper()

    patient = next(
        (
            item for item in load_patients()
            if item.get("patient_id", "").upper() == patient_id
        ),
        None
    )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient not found in the registry"
        )

    reports = get_patient_history(patient_id)
    file_path = PATIENT_FILES.get(patient_id)

    if file_path:
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Patient sample file is missing"
            )

        try:
            with file_path.open("r", encoding="utf-8") as file:
                extraction = json.load(file)

            result = run_clinical_pipeline(extraction)

            return {
                "status": "success",
                "patient_id": patient_id,
                "analysis": result,
                "reports": reports,
                "workspace_status": "analysis_available"
            }

        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Patient analysis failed: {str(error)}"
            )

    empty_analysis = {
        "patient": {
            "patient_id": patient_id,
            "patient_name": patient.get("patient_name", "Patient")
        },
        "timeline": {
            "events": []
        },
        "truth_ledger": {
            "entries": [],
            "status_counts": {}
        },
        "summary": {
            "conflicts": {}
        }
    }

    return {
        "status": "success",
        "patient_id": patient_id,
        "analysis": empty_analysis,
        "reports": reports,
        "workspace_status": "reports_available" if reports else "awaiting_reports"
    }


@app.get("/api/reports/history")
def report_history():
    return {"reports": get_all_report_history()}


@app.get("/api/patients/{patient_id}/reports")
def patient_report_history(patient_id: str):
    return {"reports": get_patient_history(patient_id.upper())}




@app.get("/api/reports/{report_id}/file")
def view_archived_report(report_id: str):
    record = get_report_by_id(report_id)
    if not record:
        raise HTTPException(status_code=404, detail="Report not found")

    base_dir = Path(__file__).resolve().parent
    report_path = (base_dir / record["stored_path"]).resolve()
    upload_dir = (base_dir / "data" / "uploads").resolve()

    if not report_path.is_relative_to(upload_dir) or not report_path.is_file():
        raise HTTPException(status_code=404, detail="Archived report file not found")

    return FileResponse(
        path=report_path,
        filename=record.get("filename", "report.pdf"),
        media_type="application/pdf"
    )


@app.post("/api/analyze/upload")
async def upload_and_analyze(file: UploadFile = File(...)):

    allowed_extensions = {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".bmp"
    }

    filename = file.filename or "uploaded_document"
    extension = Path(filename).suffix.lower()

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF or supported image file"
        )

    temporary_path = None

    try:
        content = await file.read()

        if not content:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty"
            )

        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False
        ) as temporary_file:

            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)

        document = process_document(str(temporary_path))
        extraction = extract_information(document)

        patient_id = extraction.get("patient_id")
        patient_name = extraction.get("patient_name")

        patients = load_patients()
        matched_patient = next(
            (
                patient for patient in patients
                if patient.get("patient_id") == patient_id
                and patient_name
                and patient.get("patient_name", "").strip().casefold()
                    == patient_name.strip().casefold()
            ),
            None
        )

        if matched_patient:
            patient_id = matched_patient["patient_id"]
            patient_name = matched_patient["patient_name"]
        elif patient_name and patient_name.strip():
            new_patient = register_patient(patient_name)
            patient_id = new_patient["patient_id"]
            patient_name = new_patient["patient_name"]
        else:
            raise HTTPException(
                status_code=422,
                detail="Patient name could not be extracted. Please verify the report."
            )

        extraction["patient_id"] = patient_id
        extraction["patient_name"] = patient_name
        extraction["document_name"] = filename

        result = run_clinical_pipeline(extraction)

        indexing_result = index_extraction(extraction)

        summary = "; ".join(
            str(event.get("value") or event.get("evidence") or "")
            for event in extraction.get("events", [])
            if isinstance(event, dict)
            and (event.get("value") or event.get("evidence"))
        )

        report_record = archive_report(
            patient_id=patient_id,
            patient_name=patient_name,
            source_path=temporary_path,
            original_filename=filename,
            summary=summary,
            status="processed"
        )

        return {
            "status": "success",
            "filename": filename,
            "patient_id": patient_id,
            "patient_name": patient_name,
            "report_history": report_record,
            "rag_indexing": indexing_result,
            "document_type": extraction.get("document_type"),
            "extracted_information": extraction,
            "analysis": result,
            "message": "Document processed, archived and indexed. Clinician review is required."
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {str(error)}"
        )

    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

        await file.close()


# --------------------------------------------------
# SERVE MEDUSA-X NEXUS FRONTEND
# --------------------------------------------------

@app.post("/api/patients/{patient_id}/ask")
def ask_patient_question(patient_id: str, request: AskQuestionRequest):
    try:
        return qa_engine.answer_question(
            patient_id=patient_id.upper(),
            question=request.question,
            top_k=request.top_k,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Question answering failed: {str(error)}")


@app.post("/api/patients/{patient_id}/agent-ask")
def ask_patient_agent(patient_id: str, request: AskQuestionRequest):
    try:
        return answer_patient_question(
            patient_id=patient_id.upper(),
            question=request.question,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception:
        raise HTTPException(status_code=500, detail="Agentic question processing failed.")


app.mount(
    "/app",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend"
)

