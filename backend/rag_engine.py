
from pathlib import Path
from typing import Any
from uuid import uuid4

import chromadb
from sentence_transformers import SentenceTransformer


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = PROJECT_ROOT / "backend" / "chroma_db"

# Embedding model
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class ClinicalRAG:
    """Stores and retrieves patient-specific clinical evidence."""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_PATH)
        )

        self.collection = self.client.get_or_create_collection(
            name="clinical_records",
            metadata={"hnsw:space": "cosine"}
        )

        self.model = SentenceTransformer(EMBEDDING_MODEL)

    def add_evidence(
        self,
        patient_id: str,
        document_id: str,
        document_name: str,
        source_page: int,
        evidence: str,
        event_date: str | None = None,
        recorded_date: str | None = None,
    ) -> str:
        """Store one evidence passage with its source details."""

        if not evidence.strip():
            raise ValueError("Evidence text cannot be empty.")

        if not patient_id or not document_id:
            raise ValueError("Patient ID and document ID are required.")

        if source_page < 1:
            raise ValueError("Source page must be at least 1.")

        evidence_id = (
            str(uuid4())
        )

        embedding = self.model.encode(
            evidence,
            normalize_embeddings=True
        ).tolist()

        self.collection.upsert(
            ids=[evidence_id],
            documents=[evidence],
            embeddings=[embedding],
            metadatas=[{
                "patient_id": patient_id,
                "document_id": document_id,
                "document_name": document_name,
                "source_page": source_page,
                "event_date": event_date or "",
                "recorded_date": recorded_date or "",
            }]
        )

        return evidence_id

    def search_evidence(
        self,
        patient_id: str,
        question: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant evidence for one patient only."""

        if not patient_id:
            raise ValueError("Patient ID is required.")

        if not question.strip():
            raise ValueError("Search question cannot be empty.")

        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        query_embedding = self.model.encode(
            question,
            normalize_embeddings=True
        ).tolist()

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"patient_id": patient_id},
            include=["documents", "metadatas", "distances"]
        )

        evidence_items = []

        for index, document in enumerate(
            results["documents"][0]
        ):
            metadata = results["metadatas"][0][index]
            distance = results["distances"][0][index]

            evidence_items.append({
                "evidence": document,
                "patient_id": metadata["patient_id"],
                "document_id": metadata["document_id"],
                "document_name": metadata["document_name"],
                "source_page": metadata["source_page"],
                "event_date": metadata["event_date"] or None,
                "recorded_date": metadata["recorded_date"] or None,
                "distance": distance,
            })

        return evidence_items


# Shared instance for backend integration
rag_engine = ClinicalRAG()
