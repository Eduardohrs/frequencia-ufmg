"""Read Moodle activities for an owned course; attachment bytes stay at Moodle."""

from mimetypes import guess_type
from typing import Any, Protocol

from course_repository import CourseRepository
from moodle_material_catalog_repository import MoodleMaterialCatalogRepository
from moodle_mobile_capability import MoodleMobileCapabilityService
from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
    _private_file_url,
)
from moodle_token_store import (
    AppwriteMoodleTokenStore,
    MoodleAuthorizationRequired,
    MoodleTokenStoreUnavailable,
)
from sync_timing import Telemetry, _emit, timed_stage
from ufmg_session_store import (
    UFMGReauthenticationRequired,
    UFMGSession,
    UFMGSessionStoreUnavailable,
)


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...


class CourseMoodleNotLinked(ValueError):
    """Synchronize Moodle once before opening the course activity catalogue."""


class CourseActivityService:
    def __init__(
        self,
        courses: CourseRepository,
        catalog: MoodleMaterialCatalogRepository,
        sessions: _Sessions,
        client: MoodleStructuredDatesClient,
        tokens: AppwriteMoodleTokenStore,
        capabilities: MoodleMobileCapabilityService,
        *,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._courses, self._catalog, self._sessions = courses, catalog, sessions
        self._client, self._tokens, self._capabilities = client, tokens, capabilities
        self._telemetry = telemetry

    def _source(
        self, user_id: str, course_id: str, now: int
    ) -> tuple[dict[str, Any], UFMGSession, int]:
        course = self._courses.get_course(course_id)
        catalogs = self._catalog.list_catalog([course])
        if (
            not catalogs
            or catalogs[0]["status"] not in {"found", "empty"}
            or catalogs[0]["moodle_course_id"] is None
        ):
            raise CourseMoodleNotLinked("course Moodle link unavailable")
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        return course, session, int(str(catalogs[0]["moodle_course_id"]))

    def list_activities(self, user_id: str, course_id: str, *, now: int) -> dict[str, object]:
        course, session, moodle_id = self._source(user_id, course_id, now)
        entries = timed_stage(
            "course_activity_index",
            lambda: self._client.list_activities(
                session.token, term=course["term"], course_id=moodle_id, course_code=course["code"]
            ),
            telemetry=self._telemetry,
            fields={
                "course_id": course_id,
                "course_code": course["code"],
                "moodle_course_id": moodle_id,
            },
        )
        _emit(
            self._telemetry,
            "course_activities_loaded",
            {"course_id": course_id, "activity_count": len(entries), "term": course["term"]},
        )
        return {
            "activities": entries,
            "course_id": course_id,
            "term": course["term"],
            "moodle_course_id": str(moodle_id),
        }

    def detail(
        self, user_id: str, course_id: str, source_id: str, *, now: int
    ) -> dict[str, object]:
        course, session, moodle_id = self._source(user_id, course_id, now)
        entries = timed_stage(
            "course_activity_membership",
            lambda: self._client.list_activities(
                session.token, term=course["term"], course_id=moodle_id, course_code=course["code"]
            ),
            telemetry=self._telemetry,
            fields={"course_id": course_id, "course_code": course["code"], "source_id": source_id},
        )
        entry = next((item for item in entries if item["source_id"] == source_id), None)
        if entry is None:
            raise InvalidMoodleResponse("course_activity_not_found")
        detail = timed_stage(
            "course_activity_detail",
            lambda: self._client.fetch_activity(
                session.token,
                term=course["term"],
                source_id=int(source_id),
                kind=str(entry["kind"]),
            ),
            telemetry=self._telemetry,
            fields={"course_id": course_id, "source_id": source_id},
        )
        attachments = detail["attachments"]
        if not isinstance(attachments, list):
            raise InvalidMoodleResponse("activity_attachment_shape")
        files: list[dict[str, object]] = []
        if attachments:
            try:
                tokens = self._tokens.load(user_id, now=now)
                if tokens is None or tokens.term != course["term"]:
                    self._capabilities.probe(user_id, now=now)
                    tokens = self._tokens.load(user_id, now=now)
                if tokens is None or tokens.term != course["term"]:
                    raise MoodleAuthorizationRequired("Moodle file authorization required")
                for attachment in attachments:
                    files.append(
                        {
                            "name": attachment["name"],
                            "url": _private_file_url(
                                attachment["url"],
                                "/" + str(course["term"]).replace("-", ""),
                                tokens.private_token,
                            ),
                            "size": 0,
                            "mime_type": guess_type(attachment["name"])[0]
                            or "application/octet-stream",
                        }
                    )
            except (
                MoodleAuthorizationRequired,
                MoodleTokenStoreUnavailable,
                InvalidMoodleResponse,
                MoodleUnavailable,
                UFMGReauthenticationRequired,
                UFMGSessionStoreUnavailable,
                ValueError,
            ) as error:
                _emit(
                    self._telemetry,
                    "course_activity_download_unavailable",
                    {
                        "course_id": course_id,
                        "source_id": source_id,
                        "stage": "attachment_authorization",
                        "reason": type(error).__name__,
                        "attachment_count": len(attachments),
                    },
                )
        _emit(
            self._telemetry,
            "course_activity_detail_loaded",
            {
                "course_id": course_id,
                "source_id": source_id,
                "submission_state": str(detail["submission_state"]),
                "attachment_count": len(attachments),
                "download_count": len(files),
            },
        )
        return {
            **entry,
            **detail,
            "term": course["term"],
            "moodle_course_id": entry.get("moodle_course_id", str(moodle_id)),
            "files": files,
        }
