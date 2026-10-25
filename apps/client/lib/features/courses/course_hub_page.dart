import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../backend/python_backend_transport.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/attendance_progress_bar.dart';
import '../../design/app_theme.dart';
import '../../design/course_identity.dart';
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
    if (!widget.course.tracksAttendance) return null;
    final today = tz.TZDateTime.from(widget.now(), _location);
    for (final session in _sessions.reversed) {
      final local = tz.TZDateTime.from(session.startsAt, _location);
      final beforeToday = DateTime(
        local.year,
        local.month,
        local.day,
      ).isBefore(DateTime(today.year, today.month, today.day));
      if (beforeToday &&
          session.calendarStatus.requiresAttendance &&
          session.absences == null) {
        return session;
      }
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
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      toolbarHeight: 64,
      leadingWidth: 76,
      leading: Padding(
        padding: const EdgeInsets.only(left: 18, top: 8, bottom: 8),
        child: Tooltip(
          message: 'Voltar',
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.secondaryContainer,
              shape: BoxShape.circle,
            ),
            child: MediaQuery.withClampedTextScaling(
              maxScaleFactor: 1,
              child: CupertinoNavigationBarBackButton(
                previousPageTitle: '',
                color: Theme.of(context).colorScheme.onSecondaryContainer,
                onPressed: () => Navigator.of(context).maybePop(),
              ),
            ),
          ),
        ),
      ),
    ),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 780;
          return Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1080),
              child: SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                  compact ? 18 : 36,
                  compact ? 24 : 42,
                  compact ? 18 : 36,
                  56,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _courseIdentity(compact),
                    if (_firstPending != null) ...[
                      const SizedBox(height: 24),
                      _pendingAction(compact),
                    ],
                    SizedBox(height: compact ? 28 : 34),
                    _courseContent(compact),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    ),
  );

  Widget _courseIdentity(bool compact) => Row(
    key: const Key('course-hub-identity'),
    children: [
      CourseMark(
        key: const Key('course-hub-course-mark'),
        code: widget.course.code,
        size: compact ? 50 : 62,
      ),
      SizedBox(width: compact ? 12 : 18),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 0,
              runSpacing: 2,
              children: [
                Text(
                  widget.course.code,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  ),
                ),
                Text(
                  ' · ${widget.course.term.replaceFirst('-', '/')}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              widget.course.name,
              maxLines: compact ? 2 : 1,
              overflow: TextOverflow.ellipsis,
              style:
                  (compact
                          ? Theme.of(context).textTheme.headlineSmall
                          : Theme.of(context).textTheme.headlineMedium)
                      ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    ],
  );

  Widget _pendingAction(bool compact) {
    final pending = _firstPending!;
    return Container(
      key: const Key('course-hub-pending-action'),
      padding: const EdgeInsets.all(16),
      decoration: _panelDecoration(context, radius: 18),
      child: compact
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _pendingCopy(pending),
                const SizedBox(height: 16),
                FilledButton(
                  key: const Key('course-hub-open-attendance'),
                  onPressed: _openAttendance,
                  child: const Text('Resolver agora'),
                ),
              ],
            )
          : Row(
              children: [
                Expanded(child: _pendingCopy(pending)),
                const SizedBox(width: 20),
                FilledButton(
                  key: const Key('course-hub-open-attendance'),
                  onPressed: _openAttendance,
                  child: const Text('Resolver agora'),
                ),
              ],
            ),
    );
  }

  Widget _pendingCopy(SessionRecord pending) => Row(
    children: [
      Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Theme.of(context).colorScheme.error,
          boxShadow: [
            BoxShadow(
              color: Theme.of(context).colorScheme.error.withValues(alpha: .15),
              spreadRadius: 6,
            ),
          ],
        ),
      ),
      const SizedBox(width: 14),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Frequência pendente',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 3),
            Text(
              _pendingDescription(pending),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    ],
  );

  Widget _courseContent(bool compact) {
    final main = Column(
      children: [
        _frequencySection(),
        const SizedBox(height: 28),
        _agendaSection(),
      ],
    );
    final side = Column(
      children: [
        if (widget.course.modality != CourseModality.online) _scheduleSection(),
        const SizedBox(height: 28),
        _materialsSection(),
      ],
    );
    return KeyedSubtree(
      key: const Key('course-hub-section-grid'),
      child: compact
          ? Column(children: [main, const SizedBox(height: 28), side])
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 165, child: main),
                const SizedBox(width: 28),
                Expanded(flex: 80, child: side),
              ],
            ),
    );
  }

  Widget _frequencySection() {
    if (!widget.course.tracksAttendance) {
      return _Panel(
        key: const Key('course-hub-frequency'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.course.policyLabel,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            const Text(
              'Frequência: não se aplica. Atividades e materiais continuam disponíveis.',
            ),
          ],
        ),
      );
    }
    final summary = CourseAbsenceSummary.from(
      widget.course,
      _sessions,
      now: widget.now(),
      location: _location,
    );
    return _Panel(
      key: const Key('course-hub-frequency'),
      child: Column(
        key: const Key('course-hub-frequency-summary'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _SectionHeading(
            eyebrow: 'Situação atual',
            title: 'Frequência',
            action: TextButton.icon(
              key: Key(
                _firstPending == null
                    ? 'course-hub-open-attendance'
                    : 'course-hub-open-attendance-secondary',
              ),
              onPressed: _openAttendance,
              iconAlignment: IconAlignment.end,
              icon: const Icon(Icons.arrow_forward, size: 18),
              label: const Text('Ver registros'),
            ),
          ),
          const SizedBox(height: 22),
          if (_sessionsFailed)
            const Text('Não foi possível carregar a frequência agora.')
          else if (_loading && _sessions.isEmpty)
            const Text('Carregando…')
          else
            _FrequencyFigure(summary: summary),
        ],
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
      eyebrow: 'Agenda',
      title: 'Próximas datas',
      actionKey: const Key('course-hub-open-calendar'),
      actionLabel: 'Ver calendário',
      onAction: _openCalendar,
      child: upcoming.isEmpty
          ? const Text('Nenhuma avaliação ou entrega futura encontrada.')
          : Column(
              children: [
                for (final session in upcoming)
                  _EventRow(
                    session: session,
                    date: _shortDate(session.startsAt),
                  ),
              ],
            ),
    );
  }

  Widget _scheduleSection() => _HubSection(
    key: const Key('course-hub-schedule'),
    eyebrow: 'Organização',
    title: widget.course.tracksAttendance
        ? 'Grade e período'
        : 'Grade · Sem chamada',
    actionKey: const Key('course-hub-open-schedule'),
    actionLabel: 'Ver grade',
    onAction: _openSchedule,
    child: _meetingsFailed
        ? const Text('Não foi possível carregar a grade agora.')
        : _meetings.isEmpty
        ? const Text('Nenhum horário cadastrado.')
        : Column(
            children: [
              for (final meeting in _meetings)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _ScheduleRow(meeting: meeting),
                ),
            ],
          ),
  );

  Widget _materialsSection() {
    final count = _materials?.candidates.length ?? 0;
    return _HubSection(
      key: const Key('course-hub-materials'),
      eyebrow: 'Moodle',
      title: 'Materiais',
      actionKey: const Key('course-hub-open-materials'),
      actionLabel: 'Ver todos',
      onAction: widget.ufmgSessionGateway == null ? null : _openMaterials,
      child: count == 0
          ? const Text('Nenhum material sincronizado para esta disciplina.')
          : _MaterialPreview(
              candidate: _materials!.candidates.first,
              count: count,
            ),
    );
  }

  String _shortDate(DateTime value) {
    final local = tz.TZDateTime.from(value, _location);
    return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}';
  }

  String _pendingDescription(SessionRecord session) {
    final local = tz.TZDateTime.from(session.startsAt, _location);
    const months = [
      'janeiro',
      'fevereiro',
      'março',
      'abril',
      'maio',
      'junho',
      'julho',
      'agosto',
      'setembro',
      'outubro',
      'novembro',
      'dezembro',
    ];
    return '${local.day} de ${months[local.month - 1]} · ${_clock(local.hour * 60 + local.minute)}';
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, super.key});
  final Widget child;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(22),
    decoration: _panelDecoration(context),
    child: child,
  );
}

class _HubSection extends StatelessWidget {
  const _HubSection({
    required this.eyebrow,
    required this.title,
    required this.child,
    required this.actionLabel,
    this.actionKey,
    this.onAction,
    super.key,
  });
  final String eyebrow;
  final String title;
  final Widget child;
  final String actionLabel;
  final Key? actionKey;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) => _Panel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SectionHeading(
          eyebrow: eyebrow,
          title: title,
          action: TextButton(
            key: actionKey,
            onPressed: onAction,
            child: Text(actionLabel),
          ),
        ),
        const SizedBox(height: 16),
        child,
      ],
    ),
  );
}

BoxDecoration _panelDecoration(BuildContext context, {double radius = 22}) =>
    BoxDecoration(
      color: Theme.of(context).colorScheme.surface.withValues(alpha: .84),
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: _semantic(context).separator),
    );

AppSemanticColors _semantic(BuildContext context) =>
    Theme.of(context).extension<AppSemanticColors>() ??
    const AppSemanticColors(
      success: Color(0xFF197A3E),
      warning: Color(0xFF925900),
      info: Color(0xFF1769AA),
      subtleSurface: Color(0xFFEEF2EF),
      separator: Color(0xFFDCE3DE),
    );

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({
    required this.eyebrow,
    required this.title,
    required this.action,
  });
  final String eyebrow;
  final String title;
  final Widget action;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final copy = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            eyebrow.toUpperCase(),
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w700,
              letterSpacing: .6,
            ),
          ),
          const SizedBox(height: 4),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
        ],
      );
      if (constraints.maxWidth < 300) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            copy,
            Align(alignment: Alignment.centerLeft, child: action),
          ],
        );
      }
      return Row(
        children: [
          Expanded(child: copy),
          action,
        ],
      );
    },
  );
}

class _FrequencyFigure extends StatelessWidget {
  const _FrequencyFigure({required this.summary});
  final CourseAbsenceSummary summary;
  @override
  Widget build(BuildContext context) {
    final figure = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${summary.remainingAbsences}',
          style: Theme.of(context).textTheme.displaySmall?.copyWith(
            color: _semantic(context).success,
            fontWeight: FontWeight.w700,
            letterSpacing: -1.5,
            height: .95,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          summary.remainingMeetingsLabel,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
    final track = AttendanceProgressBar(
      present: summary.presentLessons,
      unresolved: summary.unresolvedLessons,
      absent: summary.consumedAbsences,
      barKey: const Key('course-hub-frequency-track'),
      markerKey: const Key('course-hub-frequency-limit-marker'),
    );
    return LayoutBuilder(
      builder: (context, constraints) => constraints.maxWidth < 520
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [figure, const SizedBox(height: 22), track],
            )
          : Row(
              children: [
                SizedBox(width: 136, child: figure),
                const SizedBox(width: 20),
                Expanded(child: track),
              ],
            ),
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.session, required this.date});
  final SessionRecord session;
  final String date;
  @override
  Widget build(BuildContext context) {
    final parts = date.split('/');
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: _semantic(context).separator)),
      ),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 50,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: _semantic(context).subtleSurface,
              borderRadius: BorderRadius.circular(13),
            ),
            child: Text(
              '${parts[0]}\n${parts[1]}',
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Text(
              session.assessmentTitle!,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          const Icon(Icons.chevron_right, size: 20),
        ],
      ),
    );
  }
}

class _ScheduleRow extends StatelessWidget {
  const _ScheduleRow({required this.meeting});
  final MeetingRecord meeting;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
        decoration: BoxDecoration(
          color: _semantic(context).success.withValues(alpha: .10),
          borderRadius: BorderRadius.circular(9),
        ),
        child: Text(
          _weekday(meeting.weekday),
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            color: _semantic(context).success,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Text(
          '${_clock(meeting.startMinutes)}–${_clock(meeting.endMinutes)}',
        ),
      ),
    ],
  );
}

class _MaterialPreview extends StatelessWidget {
  const _MaterialPreview({required this.candidate, required this.count});
  final PythonMoodleContentCandidate candidate;
  final int count;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Container(height: 1, color: _semantic(context).separator),
      const SizedBox(height: 12),
      Row(
        children: [
          Container(
            width: 38,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Theme.of(
                context,
              ).colorScheme.errorContainer.withValues(alpha: .65),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Text(
              candidate.kind == 'file' ? 'PDF' : 'WEB',
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  candidate.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  'Disponível no Moodle',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          const Icon(Icons.arrow_forward, size: 19),
        ],
      ),
      const SizedBox(height: 10),
      Text(
        '$count ${count == 1 ? 'material disponível' : 'materiais disponíveis'}',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      ),
    ],
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
