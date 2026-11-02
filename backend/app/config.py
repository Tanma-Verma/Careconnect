import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def is_gemini_compatible(url):
    parsed = urlparse(url)
    return parsed.hostname == "generativelanguage.googleapis.com" and parsed.path.rstrip("/") == "/v1beta/openai"


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "postgresql://careconnect:careconnect@postgres:5432/careconnect"))
    origin: str = field(default_factory=lambda: os.getenv("APP_ORIGIN", "http://localhost:3000").rstrip("/"))
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    session_hours: int = field(default_factory=lambda: int(os.getenv("SESSION_HOURS", "12")))
    documents_dir: Path = field(default_factory=lambda: Path(os.getenv("DOCUMENTS_DIR", "/data/documents")))
    frontend_dir: Path = field(default_factory=lambda: Path(os.getenv("FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend"))))
    chroma_host: str = field(default_factory=lambda: os.getenv("CHROMA_HOST", "chroma"))
    chroma_port: int = field(default_factory=lambda: int(os.getenv("CHROMA_PORT", "8000")))
    embedding_url: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_BASE_URL", "").rstrip("/"))
    embedding_key: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_KEY", ""))
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", ""))
    llm_url: str = field(default_factory=lambda: os.getenv("LLM_API_BASE_URL", "").rstrip("/"))
    llm_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    provider_timeout: float = field(default_factory=lambda: float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "45")))
    max_distance: float = field(default_factory=lambda: float(os.getenv("MAX_COSINE_DISTANCE", "0.65")))
    max_upload: int = 10 * 1024 * 1024
    max_pages: int = 50
    max_text: int = 100_000

    @property
    def pipeline(self):
        # Changing model, endpoint or chunking creates an independent vector collection.
        value = f"{self.embedding_url}|{self.embedding_model}|chars1600-overlap240-v1"
        return hashlib.sha256(value.encode()).hexdigest()[:20]

    def validate(self):
        parsed = urlparse(self.origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("APP_ORIGIN must be a single http(s) origin without a path")
        if parsed.scheme == "https" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true for HTTPS")
        if not 1 <= self.session_hours <= 168 or not 1 <= self.provider_timeout <= 120:
            raise ValueError("Invalid session duration or provider timeout")
        if not 0 <= self.max_distance <= 2:
            raise ValueError("MAX_COSINE_DISTANCE must be between 0 and 2")
        for url in [self.embedding_url, self.llm_url]:
            parsed = urlparse(url)
            if url and (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("External provider base URLs must use HTTPS without credentials, query or fragment")
