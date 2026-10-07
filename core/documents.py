"""PDF/DOCX/TXT text extraction and chunking."""

import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_TYPES = ("pdf", "docx", "txt")

# all-MiniLM-L6-v2 only reads the first 256 word-pieces of a text (~190 words), so chunks
# are kept under that; longer chunks would be silently truncated when embedded.
CHUNK_WORDS = 180
CHUNK_OVERLAP = 40
MIN_CHUNK_WORDS = 30
# Words per pseudo-page for DOCX/TXT, which have no real pages.
SECTION_WORDS = 400


class DocumentError(ValueError):
    """The file can't be read or has no usable text."""


@dataclass
class Page:
    number: int | None  # 1-based PDF page; None for DOCX/TXT
    text: str


@dataclass
class Chunk:
    text: str
    page: int | None
    index: int  # position of the chunk within its document


def extract_pages(filename: str, data: bytes) -> list[Page]:
    """Extract text page by page. Raises DocumentError for unsupported or empty files."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_TYPES:
        raise DocumentError(f"Unsupported file type '.{ext}'. Use PDF, DOCX or TXT.")
    if not data:
        raise DocumentError(f"{filename} is empty.")
    try:
        if ext == "pdf":
            pages = _pdf_pages(data)
        elif ext == "docx":
            pages = _sections(_docx_text(data))
        else:
            pages = _sections(data.decode("utf-8", errors="replace"))
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not read {filename}: {exc}") from exc

    pages = [p for p in pages if p.text.strip()]
    if not pages:
        raise DocumentError(
            f"No text found in {filename}. If it is a scanned PDF, use a text-based version."
        )
    return pages


def _pdf_pages(data: bytes) -> list[Page]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    texts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        # Some PDFs (e.g. exported from web editors) come out with one word per line in
        # pypdf's default mode; layout mode reconstructs their lines properly.
        if _looks_word_per_line(text):
            text = page.extract_text(extraction_mode="layout") or text
        texts.append(text)
    texts = _strip_repeated_lines(texts)
    return [Page(number=i + 1, text=clean_text(t)) for i, t in enumerate(texts)]


def _docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _sections(text: str) -> list[Page]:
    """Split page-less text into ~SECTION_WORDS blocks on paragraph boundaries."""
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", clean_text(text)) if p.strip()]
    sections, current, count = [], [], 0
    for para in paragraphs:
        current.append(para)
        count += len(para.split())
        if count >= SECTION_WORDS:
            sections.append("\n".join(current))
            current, count = [], 0
    if current:
        sections.append("\n".join(current))
    return [Page(number=None, text=s) for s in sections]


def _looks_word_per_line(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 20:
        return False
    words = sum(len(ln.split()) for ln in lines)
    return words / len(lines) < 1.5


def _strip_repeated_lines(pages: list[str], edge: int = 3) -> list[str]:
    """Remove headers/footers: lines in the top or bottom `edge` lines of a page that
    repeat on most pages (ignoring page numbers). Body lines like "Answer:" are kept."""
    if len(pages) < 3:
        return pages

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    def edge_lines(text: str) -> list[str]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[:edge] + lines[-edge:]

    counts = Counter()
    for text in pages:
        counts.update({key(ln) for ln in edge_lines(text)})
    repeated = {k for k, n in counts.items() if n >= max(3, len(pages) * 0.5)}

    cleaned = []
    for text in pages:
        lines = text.splitlines()
        nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_idx = set(nonempty[:edge] + nonempty[-edge:])
        cleaned.append(
            "\n".join(
                ln for i, ln in enumerate(lines) if not (i in edge_idx and key(ln) in repeated)
            )
        )
    return cleaned


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("�", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(
    pages: list[Page], size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    """Split each page into overlapping word windows. Chunks never span pages,
    so every chunk has exactly one page to cite."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: list[Chunk] = []
    for page in pages:
        words = page.text.split()
        if not words:
            continue
        start = 0
        while True:
            end = min(start + size, len(words))
            # Fold a short tail into this chunk instead of making a tiny one.
            if len(words) - end < MIN_CHUNK_WORDS:
                end = len(words)
            chunks.append(Chunk(" ".join(words[start:end]), page.number, len(chunks)))
            if end == len(words):
                break
            start = end - overlap
    return chunks
