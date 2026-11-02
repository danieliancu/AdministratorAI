"""Splits Romanian legal text along its own structure: articles first, then paragraphs."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

MAX_CHUNK_CHARS = 1800
# With no article in the text, anything this short is a title or stub, not a document.
MIN_BODY_CHARS = 200

_ARTICLE = re.compile(
    r"(?:(?<=^)|(?<=\n)|(?<=\+\s)|(?<=[.;:]\s))"
    r"(Articolul\s+(?:UNIC|[0-9IVXLC]+(?:\^\d+)?)|Art\.\s*(?:[0-9]+(?:\^\d+)?))(?=[\s.:-])",
    re.MULTILINE,
)
_PARAGRAPH = re.compile(r"(?:(?<=^)|(?<=\s))\((\d+(?:\^\d+)?)\)(?=\s)")
_STRUCTURE = re.compile(
    r"(?:^|\n|\+\s)\s*((?:TITLUL|Titlul|CAPITOLUL|Capitolul|SECȚIUNEA|SECŢIUNEA|Secțiunea|Secţiunea)"
    r"\s+[0-9IVXLC]+[^\n]{0,80})"
)
_REFERENCE = re.compile(
    r"\b(Legea|Ordonanța de urgență a Guvernului|Ordonanţa de urgenţă a Guvernului|"
    r"Ordonanța Guvernului|Ordonanţa Guvernului|Hotărârea Guvernului|Hotărârii Guvernului)"
    r"\s+nr\.\s*(\d+)\s*/\s*(\d{4})"
)


@dataclass(frozen=True)
class ParsedChunk:
    text: str
    paragraph_label: str
    checksum: str


@dataclass
class ParsedProvision:
    label: str
    structure_path: str
    text: str
    chunks: list = field(default_factory=list)


@dataclass
class ParsedDocument:
    provisions: list
    is_complete: bool


def normalize_whitespace(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def fold_for_search(text):
    """Old cedilla forms and missing diacritics must not hide a match."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def text_checksum(text):
    return hashlib.sha256(fold_for_search(text).encode()).hexdigest()


def _chunks_for(text):
    """Keeps whole paragraphs together. Only an oversized paragraph is cut further."""
    matches = list(_PARAGRAPH.finditer(text))
    if not matches:
        segments = [("", text)]
    else:
        segments = []
        if text[: matches[0].start()].strip():
            segments.append(("", text[: matches[0].start()].strip()))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segments.append((f"alin. ({match.group(1)})", text[match.start() : end].strip()))

    chunks, label, buffer = [], "", ""

    def flush():
        nonlocal buffer, label
        if buffer.strip():
            chunks.append(
                ParsedChunk(
                    text=buffer.strip(), paragraph_label=label, checksum=text_checksum(buffer)
                )
            )
        buffer, label = "", ""

    for segment_label, segment in segments:
        if len(buffer) + len(segment) > MAX_CHUNK_CHARS:
            flush()
        if not buffer:
            label = segment_label
        elif segment_label:
            label = ""
        buffer = f"{buffer}\n{segment}" if buffer else segment
        while len(buffer) > MAX_CHUNK_CHARS:
            cut = buffer.rfind(" ", 0, MAX_CHUNK_CHARS)
            cut = cut if cut > 0 else MAX_CHUNK_CHARS
            head, buffer = buffer[:cut], buffer[cut:].strip()
            chunks.append(
                ParsedChunk(text=head.strip(), paragraph_label=label, checksum=text_checksum(head))
            )
    flush()
    return chunks


def _structure_before(text, position):
    found = [m.group(1).strip() for m in _STRUCTURE.finditer(text, 0, position)]
    return " / ".join(found[-2:])[:300]


def parse_legal_text(raw_text):
    text = normalize_whitespace(raw_text)
    matches = list(_ARTICLE.finditer(text))
    provisions = []
    if matches:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            provisions.append(ParsedProvision("Preambul", "", preamble))
        seen = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            label = re.sub(r"\s+", " ", match.group(1)).replace("Art. ", "Articolul ")
            # The same number can repeat when an act quotes an amended text.
            seen[label] = seen.get(label, 0) + 1
            unique_label = label if seen[label] == 1 else f"{label} ({seen[label]})"
            provisions.append(
                ParsedProvision(
                    unique_label,
                    _structure_before(text, match.start()),
                    text[match.start() : end].strip(),
                )
            )
        is_complete = True
    else:
        is_complete = len(text) >= MIN_BODY_CHARS
        if is_complete:
            provisions.append(ParsedProvision("Text integral", "", text))
    for provision in provisions:
        provision.chunks = _chunks_for(provision.text)
    return ParsedDocument(provisions=provisions, is_complete=is_complete)


def find_references(text):
    """Suggestions from text matching. They never establish that one act amends another."""
    found = []
    for name, number, year in _REFERENCE.findall(text):
        reference = f"{name} nr. {number}/{year}"
        if reference not in found:
            found.append(reference)
    return found
