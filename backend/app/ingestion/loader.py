from __future__ import annotations

from typing import List, TypedDict
from logging import getLogger
from pathlib import Path


logger = getLogger("supertutor.loader")


class LoadedPage(TypedDict):
    page: int
    text: str


class LoadedResult(TypedDict):
    file_id: str
    mime: str
    status: str
    needs_processing: bool
    needs_ocr: bool
    pages: int
    pages_text: List[str]
    pages_struct: List[LoadedPage]


def _is_pdf(path: str, mime: str) -> bool:
    m = (mime or "").strip().lower()
    return m == "application/pdf" or path.strip().lower().endswith(".pdf")


def _is_txt(path: str, mime: str) -> bool:
    m = (mime or "").strip().lower()
    return m == "text/plain" or path.strip().lower().endswith(".txt")


def load_from_path(file_id: str, path: str, mime: str) -> LoadedResult:
    """Load a local file path and return per-page text and structure.

    - PDFs are processed using langchain_community.document_loaders.UnstructuredPDFLoader
      with mode="elements" to obtain page-aware elements.
    - TXTs are read as UTF-8 into a single logical page.

    This function is pure/side-effect free: no DB writes. It only reads from the local
    filesystem path provided by the caller and returns an in-memory structure.
    """
    logger.debug("loader.start file_id=%s path=%s mime=%s", file_id, path, mime)
    p = str(Path(path))

    try:
        if _is_pdf(p, mime):
            try:
                from langchain_community.document_loaders import UnstructuredPDFLoader
            except Exception as e:
                raise RuntimeError(
                    f"Failed to import UnstructuredPDFLoader for {p} (mime={mime}): {e}"
                ) from e

            try:
                loader = UnstructuredPDFLoader(p, mode="elements")
                elements = loader.load()
            except Exception as e:
                raise RuntimeError(f"Failed to load PDF at {p} (mime={mime}): {e}") from e

            pages_by_num: dict[int, List[str]] = {}
            max_page = 0
            for el in elements:
                meta = getattr(el, "metadata", {}) or {}
                pn = meta.get("page_number") if isinstance(meta, dict) else None
                if pn is None and isinstance(meta, dict):
                    pn = meta.get("page")
                try:
                    page_num = int(pn) if pn is not None else 1
                except Exception:
                    page_num = 1
                if page_num < 1:
                    page_num = 1
                max_page = max(max_page, page_num)
                text_piece = getattr(el, "page_content", "") or ""
                pages_by_num.setdefault(page_num, []).append(text_piece)

            if max_page == 0:
                max_page = 1

            pages_text: List[str] = []
            for i in range(1, max_page + 1):
                parts = pages_by_num.get(i, [])
                joined = "\n".join(parts).strip("\n")
                pages_text.append(joined)

            all_text = "\n\n".join(pages_text)
            all_blank = all((len(t.strip()) == 0) for t in pages_text)
            needs_ocr = True if len(all_text.strip()) < 50 or all_blank else False

        elif _is_txt(p, mime):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                raise RuntimeError(f"Failed to load TXT at {p} (mime={mime}): {e}") from e

            pages_text = [text]
            needs_ocr = False

        else:
            raise ValueError(f"Unsupported mime/extension for {p} (mime={mime})")

    except Exception:
        logger.exception("loader.error file_id=%s path=%s mime=%s", file_id, p, mime)
        raise

    pages_struct: List[LoadedPage] = [
        {"page": i + 1, "text": pages_text[i]} for i in range(len(pages_text))
    ]

    result: LoadedResult = {
        "file_id": file_id,
        "mime": mime,
        "status": "pending",
        "needs_processing": True,
        "needs_ocr": needs_ocr,
        "pages": len(pages_text),
        "pages_text": pages_text,
        "pages_struct": pages_struct,
    }

    lens_first5 = [len(t) for t in pages_text[:5]]
    total_len = sum(len(t) for t in pages_text)
    logger.debug(
        "loader.done file_id=%s pages=%d needs_ocr=%s lengths_first5=%s total_len=%d",
        file_id,
        result["pages"],
        result["needs_ocr"],
        lens_first5,
        total_len,
    )

    return result
