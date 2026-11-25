
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

@app.get("/")
def home():
    return {
        "project": "MEDUSA-X",
        "status": "running",
        "message": "Clinical Intelligence API is ready"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}
