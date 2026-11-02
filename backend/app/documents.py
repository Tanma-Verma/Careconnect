import io
import re
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader


def extract(filename, media_type, data, settings):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise HTTPException(415, "Only text-based PDF and UTF-8 TXT files are supported.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    if len(data) > settings.max_upload:
        raise HTTPException(413, "Maximum upload size is 10 MiB.")
    if suffix == ".txt":
        if media_type not in {"text/plain", "application/octet-stream", ""} or data.startswith(b"%PDF"):
            raise HTTPException(415, "File content/type does not match UTF-8 TXT.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "TXT documents must use UTF-8 encoding.") from None
        if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise HTTPException(422, "Binary/control characters are not allowed in TXT documents.")
        pages = [(None, text)]
        media_type = "text/plain"
    else:
        if media_type not in {"application/pdf", "application/octet-stream", ""} or not data.startswith(b"%PDF-"):
            raise HTTPException(415, "File content/type does not match PDF.")
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise HTTPException(422, "Encrypted PDFs are not supported.")
            if not 1 <= len(reader.pages) <= settings.max_pages:
                raise HTTPException(422, f"PDF must contain 1–{settings.max_pages} pages.")
            pages = []
            total = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                total += len(text)
                if total > settings.max_text:
                    raise HTTPException(422, "Document has too much text (maximum 100,000 characters).")
                pages.append((number, text))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "PDF could not be read. Upload a valid text-based PDF.") from None
        media_type = "application/pdf"
    if sum(len(text) for _, text in pages) > settings.max_text:
        raise HTTPException(422, "Document has too much text (maximum 100,000 characters).")
    if not any(text.strip() for _, text in pages):
        raise HTTPException(422, "No text found. Scanned PDFs require OCR, which is not supported.")
    return pages, media_type


def chunk_pages(pages, document_id):
    chunks = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text.replace("\x00", "")).strip()
        start = 0
        while start < len(text):
            end = min(start + 1600, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + 1100, end)
                if boundary > start:
                    end = boundary
            excerpt = text[start:end].strip()
            if excerpt:
                chunks.append({"id": f"{document_id}:{len(chunks)}", "page": page, "text": excerpt})
            if end == len(text):
                break
            start = end - 240
    return chunks
