from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _text_to_markdown(text: str) -> str:
    lines = [_collapse_whitespace(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    markdown_lines: list[str] = []
    for idx, line in enumerate(lines):
        # Keep first line as title-like heading for resume parsers.
        if idx == 0:
            markdown_lines.append(f"# {line.lstrip('# ').strip()}")
            markdown_lines.append("")
            continue
        markdown_lines.append(line)
    return "\n".join(markdown_lines).strip() + "\n"


def _extract_with_pypdf(pdf_path: Path) -> str:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _extract_with_pdftotext(pdf_path: Path) -> str:
    cmd = ["pdftotext", str(pdf_path), "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def pdf_to_markdown(pdf_path: str | Path, output_path: str | Path | None = None) -> Path:
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF not found: {src}")
    if src.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {src}")

    text = ""
    try:
        text = _extract_with_pypdf(src)
        logger.info("Extracted PDF text using pypdf: %s", src)
    except Exception:  # noqa: BLE001
        logger.warning("pypdf extraction failed for %s. Trying pdftotext fallback.", src)
        try:
            text = _extract_with_pdftotext(src)
            logger.info("Extracted PDF text using pdftotext: %s", src)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Could not extract text from PDF. Install `pypdf` or ensure `pdftotext` is available."
            ) from exc

    markdown = _text_to_markdown(text)
    if not markdown.strip():
        raise RuntimeError(f"No extractable text found in PDF: {src}")

    target = Path(output_path) if output_path else src.with_suffix(".md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target
