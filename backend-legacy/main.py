import json
import os
import shutil
from pydantic import BaseModel, Field
from typing import Literal, List

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import StreamingResponse

from quiz import list_quiz_sources, generate_quiz, submit_quiz
from quiz_models import QuizSource, QuizGenerateRequest, QuizPublic, QuizSubmission, QuizResult

from llm_utils import stream_answer

from suggestions import (
    generate_suggested_questions,
    load_suggested_questions,
    clear_suggested_questions,
)

from ingest import (
    ingest_all_sources,
    count_uploaded_pdfs,
    count_url_sources,
    load_url_sources,
    add_url_source,
    delete_url_source,
)
from query import ask_question, clear_retrieval_cache, build_answer_payload
from config import UPLOAD_DIR, INDEX_DIR, URLS_FILE, CHUNKS_FILE

app = FastAPI(title="Nexora")

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nexora-one-ashen.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app_state = {
    "indexing": False,
    "last_index_result": None,
    "last_error": None,
}

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str

class AskRequest(BaseModel):
    query: str
    answer_mode: Literal[
        "balanced",
        "concise",
        "detailed",
        "bullet",
        "beginner",
        "exam",
    ] = "balanced"
    history: List[HistoryMessage] = Field(default_factory=list)

def run_index_job():
    app_state["indexing"] = True
    app_state["last_error"] = None

    try:
        result = ingest_all_sources()
        clear_retrieval_cache()
        generate_suggested_questions()
        app_state["last_index_result"] = result
    except Exception as e:
        app_state["last_error"] = str(e)
    finally:
        app_state["indexing"] = False


def start_indexing_if_possible(background_tasks: BackgroundTasks):
    if app_state["indexing"]:
        return

    background_tasks.add_task(run_index_job)


def reset_all_app_data():
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    if os.path.exists(CHUNKS_FILE):
        with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    if os.path.exists(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)

    clear_retrieval_cache()
    clear_suggested_questions()

    app_state["indexing"] = False
    app_state["last_index_result"] = None
    app_state["last_error"] = None

def sse_event(data: dict):
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "indexing": app_state["indexing"],
        "last_index_result": app_state["last_index_result"],
        "last_error": app_state["last_error"],
        "documents_count": count_uploaded_pdfs(),
        "urls_count": count_url_sources(),
        "index_exists": os.path.exists(INDEX_DIR) and os.path.exists(CHUNKS_FILE),
    }


@app.post("/reset")
def reset_app():
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Cannot reset while processing is running",
        )

    try:
        reset_all_app_data()
        return {"message": "Session reset successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
def upload_pdfs(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_files = []

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"{file.filename} is not a PDF",
            )

        file_path = os.path.join(UPLOAD_DIR, file.filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        saved_files.append(file.filename)

    clear_retrieval_cache()
    app_state["last_index_result"] = None
    app_state["last_error"] = None

    clear_suggested_questions()
    start_indexing_if_possible(background_tasks)

    return {
        "message": "Files uploaded successfully. Processing started in background.",
        "uploaded_files": saved_files,
    }


@app.get("/documents")
def list_documents():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    documents = []
    for filename in sorted(os.listdir(UPLOAD_DIR)):
        if filename.lower().endswith(".pdf"):
            file_path = os.path.join(UPLOAD_DIR, filename)
            size_kb = round(os.path.getsize(file_path) / 1024, 1)
            documents.append(
                {
                    "name": filename,
                    "size_kb": size_kb,
                }
            )

    return {
        "count": len(documents),
        "documents": documents,
    }


@app.delete("/documents/{filename}")
def delete_document(filename: str, background_tasks: BackgroundTasks):
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete while processing is running",
        )

    file_path = os.path.join(UPLOAD_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Document not found")

    os.remove(file_path)

    clear_retrieval_cache()
    app_state["last_index_result"] = None
    app_state["last_error"] = None

    clear_suggested_questions()
    start_indexing_if_possible(background_tasks)

    return {
        "message": f"{filename} deleted successfully. Re-processing started.",
    }


@app.get("/urls")
def list_urls():
    return {
        "count": count_url_sources(),
        "urls": load_url_sources(),
    }


@app.post("/urls")
def add_url(
    background_tasks: BackgroundTasks,
    url: str = Query(..., min_length=5),
):
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="URL must start with http:// or https://",
        )

    added = add_url_source(url)

    if not added:
        raise HTTPException(status_code=409, detail="URL already exists")

    clear_retrieval_cache()
    app_state["last_index_result"] = None
    app_state["last_error"] = None

    clear_suggested_questions()
    start_indexing_if_possible(background_tasks)

    return {
        "message": "URL added successfully. Processing started in background.",
        "url": url,
    }

@app.get("/suggested-questions")
def get_suggested_questions():
    return {
        "suggestions": load_suggested_questions()
    }

@app.delete("/urls")
def remove_url(
    background_tasks: BackgroundTasks,
    url: str = Query(..., min_length=5),
):
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete URL while processing is running",
        )

    removed = delete_url_source(url)

    if not removed:
        raise HTTPException(status_code=404, detail="URL not found")

    clear_retrieval_cache()
    app_state["last_index_result"] = None
    app_state["last_error"] = None

    clear_suggested_questions()
    start_indexing_if_possible(background_tasks)

    return {
        "message": "URL deleted successfully. Re-processing started.",
        "url": url,
    }


@app.post("/ask")
def ask(request: AskRequest):
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Your sources are still being processed. Please wait a moment.",
        )

    if not (os.path.exists(INDEX_DIR) and os.path.exists(CHUNKS_FILE)):
        raise HTTPException(
            status_code=400,
            detail="No indexed content available yet. Upload PDFs or URLs first.",
        )

    try:
        return ask_question(
            query=request.query,
            answer_mode=request.answer_mode,
            history=request.history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/ask/stream")
def ask_stream(request: AskRequest):
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Your sources are still being processed. Please wait a moment.",
        )

    if not (os.path.exists(INDEX_DIR) and os.path.exists(CHUNKS_FILE)):
        raise HTTPException(
            status_code=400,
            detail="No indexed content available yet. Upload PDFs or URLs first.",
        )

    def event_generator():
        try:
            payload = build_answer_payload(
                query=request.query,
                answer_mode=request.answer_mode,
                history=request.history,
            )

            if "fallback_answer" in payload:
                yield sse_event({
                    "type": "chunk",
                    "content": payload["fallback_answer"],
                })
                yield sse_event({
                    "type": "done",
                    "sources": payload.get("sources", []),
                })
                return

            for chunk in stream_answer(
                payload["prompt"],
                max_tokens=payload["max_tokens"],
            ):
                if chunk:
                    yield sse_event({
                        "type": "chunk",
                        "content": chunk,
                    })

            yield sse_event({
                "type": "done",
                "sources": payload["sources"],
            })

        except Exception as e:
            yield sse_event({
                "type": "error",
                "message": str(e),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/quiz/sources", response_model=list[QuizSource])
def get_quiz_sources():
    return list_quiz_sources()


@app.post("/quiz/generate", response_model=QuizPublic)
def create_quiz(request: QuizGenerateRequest):
    if app_state["indexing"]:
        raise HTTPException(
            status_code=409,
            detail="Your sources are still being processed. Please wait a moment.",
        )

    try:
        return generate_quiz(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/quiz/submit", response_model=QuizResult)
def grade_quiz(request: QuizSubmission):
    try:
        return submit_quiz(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))