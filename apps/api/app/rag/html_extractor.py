"""HTML text extraction — untrusted HTML to clean text.

No DB/repo/auth/embed calls. Output feeds the existing TextNormalizer.
"""

from bs4 import BeautifulSoup

STRIP_TAGS = {"script", "style", "noscript", "template"}


class EmptyHTMLTextError(Exception):
    pass


class HTMLTextExtractor:
    def extract(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in STRIP_TAGS:
            for element in soup.find_all(tag):
                element.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        if not cleaned.strip():
            raise EmptyHTMLTextError("no extractable text")
        return cleaned
