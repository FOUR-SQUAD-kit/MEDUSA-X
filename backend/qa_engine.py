import json
import os
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.rag_engine import rag_engine


load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


class ClinicalQA:
    """Evidence-grounded clinical question answering using RAG and Gemini."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _insufficient_response(
        self,
        patient_id: str,
        question: str,
        evidence: list[dict[str, Any]] | None = None,
        reason: str = "The available clinical records do not contain enough evidence to answer this question.",
    ) -> dict[str, Any]:
        return {
            "patient_id": patient_id,
            "question": question,
            "status": "insufficient",
            "answer": reason,
            "evidence": evidence or [],
            "requires_clinician_review": True,
        }

    def _build_sources(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": item["evidence_id"],
                "document_id": item["document_id"],
                "document_name": item["document_name"],
                "page": item["source_page"],
                "quote": item["evidence"],
                "event_date": item["event_date"],
                "recorded_date": item["recorded_date"],
                "retrieval_distance": item["distance"],
            }
            for item in items
        ]

    def answer_question(
        self,
        patient_id: str,
        question: str,
        top_k: int = 5,
    ) -> dict[str, Any]:

        if not patient_id or not patient_id.strip():
            raise ValueError("Patient ID is required.")

        if not question or not question.strip():
            raise ValueError("Question cannot be empty.")

        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        if self.client is None:
            return self._insufficient_response(
                patient_id,
                question,
                reason="Gemini is not configured. Please configure GEMINI_API_KEY.",
            )

        evidence_items = rag_engine.search_evidence(
            patient_id=patient_id,
            question=question,
            top_k=top_k,
        )

        if not evidence_items:
            return self._insufficient_response(patient_id, question)

        sources = self._build_sources(evidence_items)

        # Cosine distance is used as a retrieval signal, not clinical certainty.
        # Avoid generating answers from extremely weak matches.
        relevant_items = [
            item for item in evidence_items
            if item["distance"] <= 0.85
        ]

        if not relevant_items:
            return self._insufficient_response(
                patient_id,
                question,
                sources,
            )

        evidence_payload = []

        for item in relevant_items:
            evidence_payload.append({
                "evidence_id": item["evidence_id"],
                "document_name": item["document_name"],
                "page": item["source_page"],
                "event_date": item["event_date"],
                "recorded_date": item["recorded_date"],
                "evidence": item["evidence"],
            })

        prompt = f"""
You are MEDUSA-X, an evidence-grounded clinical record question-answering assistant.

PATIENT ID: {patient_id}

QUESTION:
{question}

RETRIEVED CLINICAL EVIDENCE:
{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}

STRICT RULES:
1. Answer only using the supplied evidence.
2. Never invent diagnoses, medication instructions, dates, dosages, or facts.
3. Distinguish historical information from current information.
4. A medication appearing in a discharge list does not prove that it was restarted or that the patient is currently taking it.
5. Explicitly identify contradictions, missing details, and pending verification.
6. If the evidence does not answer the question, return status "insufficient".
7. Do not make treatment recommendations or prescribe medication.
8. Do not independently resolve conflicting clinical records.
9. Every factual statement must be supported by one or more supplied evidence IDs.
10. Use only the exact evidence IDs supplied. Never fabricate citations.

Return ONLY valid JSON with this structure:
{{
  "status": "answered" or "insufficient",
  "answer": "Clear natural-language answer",
  "key_points": ["Evidence-supported point"],
  "conflicts": ["Unresolved contradiction, if any"],
  "missing_information": ["Missing information, if any"],
  "used_evidence_ids": ["Exact evidence ID"]
}}

If the records are insufficient, explain exactly what is missing.
"""

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            generated = json.loads(response.text)

            allowed_ids = {
                item["evidence_id"] for item in relevant_items
            }

            used_ids = generated.get("used_evidence_ids", [])

            if not isinstance(used_ids, list) or not set(used_ids).issubset(allowed_ids):
                raise ValueError("Gemini returned invalid evidence references.")

            status = generated.get("status")
            if status not in {"answered", "insufficient"}:
                raise ValueError("Gemini returned an invalid answer status.")

            answer = generated.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Gemini returned an empty answer.")

            cited_sources = [
                source for source in sources
                if source["evidence_id"] in used_ids
            ]

            if status == "answered" and not cited_sources:
                return self._insufficient_response(
                    patient_id,
                    question,
                    sources,
                    reason="The generated answer could not be linked to valid source evidence. Clinician verification is required.",
                )

            return {
                "patient_id": patient_id,
                "question": question,
                "status": status,
                "answer": answer,
                "key_points": generated.get("key_points", []),
                "conflicts": generated.get("conflicts", []),
                "missing_information": generated.get("missing_information", []),
                "evidence": cited_sources,
                "requires_clinician_review": True,
                "model": GEMINI_MODEL,
            }

        except Exception as error:
            return {
                "patient_id": patient_id,
                "question": question,
                "status": "generation_failed",
                "answer": (
                    "Relevant clinical evidence was retrieved, but the AI "
                    "answer could not be generated safely. Please review "
                    "the source evidence directly."
                ),
                "evidence": sources,
                "error_type": type(error).__name__,
                "requires_clinician_review": True,
            }


qa_engine = ClinicalQA()
