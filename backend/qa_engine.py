
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

        if not patient_id:
            raise ValueError("Patient ID is required.")

        if not question.strip():
            raise ValueError("Question cannot be empty.")

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
                    "enough evidence to answer this question."
                ),
                "evidence": [],
                "requires_clinician_review": True,
            }

        sources = []

        for item in evidence_items:
            sources.append({
                "document_id": item["document_id"],
                "document_name": item["document_name"],
                "page": item["source_page"],
                "quote": item["evidence"],
                "event_date": item["event_date"],
                "recorded_date": item["recorded_date"],
            })

        return {
            "patient_id": patient_id,
            "question": question,
            "status": "evidence_retrieved",
            "answer": (
                "Relevant clinical evidence was retrieved. "
                "A grounded answer requires evidence reconciliation "
                "and language-model processing."
            ),
            "evidence": sources,
            "requires_clinician_review": False,
        }


# Shared QA engine instance
qa_engine = ClinicalQA()
