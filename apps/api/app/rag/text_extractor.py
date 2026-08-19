"""Document text extraction — untrusted file bytes to plain text.

Memory processing only; never builds filesystem paths from filenames; never
executes uploads. No DB/repo/auth/embed calls.
"""

import io
from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


class UnsupportedFileError(Exception):
    pass


class EmptyExtractedTextError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedText:
    text: str
    extension: str


class DocumentTextExtractor:
    def extract(self, filename: str, content: bytes) -> ExtractedText:
        extension = self._safe_extension(filename)
        if extension not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFileError(f"unsupported file type: {extension}")

        if extension in (".txt", ".md"):
            text = content.decode("utf-8", errors="replace")
        elif extension == ".pdf":
            text = self._extract_pdf(content)
        elif extension == ".docx":
            text = self._extract_docx(content)
        else:  # pragma: no cover
            raise UnsupportedFileError("unsupported file type")

        if not text.strip():
            raise EmptyExtractedTextError("extracted text is empty")
        return ExtractedText(text=text, extension=extension)

    @staticmethod
    def _safe_extension(filename: str) -> str:
        # Take only the final path component; never use raw filename as a path.
        name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        dot = name.rfind(".")
        if dot < 0:
            return ""
        return name[dot:].lower()

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001 - malformed PDF
            raise EmptyExtractedTextError("malformed pdf") from exc

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        import docx

        try:
            document = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in document.paragraphs)
        except Exception as exc:  # noqa: BLE001 - malformed docx
            raise EmptyExtractedTextError("malformed docx") from exc
