import os
from dotenv import load_dotenv

load_dotenv()

# storage
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")
INDEX_DIR = os.getenv("INDEX_DIR", "data/faiss_index")
URLS_FILE = os.getenv("URLS_FILE", "data/url_sources.json")
CHUNKS_FILE = os.getenv("CHUNKS_FILE", "data/chunks_store.json")

# llm provider
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "hf")

# ollama
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")

# hugging face router
HF_BASE_URL = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")
HF_MODEL = os.getenv("HF_MODEL", "deepseek-ai/DeepSeek-R1:fastest")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# generation
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
QUIZ_MAX_TOKENS = int(os.getenv("QUIZ_MAX_TOKENS", "1400"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# retrieval
DENSE_TOP_K = int(os.getenv("DENSE_TOP_K", "10"))
SPARSE_TOP_K = int(os.getenv("SPARSE_TOP_K", "10"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "6"))
RRF_K = int(os.getenv("RRF_K", "60"))
RERANK_MODEL = os.getenv(
    "RERANK_MODEL",
    "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
MIN_RERANK_SCORE = float(os.getenv("MIN_RERANK_SCORE", "-999"))
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "6"))

SUGGESTIONS_FILE = os.getenv("SUGGESTIONS_FILE", "data/suggested_questions.json")
SUGGESTION_COUNT = int(os.getenv("SUGGESTION_COUNT", "6"))