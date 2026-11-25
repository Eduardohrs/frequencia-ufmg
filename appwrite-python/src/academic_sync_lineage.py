# ruff: noqa: E501
"""Field-level source-to-storage contracts emitted with academic sync telemetry.

The values in this module are deliberately static metadata.  They describe the
fields the parsers actually read and the Firestore fields that receive them;
they do not contain credentials, response bodies, user identifiers, or course
data.  Keeping the contract beside the code makes a production trace answer
"where did this value come from and where did it go?" without logging payloads.
"""

from typing import Final

SIGA_ENROLLMENT: Final = {
    "endpoints": ["GET https://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas"],
    "response_fields_used": [
        "listaObj[0].semestreLetivo",
        "listaObj[0].dataInicialSemestre",
        "listaObj[0].dataFinalSemestre",
        "listaObj[0].matriculas[].turma.atividadeAcademica.codigo",
        "listaObj[0].matriculas[].turma.atividadeAcademica.nome (fallback: nomeReduzido)",
        "listaObj[0].matriculas[].turma.atividadeAcademica.cargaHoraria",
        "listaObj[0].matriculas[].turma.horarios[].diaDaSemana",
        "listaObj[0].matriculas[].turma.horarios[].horaInicial",
        "listaObj[0].matriculas[].turma.horarios[].horaFinal",
    ],
    "field_mapping": [
        {"from": "semestreLetivo", "to": "courses.term", "use": "course identity"},
        {"from": "dataInicialSemestre", "to": "courses.startsOn", "use": "term bounds"},
        {"from": "dataFinalSemestre", "to": "courses.endsOn", "use": "term bounds"},
        {"from": "atividadeAcademica.codigo", "to": "courses.code", "use": "course identity"},
        {"from": "atividadeAcademica.nome|nomeReduzido", "to": "courses.name", "use": "course label"},
        {"from": "atividadeAcademica.cargaHoraria", "to": "courses.workload", "use": "workload validation"},
        {"from": "horarios[].diaDaSemana", "to": "meetings.weekday", "use": "weekly schedule"},
        {"from": "horarios[].horaInicial", "to": "meetings.startMinutes", "use": "weekly schedule"},
        {"from": "horarios[].horaFinal", "to": "meetings.endMinutes+lessonCount", "use": "weekly schedule"},
    ],
    "destinations": [
        {
            "path": "courses/{course_id}",
            "fields": ["code", "name", "workload", "term", "startsOn", "endsOn", "updatedAt"],
            "consumer": "course_repository, discipline header and attendance rules",
        },
        {
            "path": "courses/{course_id}/meetings/{meeting_id}",
            "fields": ["weekday", "startMinutes", "endMinutes", "lessonCount", "callCount", "createdAt", "updatedAt"],
            "consumer": "schedule repository, session reconciliation and frequency calculations",
        },
    ],
}


MOODLE_CALENDAR: Final = {
    "endpoints": [
        "POST https://virtual.ufmg.br/{term_path}/lib/ajax/service.php",
        "AJAX method core_calendar_get_calendar_monthly_view",
    ],
    "response_fields_used": [
        "[].error",
        "[].data.weeks[].days[].events[].id",
        "[].data.weeks[].days[].events[].name",
        "[].data.weeks[].days[].events[].timestart",
        "[].data.weeks[].days[].events[].modulename",
        "[].data.weeks[].days[].events[].course.id",
        "[].data.weeks[].days[].events[].course.shortname",
        "[].data.weeks[].days[].events[].course.fullname",
    ],
    "field_mapping": [
        {"from": "event.id", "to": "academicDates.sourceId", "use": "stable Moodle event identity"},
        {"from": "event.name", "to": "academicDates.title", "use": "agenda label"},
        {"from": "event.timestart", "to": "academicDates.dueAt", "use": "agenda instant in UTC"},
        {"from": "event.modulename", "to": "academicDates.kind", "use": "assign→assignment, quiz→quiz, other→event"},
        {"from": "event.course.id", "to": "course matching only", "use": "attach event to exactly one local discipline"},
        {"from": "event.course.shortname|fullname", "to": "course matching only", "use": "code/term match; not persisted as source fields"},
    ],
    "destinations": [
        {
            "path": "courses/{course_id}/academicDates/moodle-{event_id}",
            "fields": ["title", "dueAt", "kind", "source=moodle", "sourceId", "createdAt", "updatedAt", "manualOverride (optional)"],
            "consumer": "global next dates, discipline dates and agenda filters",
        },
    ],
    "scope_note": "This source creates academicDates only. It does not create class sessions; official class occurrences come from the teaching-plan schedule.",
}


MOODLE_MATERIAL_CATALOG: Final = {
    "endpoints": [
        "POST https://virtual.ufmg.br/{term_path}/lib/ajax/service.php",
        "AJAX methods core_course_get_enrolled_courses_by_timeline_classification and core_courseformat_get_state",
    ],
    "response_fields_used": [
        "course-list[].data.courses[].id",
        "course-list[].data.courses[].shortname",
        "course-list[].data.courses[].fullname",
        "course-state[].data (JSON string).cm[].uservisible",
        "course-state[].data (JSON string).cm[].module",
        "course-state[].data (JSON string).cm[].id",
        "course-state[].data (JSON string).cm[].name",
        "course-state[].data (JSON string).cm[].url",
    ],
    "field_mapping": [
        {"from": "courses[].id|shortname|fullname", "to": "materialCatalog.moodleCourseId/status", "use": "canonical/metaturma course linking"},
        {"from": "cm[].id", "to": "materialCatalog.materialsJson[].source_id", "use": "Moodle module identity"},
        {"from": "cm[].module", "to": "materialCatalog.materialsJson[].kind", "use": "page/file/link/text classification"},
        {"from": "cm[].name", "to": "materialCatalog.materialsJson[].title", "use": "material label"},
        {"from": "cm[].url", "to": "materialCatalog.materialsJson[].url", "use": "open module in Moodle"},
        {"from": "course/metadata and title", "to": "materialCatalog.materialsJson[].relevance/origin", "use": "teaching-plan selection and metaturma marker"},
    ],
    "destinations": [
        {
            "path": "courses/{course_id}/materialCatalog/current",
            "fields": ["schemaVersion", "term", "status", "moodleCourseId", "candidateCount", "metaturmaCandidateCount", "materialsJson", "contentHash", "createdAt", "updatedAt"],
            "consumer": "discipline materials and canonical teaching-plan selection",
        },
    ],
}


MOODLE_ACTIVITY_SNAPSHOT: Final = {
    "endpoints": [
        "POST https://virtual.ufmg.br/{term_path}/lib/ajax/service.php (core_courseformat_get_state)",
        "POST https://virtual.ufmg.br/{term_path}/lib/ajax/service.php (core_course_get_updates_since)",
        "POST https://virtual.ufmg.br/{term_path}/webservice/rest/server.php (core_course_get_contents)",
        "POST https://virtual.ufmg.br/{term_path}/webservice/rest/server.php (mod_assign_get_assignments, conditional)",
        "POST https://virtual.ufmg.br/{term_path}/webservice/rest/server.php (mod_quiz_get_quizzes_by_courses, conditional)",
        "GET https://virtual.ufmg.br/{term_path}/mod/{assign|quiz}/view.php?id={cmid} (HTML fallback only)",
    ],
    "response_fields_used": [
        "course-state.data.cm[].id|module|name|url|uservisible",
        "updates.data.instances[].id|updates[]",
        "core_course_get_contents[].modules[].id|modname|name|description|dates[]|contents[]",
        "contents[].dates[].label|timestamp",
        "contents[].contents[].type|filename|fileurl",
        "assignments[].cmid|name|intro|activity|introattachments|activityattachments|allowsubmissionsfromdate|duedate|cutoffdate|gradingduedate",
        "quizzes[].coursemodule|name|intro|contents|timeopen|timeclose",
        "HTML activity parser output: description|dates_text|has_due_date|submission_state|submission_text|attachments",
    ],
    "field_mapping": [
        {"from": "cm[].id|module|name|url", "to": "snapshot.activities[].source_id|kind|title|url", "use": "activity index"},
        {"from": "updates.instances[].id|updates[]", "to": "reuse decision", "use": "skip unchanged activity details"},
        {"from": "bulk/module descriptions", "to": "snapshot.activities[].description", "use": "offline detail"},
        {"from": "dates or allowsubmissions*/due*/time*", "to": "snapshot.activities[].dates_text|has_due_date", "use": "activity deadlines"},
        {"from": "intro/activity attachments and contents", "to": "snapshot.activities[].attachments", "use": "direct Moodle download links"},
        {"from": "HTML submission fields", "to": "snapshot.activities[].submission_state|submission_text", "use": "student-specific state when bulk lacks it"},
    ],
    "destinations": [
        {
            "path": "courses/{course_id}/activitySnapshots/current",
            "fields": ["schemaVersion", "snapshotJson", "contentHash", "updatedAt"],
            "consumer": "discipline activity view and local/offline snapshot",
        },
        {
            "path": "snapshotJson.activities[]",
            "fields": ["source_id", "kind", "title", "url", "relevance", "description", "dates_text", "has_due_date", "submission_state", "submission_text", "attachments", "files", "term"],
            "consumer": "activity cards, deadlines and direct file opening",
        },
    ],
    "overlap_policy": "The calendar owns academicDates agenda records; the activity snapshot owns activity details and links. A due date may be represented in both views but is not written twice into the same collection.",
}


DIARIO_TEACHING_PLAN: Final = {
    "endpoints": [
        "GET https://virtual.ufmg.br/{term_path}/mod/url/view.php?id={source_id} (Moodle launch)",
        "GET/POST https://sistemas.ufmg.br/diario/JasperServlet (official Diário document/transition)",
    ],
    "response_fields_used": [
        "Plano identity: Período, Atividade, Turma",
        "Avaliações rows: cod, tipo, nome, data/hora, local, valor, peso",
        "Critérios rows: descrição, valor parcial",
        "Cronograma rows: aula, data, dia, num. aulas, horário, tipo, assunto",
    ],
    "field_mapping": [
        {"from": "Período|Atividade|Turma", "to": "teachingPlans.planJson.term|course_code|class_group", "use": "plan identity validation"},
        {"from": "Avaliações.cod|tipo|nome|data/hora|local|valor|peso", "to": "teachingPlans.planJson.assessments[]", "use": "official assessment plan"},
        {"from": "Avaliações.cod|nome|data/hora", "to": "academicDates.diario-{source_id}-{code}.sourceId|title|dueAt", "use": "assessment date in agenda"},
        {"from": "Critérios.descrição|valor parcial", "to": "teachingPlans.planJson.criteria[]", "use": "grade calculation context"},
        {"from": "Cronograma.aula|data|dia|num. aulas|horário|tipo|assunto", "to": "teachingPlans.planJson.schedule[]", "use": "official class occurrences"},
        {"from": "Cronograma.schedule[]", "to": "courses/{course_id}/sessions/{session_id}", "use": "reconciliation creates/updates class sessions; exact/manual conflicts are preserved"},
    ],
    "destinations": [
        {
            "path": "courses/{course_id}/teachingPlans/current",
            "fields": ["schemaVersion", "source=ufmg_diario", "sourceId", "confidence=authoritative", "planJson", "contentHash", "collectedAt", "createdAt", "updatedAt"],
            "consumer": "teaching-plan screen and reconciliation",
        },
        {
            "path": "courses/{course_id}/academicDates/diario-{source_id}-{assessment_code}",
            "fields": ["title", "dueAt", "kind=assessment", "source=diario", "sourceId", "createdAt", "updatedAt"],
            "consumer": "agenda and discipline dates",
        },
        {
            "path": "courses/{course_id}/sessions/{session_id}",
            "fields": ["startsAt", "endsAt", "lessonCount", "callCount", "calendarStatus", "assessmentTitle", "firstPing", "secondPing", "attendanceStatus", "absences", "createdAt", "updatedAt"],
            "consumer": "frequency register and attendance calculations",
        },
    ],
    "overlap_policy": "The teaching plan is authoritative for class occurrences and assessments; SIGA weekly meetings validate the recurring schedule; existing manual/attendance records are not overwritten.",
}
