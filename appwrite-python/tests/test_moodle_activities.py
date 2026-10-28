import pytest

from moodle_activities import InvalidActivityPage, parse_activity_page
from moodle_structured_dates import InvalidMoodleResponse, MoodleStructuredDatesClient
from ufmg_session_store import UFMGReauthenticationRequired


def test_assignment_page_keeps_description_teacher_files_and_submission_separate() -> None:
    html = b"""<main id="region-main">
<div id="intro">
<p>Prepare a prototype.</p>
<a href="https://virtual.ufmg.br/20262/pluginfile.php/20/mod_assign/introattachment/0/a.pdf">a.pdf</a>
</div>
<div data-region="activity-dates">
<strong>Vencimento:</strong> domingo, 1 nov. 2026, 23:59</div>
<div class="submissionstatustable">
<table>
<tr>
<th>Status de envio</th>
<td>Enviado para avaliacao</td>
</tr>
<tr>
<th>Envios de arquivo</th>
<td>PRIVATE_STUDENT_FILE</td>
</tr>
</table>
</div>
</main>"""
    result = parse_activity_page(html, term="2026-2", kind="assign")
    assert result["description"] == "Prepare a prototype. a.pdf"
    assert len(result["attachments"]) == 1
    assert result["submission_state"] == "submitted"
    assert result["has_due_date"] is True
    assert "PRIVATE_STUDENT_FILE" not in str(result)


def test_undated_assignment_is_visible_without_inventing_a_deadline_or_submission() -> None:
    result = parse_activity_page(
        b"""<main id="region-main">
<div id="intro">Read this</div>
<div class="submissionstatustable">
<table>
<tr>
<th>Submission status</th>
<td>No submissions have been made yet</td>
</tr>
</table>
</div>
</main>""",
        term="2026-2",
        kind="assign",
    )
    assert result["has_due_date"] is False
    assert result["submission_state"] == "not_submitted"
    assert result["dates_text"] == ""


def test_structured_activity_index_and_detail_use_observed_endpoints() -> None:
    import json

    from moodle_structured_dates import MoodleStructuredDatesClient

    class Client(MoodleStructuredDatesClient):
        def _connect(self, token, term):
            return "/20262", "/20262/lib/ajax/service.php", "private-session"

        def _ajax(self, root, path, key, calls):
            assert calls[0]["methodname"] == "core_courseformat_get_state"
            return json.dumps(
                [
                    {
                        "error": False,
                        "data": json.dumps(
                            {
                                "cm": [
                                    {
                                        "id": "20",
                                        "name": "Undated task",
                                        "module": "assign",
                                        "uservisible": True,
                                        "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=20",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            ).encode()

        def _open(self, request):
            return (
                b"""<main id="region-main">
<div id="intro">Task</div>
</main>""",
                request.full_url,
                "text/html",
            )

    client = Client()
    entries = client.list_activities("private", term="2026-2", course_id=1)
    assert entries[0]["kind"] == "assign"
    detail = client.fetch_activity("private", term="2026-2", source_id=20, kind="assign")
    assert detail["description"] == "Task"


@pytest.mark.parametrize(
    "payload,term,kind,reason",
    [
        (b"", "bad", "assign", "activity_request"),
        (b"", "2026-2", "forum", "activity_request"),
        (b"x" * 1_048_577, "2026-2", "assign", "activity_page_size"),
        (b"\xff", "2026-2", "assign", "activity_page_encoding"),
        (b"<main>Login</main>", "2026-2", "assign", "activity_page_shape"),
        (b'<main id="region-main">' + b"<div>" * 103, "2026-2", "assign", "activity_html_depth"),
    ],
    ids=lambda value: "bytes-" + str(len(value)) if isinstance(value, bytes) else str(value),
)
def test_activity_reader_rejects_invalid_or_unbounded_documents(payload, term, kind, reason):
    with pytest.raises(InvalidActivityPage) as rejected:
        parse_activity_page(payload, term=term, kind=kind)
    assert rejected.value.reason == reason


def test_activity_reader_handles_unknown_draft_and_invalid_teacher_links_without_student_data():
    html = b"""<main id="region-main">
<div id="intro">
<p>A<br/>B</span>C<a>link</a>
<a href="https://other.example/file.pdf">unsafe</a>
<script>SKIP_SCRIPT</script>
<style>SKIP_STYLE</style>
</p>
</div>
<div data-region="activity-dates">Aberto: 1/11</div>
<div class="submissionstatustable">
<table>
<tr>
<th>Submission status</th>
<td>Draft (not submitted)</td>
</tr>
</table>
</div>
</main>"""
    result = parse_activity_page(html, term="2026-2", kind="assign")
    assert result["submission_state"] == "draft"
    assert "SKIP_SCRIPT" not in result["description"]
    assert result["attachments"] == []
    assert not result["has_due_date"]
    unknown = parse_activity_page(
        b"""<main id="region-main">
<div id="intro">Quiz</div>
</main>""",
        term="2026-2",
        kind="quiz",
    )
    assert unknown["submission_state"] == "unknown"
    base = "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_assign/introattachment/0"
    html = (
        b'<main id="region-main"><div id="intro">'
        + b"".join(f'<a href="{base}/{i}.pdf">file</a>'.encode() for i in range(101))
        + b"</div></main>"
    )
    with pytest.raises(InvalidActivityPage, match="attachment_limit"):
        parse_activity_page(html, term="2026-2", kind="assign")


def test_activity_client_validates_permissions_redirects_and_membership_sources():
    class Client(MoodleStructuredDatesClient):
        status = "found"
        candidates = []
        response = (
            b"""<main id="region-main">
</main>""",
            "https://virtual.ufmg.br/20262/mod/assign/view.php?id=20",
            "text/html",
        )

        def _connect(self, *args):
            return "/20262", "ajax", "private"

        def _open(self, request):
            return self.response

        def discover(self, *args, **kwargs):
            assert kwargs["activities"] is True
            return [{"status": self.status, "candidates": self.candidates}]

    client = Client()
    for identifier in [True, 0, -1, 2_147_483_648]:
        with pytest.raises(InvalidMoodleResponse):
            client.list_activities("token", term="2026-2", course_id=identifier)
        with pytest.raises(InvalidMoodleResponse):
            client.fetch_activity("token", term="2026-2", source_id=identifier, kind="assign")
    with pytest.raises(InvalidMoodleResponse):
        client.fetch_activity("token", term="2026-2", source_id=20, kind="forum")
    assert client.list_activities("token", term="2026-2", course_id=1, course_code="ELE631") == []
    client.status = "ambiguous"
    with pytest.raises(InvalidMoodleResponse):
        client.list_activities("token", term="2026-2", course_id=1, course_code="ELE631")
    client.status = "found"
    client.candidates = None
    with pytest.raises(InvalidMoodleResponse):
        client.list_activities("token", term="2026-2", course_id=1, course_code="ELE631")
    for url in [
        "https://sistemas.ufmg.br/idp/login.jsp",
        "https://virtual.ufmg.br/20262/login/index.php",
    ]:
        client.response = (b"", url, "text/html")
        with pytest.raises(UFMGReauthenticationRequired):
            client.fetch_activity("token", term="2026-2", source_id=20, kind="assign")
    client.response = (b"", "https://other.example/", "text/html")
    with pytest.raises(InvalidMoodleResponse):
        client.fetch_activity("token", term="2026-2", source_id=20, kind="assign")
    client.response = (
        b"login",
        "https://virtual.ufmg.br/20262/mod/assign/view.php?id=20",
        "text/html",
    )
    with pytest.raises(InvalidMoodleResponse) as rejected:
        client.fetch_activity("token", term="2026-2", source_id=20, kind="assign")
    assert rejected.value.reason == "activity_page_shape"


@pytest.mark.parametrize(
    "marker", ["quizinfo", "quizattemptsummary", "quizattempt", "quizstartbuttondiv"]
)
def test_undated_quiz_without_intro_accepts_real_quiz_blocks(marker):
    page = f'<section id="region-main"><div class="{marker}">Quiz</div></section>'.encode()
    detail = parse_activity_page(page, term="2026-2", kind="quiz")
    assert detail == {
        "description": "",
        "dates_text": "",
        "has_due_date": False,
        "submission_state": "unknown",
        "submission_text": "",
        "attachments": [],
    }


@pytest.mark.parametrize(
    "kind,html",
    [
        ("assign", b'<section id="region-main"><div class="quizinfo"></div></section>'),
        ("quiz", b'<div class="quizinfo"></div><section id="region-main"></section>'),
        ("quiz", b'<section id="region-main">Temporarily unavailable</section>'),
    ],
)
def test_quiz_marker_must_be_inside_main_and_only_validates_quizzes(kind, html):
    with pytest.raises(InvalidActivityPage, match="activity_page_shape"):
        parse_activity_page(html, term="2026-2", kind=kind)
