
from typing import Any

from backend.rag_engine import rag_engine


class ClinicalQA:
    """Evidence-grounded question answering for clinical records."""

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

        evidence_items = rag_engine.search_evidence(
            patient_id=patient_id,
            question=question,
            top_k=top_k,
        )

        if not evidence_items:
            return {
                "patient_id": patient_id,
                "question": question,
                "status": "insufficient",
                "answer": (
                    "The available clinical records do not contain "
                    "enough evidence to answer this question. "
                    "No clinical conclusion has been generated."
                ),
                "evidence": [],
                "requires_clinician_review": True,
            }

        sources = []

        for item in evidence_items:
            sources.append({
                "evidence_id": item["evidence_id"],
                "document_id": item["document_id"],
                "document_name": item["document_name"],
                "page": item["source_page"],
                "quote": item["evidence"],
                "event_date": item["event_date"],
                "recorded_date": item["recorded_date"],
                "retrieval_distance": item["distance"],
            })

        return {
            "patient_id": patient_id,
            "question": question,
            "status": "evidence_retrieved",
            "answer": (
                "Relevant clinical evidence was retrieved from "
                "the patient's records. This evidence has not yet "
                "been reconciled or verified. A clinical conclusion "
                "cannot be generated at this stage."
            ),
            "evidence": sources,
            "requires_clinician_review": True,
        }


# Shared QA engine instance
qa_engine = ClinicalQA()
