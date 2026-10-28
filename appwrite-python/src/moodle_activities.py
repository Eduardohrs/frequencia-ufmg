"""Read visible Moodle assignment facts, never student file contents or comments."""

import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlsplit


class InvalidActivityPage(ValueError):
    """An assignment page did not satisfy the bounded reader contract."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_VOID = {
    "br",
    "hr",
    "img",
    "input",
    "meta",
    "link",
    "source",
    "wbr",
    "area",
    "base",
    "embed",
    "param",
    "track",
    "col",
}


def _normalized(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if not unicodedata.combining(c)
    )


class _ActivityParser(HTMLParser):
    def __init__(self, term: str) -> None:
        super().__init__()
        self.term = term
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.description: list[str] = []
        self.dates: list[str] = []
        self.due_label = False
        self.attachments: list[dict[str, str]] = []
        self.cells: list[str] = []
        self.cell: list[str] | None = None
        self.submission = ""
        self.main = False
        self.activity = False

    def _inside(self, key: str, value: str) -> bool:
        return any(attributes.get(key) == value for _, attributes in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.main |= attributes.get("id") == "region-main"
        self.activity |= (
            attributes.get("id") == "intro"
            or attributes.get("data-region") == "activity-dates"
            or "submissionstatustable" in (attributes.get("class", "") or "").split()
        )
        if len(self.stack) > 100:
            raise InvalidActivityPage("activity_html_depth")
        if tag not in _VOID:
            self.stack.append((tag, attributes))
        if self._inside("id", "intro") and tag == "a":
            url = attributes.get("href", "") or ""
            parsed = urlsplit(url)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "virtual.ufmg.br"
                and parsed.netloc == "virtual.ufmg.br"
                and parsed.path.startswith(f"/{self.term.replace('-', '')}/pluginfile.php/")
                and "/introattachment/" in parsed.path
                and not parsed.fragment
            ):
                self.attachments.append({"url": url, "name": parsed.path.rsplit("/", 1)[-1][:255]})
        if any(
            "submissionstatustable" in (a.get("class", "") or "").split() for _, a in self.stack
        ) and tag in {"th", "td"}:
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self.cell is not None:
            self.cells.append(" ".join(self.cell).strip())
            self.cell = None
        if tag == "tr":
            if len(self.cells) >= 2 and _normalized(self.cells[0]) in {
                "status de envio",
                "submission status",
            }:
                self.submission = self.cells[1][:500]
            self.cells = []
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or any(tag in {"script", "style"} for tag, _ in self.stack):
            return
        if self._inside("id", "intro"):
            self.description.append(text)
        if self._inside("data-region", "activity-dates"):
            self.dates.append(text)
            self.due_label |= _normalized(text).startswith(("vencimento:", "due date:"))
        if self.cell is not None:
            self.cell.append(text)


def parse_activity_page(payload: bytes, *, term: str, kind: str) -> dict[str, object]:
    if re.fullmatch(r"20[2-9][0-9]-[12]", term) is None or kind not in {"assign", "quiz"}:
        raise InvalidActivityPage("activity_request")
    if len(payload) > 1_048_576:
        raise InvalidActivityPage("activity_page_size")
    parser = _ActivityParser(term)
    try:
        parser.feed(payload.decode("utf-8"))
    except UnicodeDecodeError:
        raise InvalidActivityPage("activity_page_encoding") from None
    if not parser.main or not parser.activity:
        raise InvalidActivityPage("activity_page_shape")
    status = _normalized(parser.submission)
    state = "unknown"
    if status.startswith(("enviado para avalia", "submitted for grading")):
        state = "submitted"
    elif status.startswith(("nenhum envio", "no submission")):
        state = "not_submitted"
    elif "rascunho" in status or "draft" in status:
        state = "draft"
    if len(parser.attachments) > 100:
        raise InvalidActivityPage("activity_attachment_limit")
    return {
        "description": " ".join(parser.description)[:20000],
        "dates_text": " ".join(parser.dates)[:2000],
        "has_due_date": parser.due_label,
        "submission_state": state,
        "submission_text": parser.submission,
        "attachments": parser.attachments,
    }
