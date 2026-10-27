"""Read text from pages that are only images (scanned PDFs, slides exported as pictures).

Text extraction finds nothing on such pages, so on upload they are sent to Claude, which
reads the images and transcribes them. PDF pages go as a small PDF of just those pages;
slide pictures go as images. Batches run in parallel. A batch that fails leaves its pages
empty (the rest of the file is still used) and is reported in the result.
"""

import base64
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from core import config, llm
from core.documents import Page, slide_images

log = logging.getLogger(__name__)

# A page with fewer words than this is treated as an image page.
MIN_WORDS = 25
PDF_PAGES_PER_CALL = 6
SLIDES_PER_CALL = 6
PARALLEL_CALLS = 4
TIMEOUT_S = 180  # longer than chat: a batch transcribes several pages
MAX_TOKENS = 16000
# Claude reads these image types; the rest (EMF/WMF diagrams, TIFF...) are converted or skipped.
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MIN_IMAGE_BYTES = 8_000  # skip icons, bullets and logos
MAX_IMAGE_SIDE = 1568  # larger images are downscaled first (Claude's own limit for detail)
MAX_IMAGES_PER_SLIDE = 4

PROMPT = """These are {what} from a student's course notes. Transcribe the readable text on
each one exactly: headings, bullet points, definitions, formulas (in plain text) and table
rows. For a diagram or chart, add one short line "[Figure: ...]" saying what it shows,
using only what is visible. Do not add explanations or facts that are not on the page.
If a page has no readable text, return an empty string for it.

Return JSON: {{"pages": [{{"number": <{label} number>, "text": "..."}}]}}"""

SCHEMA = {
    "type": "object",
    "properties": {"pages": {"type": "array", "items": {
        "type": "object",
        "properties": {"number": {"type": "integer"}, "text": {"type": "string"}},
        "required": ["number", "text"], "additionalProperties": False,
    }}},
    "required": ["pages"], "additionalProperties": False,
}


@dataclass
class OcrResult:
    pages_read: int = 0  # image pages that got text
    pages_failed: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def enabled() -> bool:
    return config.OCR_ENABLED and bool(config.ANTHROPIC_API_KEY)


def needs_ocr(page: Page) -> bool:
    return page.number is not None and len(page.text.split()) < MIN_WORDS


def fill_image_pages(filename: str, data: bytes, pages: list[Page]) -> OcrResult:
    """Transcribe pages with (almost) no text, in place. Only PDF and PPTX/PPT pages."""
    result = OcrResult()
    targets = [p for p in pages if needs_ocr(p)]
    ext = Path(filename).suffix.lower().lstrip(".")
    if not targets or not enabled() or ext not in ("pdf", "pptx", "ppt"):
        return result
    if ext == "pdf":
        batches = [targets[i:i + PDF_PAGES_PER_CALL] for i in range(0, len(targets), PDF_PAGES_PER_CALL)]
        jobs = [(batch, _pdf_content(data, batch)) for batch in batches]
    else:
        pictures = slide_images(data)
        with_pictures = [p for p in targets if _usable(pictures.get(p.number, []))]
        batches = [with_pictures[i:i + SLIDES_PER_CALL] for i in range(0, len(with_pictures), SLIDES_PER_CALL)]
        jobs = [(batch, _slide_content(batch, pictures)) for batch in batches]
    if not jobs:
        return result

    what = "PDF pages" if ext == "pdf" else "slides"
    with ThreadPoolExecutor(PARALLEL_CALLS) as pool:
        outcomes = list(pool.map(lambda job: _transcribe(job[1], what), jobs))
    for (batch, _), outcome in zip(jobs, outcomes):
        if outcome is None:
            result.pages_failed += [p.number for p in batch]
            continue
        texts, usage = outcome
        result.input_tokens += usage[0]
        result.output_tokens += usage[1]
        for page in batch:
            text = texts.get(page.number, "").strip()
            if text:
                page.text = f"{page.text}\n{text}".strip()
                result.pages_read += 1
    log.info("OCR %s: %d of %d image pages read (%d failed), %d in / %d out tokens",
             filename, result.pages_read, len(targets), len(result.pages_failed),
             result.input_tokens, result.output_tokens)
    return result


def _pdf_content(data: bytes, batch: list[Page]) -> list[dict]:
    """A PDF of just these pages, plus which original page each one is."""
    from pypdf import PdfReader, PdfWriter

    reader, writer = PdfReader(io.BytesIO(data)), PdfWriter()
    for page in batch:
        writer.add_page(reader.pages[page.number - 1])
    buffer = io.BytesIO()
    writer.write(buffer)
    numbers = ", ".join(str(p.number) for p in batch)
    return [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": base64.standard_b64encode(buffer.getvalue()).decode()}},
        {"type": "text", "text": f"The PDF's pages are, in order, original pages {numbers}. "
                                 "Use the original page numbers."},
    ]


def _usable(images: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    return [(blob, kind) for blob, kind in images if len(blob) >= MIN_IMAGE_BYTES][:MAX_IMAGES_PER_SLIDE]


def _slide_content(batch: list[Page], pictures: dict) -> list[dict]:
    content = []
    for page in batch:
        content.append({"type": "text", "text": f"Slide {page.number}:"})
        for blob, kind in _usable(pictures.get(page.number, [])):
            image = _as_supported_image(blob, kind)
            if image:
                content.append({"type": "image", "source": {"type": "base64", "media_type": image[1],
                                                            "data": base64.standard_b64encode(image[0]).decode()}})
    return content


def _as_supported_image(blob: bytes, kind: str) -> tuple[bytes, str] | None:
    """PNG/JPEG under Claude's size limits; None if the picture can't be decoded."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(blob))
        image.load()
    except Exception:
        return None  # e.g. EMF/WMF vector diagrams
    if kind in IMAGE_TYPES and max(image.size) <= MAX_IMAGE_SIDE and len(blob) < 3_500_000:
        return blob, kind
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def _transcribe(content: list[dict], what: str) -> tuple[dict[int, str], tuple[int, int]] | None:
    """One Claude call; {page number: text} and (input, output) tokens, or None on failure."""
    import anthropic

    label = "page" if what == "PDF pages" else "slide"
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=TIMEOUT_S, max_retries=1)
    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "between_tools"},  # plain transcription: no reasoning pass needed
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content + [
                {"type": "text", "text": PROMPT.format(what=what, label=label)}]}],
        )
        if response.stop_reason != "end_turn":
            raise llm.LLMError(f"stopped early ({response.stop_reason})")
        text = "".join(b.text for b in response.content if b.type == "text")
        pages = {int(p["number"]): p["text"] for p in json.loads(text)["pages"]}
        return pages, (response.usage.input_tokens, response.usage.output_tokens)
    except Exception as exc:
        log.warning("OCR batch failed: %s", llm._describe(exc))
        return None
