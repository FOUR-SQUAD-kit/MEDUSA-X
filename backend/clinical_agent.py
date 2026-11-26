
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.report_history import (
    BASE_DIR,
    UPLOAD_DIR,
    get_patient_history,
)
from backend.document_processor import process_document
from backend.extractor import extract_information
from backend.clinical_pipeline import run_multi_document_pipeline


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv(BASE_DIR / ".env")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

MAX_TOOL_CALLS = 6

_client = None


def get_gemini_client():
    global _client

    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured."
            )

        _client = genai.Client(api_key=api_key)

    return _client


# --------------------------------------------------
# SECURITY: PATIENT ARCHIVE VALIDATION
# --------------------------------------------------

def get_safe_report_path(patient_id: str, record: dict) -> Path:
    """
    Allow access only to files inside this patient's archive folder.
    """

    expected_folder = (
        UPLOAD_DIR / patient_id
    ).resolve()

    stored_path = record.get("stored_path")

    if not stored_path:
        raise ValueError("Archived file path is missing.")

    file_path = (
        BASE_DIR / stored_path
    ).resolve()

    if not file_path.is_relative_to(expected_folder):
        raise ValueError(
            "Report path is outside the patient's archive."
        )

    if not file_path.is_file():
        raise FileNotFoundError(
            "Archived report file was not found."
        )

    return file_path


# --------------------------------------------------
# TOOL 1: RETRIEVE PATIENT REPORTS
# --------------------------------------------------

def list_patient_reports(patient_id: str) -> dict:
    records = get_patient_history(patient_id)

    reports = []

    for record in records:
        reports.append({
            "report_id": record.get("report_id"),
            "filename": record.get("filename"),
            "uploaded_at": record.get("uploaded_at"),
            "status": record.get("status"),
            "summary": record.get("summary"),
        })

    return {
        "patient_id": patient_id,
        "report_count": len(reports),
        "reports": reports,
    }


# --------------------------------------------------
# TOOL 2: ANALYSE ARCHIVED PATIENT HISTORY
# --------------------------------------------------

def analyse_patient_history(
    patient_id: str,
    patient_name: str,
    analysis_cache: dict,
) -> dict:

    # Approved synthetic test patients only.
    synthetic_patients = {
        "P001": ("Ananya", "data/patient_001/ananya_output.json"),
        "P002": ("Kiran", "data/patient_002/kiran_output.json"),
    }

    if patient_id in synthetic_patients:
        trusted_name, relative_file = synthetic_patients[patient_id]
        synthetic_path = (BASE_DIR / relative_file).resolve()

        if not synthetic_path.is_relative_to(BASE_DIR.resolve()):
            raise ValueError("Synthetic record path is invalid.")

        with synthetic_path.open("r", encoding="utf-8") as file:
            extraction = json.load(file)

        if extraction.get("patient_id") != patient_id:
            raise ValueError("Synthetic patient ID does not match.")

        if not isinstance(extraction.get("events"), list):
            raise ValueError("Synthetic record events are invalid.")

        extraction["patient_name"] = trusted_name
        extraction.setdefault("document_name", synthetic_path.name)

        analysis = run_multi_document_pipeline([extraction])
        analysis_cache["analysis"] = analysis

        return {
            "status": "completed",
            "patient_id": patient_id,
            "processed_reports": 1,
            "failed_reports": 0,
            "processing_errors": [],
            "summary": analysis["summary"],
            "timeline": analysis["timeline"],
            "conflict_report": analysis["conflict_report"],
            "truth_ledger": analysis["truth_ledger"],
            "quality_warnings": analysis["quality_warnings"],
        }

    records = get_patient_history(patient_id)

    if not records:
        return {
            "status": "insufficient_evidence",
            "message": "No archived reports were found.",
            "report_count": 0,
        }

    extractions = []
    processing_errors = []

    for record in records:

        try:
            file_path = get_safe_report_path(
                patient_id,
                record,
            )

            document = process_document(str(file_path))

            extraction = extract_information(document)

            # Trusted archive identity takes precedence.
            extraction["patient_id"] = patient_id
            extraction["patient_name"] = (
                record.get("patient_name")
                or patient_name
            )
            extraction["document_name"] = (
                record.get("filename")
            )

            extractions.append(extraction)

        except Exception as error:
            processing_errors.append({
                "filename": record.get("filename"),
                "error": str(error),
            })

    if not extractions:
        return {
            "status": "insufficient_evidence",
            "message": "No archived reports could be processed.",
            "processing_errors": processing_errors,
        }

    analysis = run_multi_document_pipeline(extractions)

    analysis_cache["analysis"] = analysis

    return {
        "status": "completed",
        "patient_id": patient_id,
        "processed_reports": len(extractions),
        "failed_reports": len(processing_errors),
        "processing_errors": processing_errors,
        "summary": analysis["summary"],
        "timeline": analysis["timeline"],
        "conflict_report": analysis["conflict_report"],
        "truth_ledger": analysis["truth_ledger"],
        "quality_warnings": analysis["quality_warnings"],
    }


# --------------------------------------------------
# TOOL 3: INSPECT CLINICAL EVIDENCE
# --------------------------------------------------

def inspect_clinical_evidence(
    analysis_cache: dict,
    query: str = "",
) -> dict:

    analysis = analysis_cache.get("analysis")

    if not analysis:
        return {
            "status": "analysis_not_available",
            "message": "Run patient history analysis first.",
        }

    query_words = {
        word.lower()
        for word in query.split()
        if len(word) > 2
    }

    timeline = analysis.get("timeline", {})
    events = timeline.get("events", [])

    conflicts = analysis.get(
        "conflict_report", {}
    ).get("conflicts", [])

    ledger = analysis.get(
        "truth_ledger", {}
    ).get("entries", [])

    def matches(item):
        if not query_words:
            return True

        searchable = json.dumps(
            item,
            default=str
        ).lower()

        return any(
            word in searchable
            for word in query_words
        )

    relevant_events = [
        event for event in events
        if matches(event)
    ]

    relevant_conflicts = [
        conflict for conflict in conflicts
        if matches(conflict)
    ]

    relevant_ledger = [
        entry for entry in ledger
        if matches(entry)
    ]

    return {
        "status": "completed",
        "query": query,
        "evidence_events": relevant_events[:40],
        "conflicts": relevant_conflicts[:30],
        "truth_ledger_entries": relevant_ledger[:30],
    }


# --------------------------------------------------
# GEMINI TOOL DECLARATIONS
# --------------------------------------------------

FUNCTION_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="list_patient_reports",
            description=(
                "List the archived reports belonging to the "
                "current patient. Use this to understand which "
                "reports are available."
            ),
            parameters_json_schema={
                "type": "OBJECT",
                "properties": {},
            },
        ),

        types.FunctionDeclaration(
            name="analyse_patient_history",
            description=(
                "Reprocess all archived reports for the current "
                "patient and run multi-document clinical timeline, "
                "reconciliation and Truth Ledger analysis. "
                "Use this before answering questions that require "
                "cross-report investigation."
            ),
            parameters_json_schema={
                "type": "OBJECT",
                "properties": {},
            },
        ),

        types.FunctionDeclaration(
            name="inspect_clinical_evidence",
            description=(
                "Inspect timeline events, conflicts and Truth "
                "Ledger entries from the completed patient analysis. "
                "Use the question or relevant clinical subject "
                "as the query."
            ),
            parameters_json_schema={
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": (
                            "Clinical subject or question to "
                            "search in the existing analysis."
                        ),
                    }
                },
                "required": ["query"],
            },
        ),
    ]
)


# --------------------------------------------------
# MAIN AGENT: CONTROLLED TOOL-CALLING LOOP
# --------------------------------------------------

def answer_patient_question(
    patient_id: str,
    question: str,
) -> dict:

    patient_id = patient_id.upper().strip()
    question = question.strip()

    if not patient_id:
        raise ValueError("Patient ID is required.")

    if not question:
        raise ValueError("Question cannot be empty.")

    if len(question) > 1000:
        raise ValueError("Question is too long.")

    # Patient identity comes from the API, never from Gemini.
    history = get_patient_history(patient_id)

    synthetic_names = {
        "P001": "Ananya",
        "P002": "Kiran",
    }

    is_synthetic = patient_id in synthetic_names

    if not history and not is_synthetic:
        return {
            "status": "insufficient_evidence",
            "answer": (
                "No archived reports are available "
                "for this patient."
            ),
            "evidence": [],
            "requires_clinician_review": True,
        }

    patient_name = (
        synthetic_names[patient_id]
        if is_synthetic
        else history[0].get("patient_name") or "Unknown"
    )

    analysis_cache = {}

    # Only these three functions can be executed.
    allowed_tools = {
        "list_patient_reports": lambda args: (
            list_patient_reports(patient_id)
        ),
        "analyse_patient_history": lambda args: (
            analyse_patient_history(
                patient_id,
                patient_name,
                analysis_cache,
            )
        ),
        "inspect_clinical_evidence": lambda args: (
            inspect_clinical_evidence(
                analysis_cache,
                args.get("query", ""),
            )
        ),
    }

    system_instruction = """
You are MEDUSA-X, an agentic clinical information
reconciliation and evidence verification assistant.

Your task is to investigate patient records, not to diagnose
or prescribe treatment.

You must:

1. Understand the user's clinical question.
2. Decide which approved tools are required.
3. Inspect available reports before making conclusions.
4. Run patient history analysis when cross-report evidence
   or clinical history is needed.
5. Inspect relevant timeline events, conflicts and Truth Ledger
   entries before answering.
6. Compare dates and source documents carefully.
7. Distinguish documented facts, historical information,
   contradictions, missing information and uncertainty.
8. Never invent clinical facts or evidence.
9. Never assume a medicine is currently being taken merely
   because it appears in a report.
10. Never interpret a missing event as proof that it did not occur.

Use only information returned by the tools.

If evidence is insufficient, clearly say so.

Do not make diagnoses, recommend treatments, prescribe
medications or modify clinical decisions.

Cite available document names, page numbers and evidence
references when provided.

Every final response must state that clinician review is required.
"""


    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"Current patient: {patient_id}\n"
                        f"Patient name: {patient_name}\n"
                        f"Question: {question}"
                    )
                )
            ],
        )
    ]

    tool_trace = []
    tool_call_count = 0

    try:
        client = get_gemini_client()

        while tool_call_count < MAX_TOOL_CALLS:

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=2500,
                    tools=[FUNCTION_TOOLS],
                    automatic_function_calling=types.
                        AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                ),
            )

            if not response.candidates:
                raise RuntimeError(
                    "Gemini returned no response."
                )

            model_content = response.candidates[0].content

            function_calls = [
                part.function_call
                for part in model_content.parts
                if part.function_call
            ]

            if not function_calls:

                return {
                    "status": "completed",
                    "answer": response.text or (
                        "The agent could not generate a final answer."
                    ),
                    "tool_trace": tool_trace,
                    "requires_clinician_review": True,
                }

            contents.append(model_content)

            for function_call in function_calls:

                if tool_call_count >= MAX_TOOL_CALLS:
                    break

                tool_name = function_call.name
                arguments = dict(function_call.args or {})

                if tool_name not in allowed_tools:
                    tool_result = {
                        "status": "rejected",
                        "message": "Tool is not permitted.",
                    }

                else:
                    try:
                        tool_result = allowed_tools[
                            tool_name
                        ](arguments)

                    except Exception as error:
                        tool_result = {
                            "status": "tool_error",
                            "message": str(error),
                        }

                tool_call_count += 1

                tool_trace.append({
                    "tool": tool_name,
                    "status": tool_result.get(
                        "status",
                        "completed"
                    ),
                })

                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name,
                                response=tool_result,
                            )
                        ],
                    )
                )

        return {
            "status": "incomplete",
            "answer": (
                "The investigation reached its tool-call limit. "
                "A complete evidence-based answer could not "
                "be generated."
            ),
            "tool_trace": tool_trace,
            "requires_clinician_review": True,
        }

    except Exception as error:
        return {
            "status": "error",
            "answer": (
                "The clinical investigation could not be completed."
            ),
            "error": str(error),
            "tool_trace": tool_trace,
            "requires_clinician_review": True,
        }
