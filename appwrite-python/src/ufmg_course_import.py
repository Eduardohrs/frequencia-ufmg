"""Read current SIGA enrollments and create only missing local courses."""

import json
import re
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession

_ENROLLMENTS_URL = "https://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas"
_MAX_RESPONSE_BYTES = 262_144
_CODE = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,31}")
_CLOCK = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_WEEKDAYS = {
    "SEGUNDA": 1,
    "TERÇA": 2,
    "QUARTA": 3,
    "QUINTA": 4,
    "SEXTA": 5,
    "SÁBADO": 6,
}
_LESSON_COUNTS = {1, 2, 4}
_MAX_MEETINGS = 32


class InvalidUFMGEnrollmentResponse(Exception):
    """SIGA returned data outside the bounded enrollment contract."""


class UFMGEnrollmentUnavailable(Exception):
    """SIGA could not be reached safely."""

    def __init__(self, reason: str = "network", *, upstream_status: int | None = None) -> None:
        super().__init__("UFMG enrollment unavailable")
        self.reason = reason
        self.upstream_status = upstream_status


class _HTTPSOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        target = urlsplit(new_url)
        if target.scheme != "https" or target.hostname != "sistemas.ufmg.br":
            raise URLError("untrusted UFMG enrollment redirect")
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _open_response(request: Request, *, timeout: float) -> Any:
    return build_opener(_HTTPSOnlyRedirectHandler()).open(request, timeout=timeout)


class _SessionStore(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _CourseRepository(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...

    def save_course(self, payload: dict[str, object]) -> dict[str, Any]: ...


class _EnrollmentClient(Protocol):
    def fetch(self, token: str) -> list[dict[str, object]]: ...


class UFMGEnrollmentClient:
    """Fetch the minimum course metadata from the authenticated SIGA endpoint."""

    def __init__(
        self,
        *,
        open_response: Callable[..., Any] = _open_response,
        timeout_seconds: float = 10,
    ) -> None:
        if not 1 <= timeout_seconds <= 15:
            raise ValueError("invalid UFMG enrollment timeout")
        self._open = open_response
        self._timeout_seconds = timeout_seconds

    def fetch(self, token: str) -> list[dict[str, object]]:
        request = Request(
            _ENROLLMENTS_URL,
            headers={"Cookie": f"LtpaToken2={token}"},
        )
        try:
            with self._open(request, timeout=self._timeout_seconds) as response:
                if not _is_enrollment_response(response):
                    raise UFMGReauthenticationRequired(
                        "UFMG reauthentication required"
                    )
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except UFMGReauthenticationRequired:
            raise
        except HTTPError as error:
            raise UFMGEnrollmentUnavailable(
                "http_error", upstream_status=error.code
            ) from None
        except OSError as error:
            raise UFMGEnrollmentUnavailable(_transport_reason(error)) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise InvalidUFMGEnrollmentResponse("invalid UFMG enrollment response")
        try:
            payload = json.loads(raw.decode("iso-8859-1"))
            return _parse_courses(payload)
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            raise InvalidUFMGEnrollmentResponse(
                "invalid UFMG enrollment response"
            ) from None


class UFMGCourseImportService:
    """Idempotently add SIGA courses without modifying existing user records."""

    def __init__(
        self,
        sessions: _SessionStore,
        enrollments: _EnrollmentClient,
        courses: _CourseRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._courses = courses
        self._clock = clock or (lambda: datetime.now(UTC))

    def import_courses(self, user_id: str, *, now: int) -> dict[str, int]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        try:
            imported = self._enrollments.fetch(session.token)
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        unique = {str(course["code"]): course for course in imported}
        existing_codes = {
            str(course["code"]) for course in self._courses.list_courses()
        }
        timestamp = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        created = 0
        for code, course in sorted(unique.items()):
            if code in existing_codes:
                continue
            term = str(course["term"])
            self._courses.save_course(
                {
                    "id": f"ufmg-{term}-{code.lower()}",
                    "code": code,
                    "name": course["name"],
                    "workload": course["workload"],
                    "term": term,
                    "starts_on": None,
                    "ends_on": None,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
            created += 1
        return {
            "created": created,
            "existing": len(unique) - created,
            "total": len(unique),
        }


def _is_enrollment_response(response: Any) -> bool:
    parsed = urlsplit(response.geturl())
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "sistemas.ufmg.br"
        and parsed.path == "/siga-ws/seam/resource/rest/WsMatriculas"
    )


def _transport_reason(error: OSError) -> str:
    cause: object = error.reason if isinstance(error, URLError) else error
    if isinstance(cause, TimeoutError):
        return "timeout"
    if isinstance(cause, ssl.SSLError):
        return "tls"
    return "network"


def _parse_courses(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, Mapping) or "listaObj" not in payload:
        raise ValueError
    periods = payload["listaObj"]
    if not isinstance(periods, list) or not periods:
        raise ValueError
    period = periods[0]
    if not isinstance(period, Mapping):
        raise ValueError
    term = _term(period.get("semestreLetivo"))
    starts_on = _semester_date(period.get("dataInicialSemestre"), term)
    ends_on = _semester_date(period.get("dataFinalSemestre"), term)
    if starts_on > ends_on:
        raise ValueError
    enrollments = period.get("matriculas")
    if not isinstance(enrollments, list) or len(enrollments) > 100:
        raise ValueError
    courses: list[dict[str, object]] = []
    for enrollment in enrollments:
        try:
            classroom = enrollment["turma"]
            activity = classroom["atividadeAcademica"]
            raw_code = activity["codigo"]
            name_value = activity.get("nome") or activity.get("nomeReduzido")
            raw_workload = activity["cargaHoraria"]
            if (
                not isinstance(raw_code, str)
                or not isinstance(name_value, str)
                or isinstance(raw_workload, bool)
                or not isinstance(raw_workload, int | str)
                or isinstance(raw_workload, str) and not raw_workload.isdigit()
            ):
                raise ValueError
            code = raw_code.strip().upper()
            name = name_value.strip()
            workload = int(raw_workload)
            meetings = _meetings(classroom.get("horarios", []))
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError from None
        if (
            _CODE.fullmatch(code) is None
            or not name
            or len(name) > 160
            or workload <= 0
        ):
            raise ValueError
        courses.append(
            {
                "code": code,
                "name": name,
                "term": term,
                "workload": workload,
                "starts_on": starts_on,
                "ends_on": ends_on,
                "meetings": meetings,
            }
        )
    return courses


def _term(value: object) -> str:
    normalized = str(value).strip().replace("/", "-")
    if re.fullmatch(r"[0-9]{5}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4]}"
    if re.fullmatch(r"[0-9]{4}-[12]", normalized) is None:
        raise ValueError
    return normalized


def _semester_date(value: object, term: str) -> str:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=UTC)
    year, semester = (int(part) for part in term.split("-"))
    if parsed.year != year or (semester == 1) != (parsed.month <= 6):
        raise ValueError
    return parsed.isoformat().replace("+00:00", "Z")


def _meetings(value: object) -> list[dict[str, int]]:
    if not isinstance(value, list) or len(value) > _MAX_MEETINGS:
        raise ValueError
    result: list[dict[str, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError
        day = raw.get("diaDaSemana")
        start = raw.get("horaInicial")
        end = raw.get("horaFinal")
        if (
            not isinstance(day, str)
            or day not in _WEEKDAYS
            or not isinstance(start, str)
            or _CLOCK.fullmatch(start) is None
            or not isinstance(end, str)
            or _CLOCK.fullmatch(end) is None
        ):
            raise ValueError
        start_minutes = _clock_minutes(start)
        duration = _clock_minutes(end) - start_minutes
        if duration <= 0 or duration % 50 != 0:
            raise ValueError
        lesson_count = duration // 50
        if lesson_count not in _LESSON_COUNTS:
            raise ValueError
        meeting = (_WEEKDAYS[day], start_minutes, lesson_count)
        if meeting in seen or any(
            saved[0] == meeting[0]
            and start_minutes < saved[1] + saved[2] * 50
            and saved[1] < start_minutes + lesson_count * 50
            for saved in seen
        ):
            raise ValueError
        seen.add(meeting)
        result.append(
            {
                "weekday": meeting[0],
                "start_minutes": meeting[1],
                "lesson_count": meeting[2],
            }
        )
    return sorted(result, key=lambda item: (item["weekday"], item["start_minutes"]))


def _clock_minutes(value: str) -> int:
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 60 + minutes
