# MEDUSA-X
### History-Aware Agentic Clinical Intelligence

MEDUSA-X is an assistive clinical-record intelligence system designed to organize fragmented medical records, reconstruct patient timelines, identify conflicting or missing information, and provide evidence-grounded answers.

## Core Features

- Clinical document processing
- Chronological patient timeline reconstruction
- Diagnosis and medication reconciliation
- Clinical Truth Ledger
- Evidence-grounded retrieval and question answering
- Safety checks and clinician escalation

## Technology Stack

- Python
- FastAPI
- ChromaDB
- Sentence Transformers
- PyMuPDF
- HTML, CSS and JavaScript
- SQLite

## Project Structure

- backend/ - Backend APIs, RAG and clinical intelligence
- frontend/ - User interface
- data/ - Local patient documents and datasets
- outputs/ - Generated reports and results

## Safety Principles

- Preserve source document and page evidence.
- Do not invent missing clinical information.
- Distinguish historical information from current information.
- Escalate unresolved conflicts for clinician review.
- MEDUSA-X does not replace professional medical judgment.

## Team

- Harshitha - Team Lead and RAG/Backend
- Meghana - Document Processing
- Prajwal - Timeline and Reconciliation
- Jathin - Frontend and Safety Interface

## Project Status

Under development for the hackathon.
