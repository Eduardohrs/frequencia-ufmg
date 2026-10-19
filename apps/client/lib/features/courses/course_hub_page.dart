import 'dart:async';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../backend/python_backend_transport.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../observability/app_logger.dart';
import '../attendance/absence_dashboard_page.dart';
import '../attendance/attendance_page.dart';
import '../schedule/course_schedule_page.dart';
import '../schedule/general_calendar_page.dart';
import '../ufmg/ufmg_connection_page.dart';

class CourseHubPage extends StatefulWidget {
  const CourseHubPage({
    required this.course,
    required this.allCourses,
    required this.courseRepository,
    required this.meetingRepository,
    required this.sessionRepository,
    required this.logger,
    required this.now,
    this.initialSessionsByCourse,
    this.attendanceEvaluator,
    this.scheduleGateway,
    this.sessionGateway,
    this.ufmgSessionGateway,
    this.ufmgSyncSchedule,
    this.userId,
    this.scheduleReadsEnabled = true,
    this.scheduleWritesEnabled = false,
    this.sessionWritesEnabled = false,
    this.androidOfflineQueueEnabled = false,
    super.key,
  });

  final CourseRecord course;
  final List<CourseRecord> allCourses;
  final CourseRepository courseRepository;
  final MeetingRepository meetingRepository;
  final SessionRepository sessionRepository;
  final AppLogger logger;
  final DateTime Function() now;
  final Map<String, List<SessionRecord>>? initialSessionsByCourse;
  final BackendAttendanceEvaluator? attendanceEvaluator;
  final BackendScheduleGateway? scheduleGateway;
  final BackendSessionGateway? sessionGateway;
  final BackendUFMGSessionGateway? ufmgSessionGateway;
  final UFMGSyncScheduleGateway? ufmgSyncSchedule;
  final String? userId;
  final bool scheduleReadsEnabled;
  final bool scheduleWritesEnabled;
  final bool sessionWritesEnabled;
  final bool androidOfflineQueueEnabled;

  @override
  State<CourseHubPage> createState() => _CourseHubPageState();
}

class _CourseHubPageState extends State<CourseHubPage> {
  static final _location = tz.getLocation('America/Sao_Paulo');
  List<SessionRecord> _sessions = const [];
  List<MeetingRecord> _meetings = const [];
  PythonMoodleCourseContent? _materials;
  bool _sessionsFailed = false;
  bool _meetingsFailed = false;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final initial = widget.initialSessionsByCourse?[widget.course.id];
    if (initial != null) _sessions = List.of(initial);
    final results = await Future.wait([
      if (initial == null)
        widget.sessionRepository
            .listSessions(widget.course.id)
            .then(
              (value) => _sessions = List.of(value),
              onError: (_) {
                _sessionsFailed = true;
                return _sessions = <SessionRecord>[];
              },
            ),
      widget.meetingRepository
          .listMeetings(widget.course.id)
          .then(
            (value) => _meetings = List.of(value),
            onError: (_) {
              _meetingsFailed = true;
              return _meetings = <MeetingRecord>[];
            },
          ),
      if (widget.ufmgSessionGateway case final gateway?)
        gateway.listMoodleMaterialCatalog().then((catalog) {
          for (final item in catalog.courses) {
            if (_matchesCourse(item)) {
              _materials = item;
              break;
            }
          }
        }, onError: (_) {}), // coverage:ignore-line
    ]);
    results.length;
    _sessions.sort((a, b) => a.startsAt.compareTo(b.startsAt));
    _meetings.sort((a, b) {
      final weekday = a.weekday.compareTo(b.weekday);
      return weekday != 0 ? weekday : a.startMinutes.compareTo(b.startMinutes);
    });
    if (mounted) setState(() => _loading = false);
  }

  bool _matchesCourse(PythonMoodleCourseContent item) =>
      item.courseId == widget.course.id ||
      (item.courseCode.toUpperCase() == widget.course.code.toUpperCase() &&
          item.term == widget.course.term);

  Future<void> _openAttendance() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AttendancePage(
          courseId: widget.course.id,
          courseCode: widget.course.code,
          repository: widget.sessionRepository,
          logger: widget.logger,
          location: _location,
          now: widget.now,
          attendanceEvaluator: widget.attendanceEvaluator,
          sessionGateway: widget.sessionGateway,
          sessionWritesEnabled: widget.sessionWritesEnabled,
          androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          initialSessions: _sessions,
          initialSessionId: _firstPending?.id,
        ),
      ),
    );
    if (mounted) await _reloadSessions();
  }

  Future<void> _reloadSessions() async {
    try {
      final sessions = await widget.sessionRepository.listSessions(
        widget.course.id,
      );
      sessions.sort((a, b) => a.startsAt.compareTo(b.startsAt));
      if (mounted) setState(() => _sessions = sessions);
    } catch (_) {} // coverage:ignore-line
  }

  SessionRecord? get _firstPending {
    final today = tz.TZDateTime.from(widget.now(), _location);
    for (final session in _sessions.reversed) {
      final local = tz.TZDateTime.from(session.startsAt, _location);
      final beforeToday = DateTime(
        local.year,
        local.month,
        local.day,
      ).isBefore(DateTime(today.year, today.month, today.day));
      if (beforeToday && session.absences == null) return session;
    }
    return null;
  }

  Future<void> _openCalendar() => Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => GeneralCalendarPage(
        courses: widget.allCourses,
        repository: widget.sessionRepository,
        location: _location,
        now: widget.now,
        initialCourseId: widget.course.id,
        initialSessionsByCourse: widget.initialSessionsByCourse,
      ),
    ),
  );

  Future<void> _openSchedule() => Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => CourseSchedulePage(
        course: widget.course,
        courseRepository: widget.courseRepository,
        repository: widget.meetingRepository,
        sessionRepository: widget.sessionRepository,
        logger: widget.logger,
        attendanceEvaluator: widget.attendanceEvaluator,
        scheduleGateway: widget.scheduleGateway,
        scheduleReadsEnabled: widget.scheduleReadsEnabled,
        sessionGateway: widget.sessionGateway,
        scheduleWritesEnabled: widget.scheduleWritesEnabled,
        sessionWritesEnabled: widget.sessionWritesEnabled,
        androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
        initialSessionsByCourse: widget.initialSessionsByCourse,
        allCourses: widget.allCourses,
        allCourseIds: widget.allCourses.map((item) => item.id),
      ),
    ),
  );

  Future<void> _openMaterials() async {
    final gateway = widget.ufmgSessionGateway!;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => UFMGConnectionPage(
          gateway: gateway,
          logger: widget.logger,
          userId: widget.userId,
          syncSchedule: widget.ufmgSyncSchedule,
          materialCourseId: widget.course.id,
          materialCourseCode: widget.course.code,
          materialCourseTerm: widget.course.term,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.course.code)),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 960),
              child: SingleChildScrollView(
                padding: EdgeInsets.all(constraints.maxWidth < 600 ? 16 : 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      widget.course.name,
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${widget.course.code} • ${widget.course.term}',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _attendanceAction(),
                    const SizedBox(height: 12),
                    _frequencySection(),
                    const SizedBox(height: 12),
                    _agendaSection(),
                    const SizedBox(height: 12),
                    _scheduleSection(),
                    const SizedBox(height: 12),
                    _materialsSection(),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _attendanceAction() => FilledButton.icon(
    key: const Key('course-hub-open-attendance'),
    onPressed: _openAttendance,
    icon: const Icon(Icons.how_to_reg_outlined),
    label: Text(
      _firstPending == null ? 'Registrar frequência' : 'Resolver pendência',
    ),
  );

  Widget _frequencySection() {
    final summary = CourseAbsenceSummary.from(
      widget.course,
      _sessions,
      now: widget.now(),
      location: _location,
    );
    return _HubSection(
      key: const Key('course-hub-frequency'),
      icon: Icons.donut_large_outlined,
      title: 'Frequência',
      actionLabel: 'Ver registros',
      onAction: _openAttendance,
      child: _sessionsFailed
          ? const Text('Não foi possível carregar a frequência agora.')
          : Text(
              _loading && _sessions.isEmpty
                  ? 'Carregando…'
                  : '${summary.consumedAbsences} de ${summary.absenceLimit} faltas usadas • ${summary.remainingMeetingsLabel}',
            ),
    );
  }

  Widget _agendaSection() {
    final now = widget.now();
    final upcoming = _sessions
        .where(
          (session) =>
              session.assessmentTitle != null &&
              session.startsAt.isAfter(now.subtract(const Duration(days: 1))),
        )
        .take(3)
        .toList();
    return _HubSection(
      key: const Key('course-hub-agenda'),
      icon: Icons.event_outlined,
      title: 'Próximas datas',
      actionKey: const Key('course-hub-open-calendar'),
      actionLabel: 'Ver calendário',
      onAction: _openCalendar,
      child: upcoming.isEmpty
          ? const Text('Nenhuma avaliação ou entrega futura encontrada.')
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final session in upcoming)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text(
                      '${session.assessmentTitle} • ${_shortDate(session.startsAt)}',
                    ),
                  ),
              ],
            ),
    );
  }

  Widget _scheduleSection() => _HubSection(
    key: const Key('course-hub-schedule'),
    icon: Icons.schedule_outlined,
    title: 'Grade e período',
    actionKey: const Key('course-hub-open-schedule'),
    actionLabel: 'Ver grade',
    onAction: _openSchedule,
    child: _meetingsFailed
        ? const Text('Não foi possível carregar a grade agora.')
        : _meetings.isEmpty
        ? const Text('Nenhum horário cadastrado.')
        : Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final meeting in _meetings)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text(
                    '${_weekday(meeting.weekday)}, ${_clock(meeting.startMinutes)}–${_clock(meeting.endMinutes)}',
                  ),
                ),
            ],
          ),
  );

  Widget _materialsSection() {
    final count = _materials?.candidates.length ?? 0;
    return _HubSection(
      key: const Key('course-hub-materials'),
      icon: Icons.folder_outlined,
      title: 'Materiais',
      actionKey: const Key('course-hub-open-materials'),
      actionLabel: 'Ver materiais',
      onAction: widget.ufmgSessionGateway == null ? null : _openMaterials,
      child: Text(
        count == 0
            ? 'Nenhum material sincronizado para esta disciplina.'
            : '$count ${count == 1 ? 'material disponível' : 'materiais disponíveis'}',
      ),
    );
  }

  String _shortDate(DateTime value) {
    final local = tz.TZDateTime.from(value, _location);
    return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}';
  }
}

class _HubSection extends StatelessWidget {
  const _HubSection({
    required this.icon,
    required this.title,
    required this.child,
    required this.actionLabel,
    this.actionKey,
    this.onAction,
    super.key,
  });

  final IconData icon;
  final String title;
  final Widget child;
  final String actionLabel;
  final Key? actionKey;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(icon),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          child,
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              key: actionKey,
              onPressed: onAction,
              child: Text(actionLabel),
            ),
          ),
        ],
      ),
    ),
  );
}

String _weekday(int weekday) => const [
  'Segunda',
  'Terça',
  'Quarta',
  'Quinta',
  'Sexta',
  'Sábado',
  'Domingo',
][weekday - 1];

String _clock(int minutes) =>
    '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';
