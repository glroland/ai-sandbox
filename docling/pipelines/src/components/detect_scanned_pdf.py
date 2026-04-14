from kfp import dsl
from kfp.dsl import Input, Artifact

_BASE_IMAGE = "python:3.11-slim"
_PACKAGES = ["pypdf>=4.0.0"]

@dsl.component(base_image=_BASE_IMAGE, packages_to_install=_PACKAGES)
def detect_scanned_pdf_op(
    input_file: Input[Artifact],

    # Minimum average characters per page to consider a PDF digitally-born (not scanned).
    # Pages with fewer characters than this threshold are treated as image-only pages.
    chars_per_page_threshold: int = 50,
) -> bool:
    """
    Detect whether a PDF is a scanned document that requires OCR.

    A PDF is classified as scanned when the average number of extractable
    characters per page falls below *chars_per_page_threshold*, which
    indicates that the pages contain images rather than embedded text.

    Parameters
    ----------
    input_file              : PDF artifact to inspect
    chars_per_page_threshold: avg chars/page below which the doc is
                              considered scanned (default 50)

    Returns
    -------
    bool
        True  - scanned document (OCR required)
        False - digitally-born PDF (OCR not required)
    """
    from pypdf import PdfReader

    reader = PdfReader(input_file.path)
    num_pages = len(reader.pages)

    if num_pages == 0:
        print("[WARN] PDF has no pages; treating as scanned.")
        return True

    total_chars = 0
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        page_chars = len(text.strip())
        total_chars += page_chars
        print(f"[INFO] Page {i + 1}/{num_pages}: {page_chars} chars extracted")

    avg_chars = total_chars / num_pages
    is_scanned = avg_chars < chars_per_page_threshold

    print(
        f"[INFO] Total pages: {num_pages} | "
        f"Total chars: {total_chars} | "
        f"Avg chars/page: {avg_chars:.1f} | "
        f"Threshold: {chars_per_page_threshold} | "
        f"Scanned: {is_scanned}"
    )
    return is_scanned
