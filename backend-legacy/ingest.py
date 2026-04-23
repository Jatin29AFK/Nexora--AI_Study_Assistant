import json
import os
import shutil
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import UPLOAD_DIR, INDEX_DIR, URLS_FILE, REQUEST_TIMEOUT, CHUNKS_FILE


def get_embedding_model():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

def ensure_data_files():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(URLS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(CHUNKS_FILE), exist_ok=True)

    if not os.path.exists(URLS_FILE):
        with open(URLS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def count_uploaded_pdfs():
    ensure_data_files()
    return len([f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(".pdf")])


def load_url_sources():
    ensure_data_files()
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_url_sources(urls):
    ensure_data_files()
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2, ensure_ascii=False)


def count_url_sources():
    return len(load_url_sources())


def add_url_source(url: str):
    urls = load_url_sources()

    if any(item["url"] == url for item in urls):
        return False

    urls.append({
        "url": url,
        "added_at": datetime.utcnow().isoformat()
    })
    save_url_sources(urls)
    return True


def delete_url_source(url: str):
    urls = load_url_sources()
    updated = [item for item in urls if item["url"] != url]

    if len(updated) == len(urls):
        return False

    save_url_sources(updated)
    return True


def fetch_url_document(url: str):
    from langchain_core.documents import Document
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AIKnowledgeCopilot/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    # try to find main docs/article area first
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id="main-content")
        or soup.find(class_="document")
        or soup.find(class_="bd-main")
    )

    root = main if main else soup

    parts = []
    for tag in root.find_all(["h1", "h2", "h3", "p", "li", "pre", "code"]):
        text = tag.get_text(" ", strip=True)
        if text:
            parts.append(text)

    text = "\n".join(parts)
    text = " ".join(text.split())

    if not text.strip():
        text = root.get_text(" ", strip=True)

    if not text.strip():
        raise ValueError(f"Could not extract readable content from {url}")

    return Document(
        page_content=text,
        metadata={
            "source_type": "url",
            "source_file": url,
            "title": title
        }
    )


def save_chunk_store(split_docs):
    chunk_payload = []

    for doc in split_docs:
        chunk_payload.append({
            "chunk_id": doc.metadata["chunk_id"],
            "text": doc.page_content,
            "metadata": doc.metadata
        })

    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        json.dump(chunk_payload, f, indent=2, ensure_ascii=False)


def ingest_all_sources():
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    ensure_data_files()

    pdf_files = [
        os.path.join(UPLOAD_DIR, f)
        for f in os.listdir(UPLOAD_DIR)
        if f.lower().endswith(".pdf")
    ]

    url_sources = load_url_sources()
    all_docs = []

    for pdf_path in pdf_files:
        loader = PyPDFLoader(pdf_path)
        documents = loader.load()

        for doc in documents:
            doc.metadata["source_type"] = "pdf"
            doc.metadata["source_file"] = os.path.basename(pdf_path)

        all_docs.extend(documents)

    url_success_count = 0
    url_failures = []

    for item in url_sources:
        url = item["url"]
        try:
            doc = fetch_url_document(url)
            all_docs.append(doc)
            url_success_count += 1
        except Exception as e:
            url_failures.append({
                "url": url,
                "error": str(e)
            })

    if not all_docs:
        raise ValueError("No PDFs or valid URLs available for indexing")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=80
    )

    split_docs = text_splitter.split_documents(all_docs)

    for i, doc in enumerate(split_docs):
        doc.metadata["chunk_id"] = f"chunk_{i}"

    save_chunk_store(split_docs)

    embeddings = get_embedding_model()

    if os.path.exists(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)

    vectorstore = FAISS.from_documents(split_docs, embeddings)
    vectorstore.save_local(INDEX_DIR)

    return {
        "message": "Index created successfully",
        "pdf_files_indexed": len(pdf_files),
        "urls_indexed": url_success_count,
        "chunks_created": len(split_docs),
        "url_failures": url_failures,
    }