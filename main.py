
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from backend.qa_engine import qa_engine
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.document_processor import process_document
from backend.extractor import extract_information
from backend.clinical_pipeline import run_clinical_pipeline


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
    return {
        "patients": [
            {"patient_id": "P001", "patient_name": "Ananya"},
            {"patient_id": "P002", "patient_name": "Kiran"},
        ]
    }


# --------------------------------------------------
# ANALYZE EXISTING SYNTHETIC PATIENT
# --------------------------------------------------

@app.get("/api/patients/{patient_id}/analysis")
def analyze_existing_patient(patient_id: str):

    patient_id = patient_id.upper()

    if patient_id not in PATIENT_FILES:
        raise HTTPException(
            status_code=404,
            detail="Synthetic patient not found"
        )

    file_path = PATIENT_FILES[patient_id]

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
            "analysis": result
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Patient analysis failed: {str(error)}"
        )


# --------------------------------------------------
# UPLOAD AND ANALYZE CLINICAL DOCUMENT
# --------------------------------------------------

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

        if not patient_id:
            raise HTTPException(
                status_code=422,
                detail="Patient ID could not be extracted from the document"
            )

        result = run_clinical_pipeline(extraction)

        return {
            "status": "success",
            "filename": filename,
            "patient_id": patient_id,
            "document_type": extraction.get("document_type"),
            "extracted_information": extraction,
            "analysis": result,
            "message": "Document processed and clinical analysis completed. Clinician review is required."
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


app.mount(
    "/app",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend"
)
