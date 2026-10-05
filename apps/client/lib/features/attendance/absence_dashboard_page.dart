import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../domain/attendance.dart';

final class CourseAbsenceSummary {
  CourseAbsenceSummary._({
    required this.course,
    required this.sessions,
    required this.now,
    required this.location,
  });

  factory CourseAbsenceSummary.from(
    CourseRecord course,
    Iterable<SessionRecord> allSessions, {
    required DateTime now,
    required tz.Location location,
  }) {
    final sessions = allSessions.where(_countsAcademically).toList()
      ..sort((left, right) => left.startsAt.compareTo(right.startsAt));
    return CourseAbsenceSummary._(
      course: course,
      sessions: sessions,
      now: now,
      location: location,
    );
  }

  final CourseRecord course;
  final List<SessionRecord> sessions;
  final DateTime now;
  final tz.Location location;

  int get consumedAbsences => sessions.fold(
    0,
    (total, session) =>
        total +
        (session.calendarStatus == SessionCalendarStatus.noCall
            ? 0
            : session.absences ?? 0),
  );

  int get eligibleLessons =>
      sessions.fold(0, (total, session) => total + session.lessonCount.value);

  int get absenceLimit => eligibleLessons ~/ 4;

  int get remainingAbsences => max(0, absenceLimit - consumedAbsences);

  int get pendingSessions => sessions.where((session) {
    if (session.calendarStatus == SessionCalendarStatus.noCall ||
        session.absences != null) {
      return false;
    }
    final localSession = tz.TZDateTime.from(session.startsAt, location);
    final localNow = tz.TZDateTime.from(now, location);
    return DateTime(
      localSession.year,
      localSession.month,
      localSession.day,
    ).isBefore(DateTime(localNow.year, localNow.month, localNow.day));
  }).length;

  int get presentLessons => sessions.fold(0, (total, session) {
    final lessonCount = session.lessonCount.value;
    if (session.calendarStatus == SessionCalendarStatus.noCall) {
      return total + lessonCount;
    }
    final absences = session.absences;
    return total + (absences == null ? 0 : max(0, lessonCount - absences));
  });

  int get unresolvedLessons =>
      max(0, eligibleLessons - presentLessons - consumedAbsences);

  bool get minimumAttendanceGuaranteed =>
      eligibleLessons > 0 && presentLessons >= (eligibleLessons * .75).ceil();

  String get remainingMeetingsLabel {
    if (sessions.isEmpty) return '0 encontros restantes';
    final lessonCounts = sessions.map((item) => item.lessonCount.value).toSet();
    final callCounts = sessions.map((item) => item.callCount.value).toSet();
    if (lessonCounts.length != 1 || callCounts.length != 1) {
      return remainingAbsences == 1
          ? '1 aula de 50 min restante'
          : '$remainingAbsences aulas de 50 min restantes';
    }
    final raw = remainingAbsences / lessonCounts.single;
    final usable = callCounts.single == 1
        ? raw.floorToDouble()
        : (raw * 2).floor() / 2;
    final value = usable == usable.truncateToDouble()
        ? usable.toInt().toString()
        : usable.toStringAsFixed(1).replaceFirst('.', ',');
    return '$value ${usable == 1 ? 'encontro restante' : 'encontros restantes'}';
  }
}

bool _countsAcademically(SessionRecord session) =>
    session.calendarStatus == SessionCalendarStatus.scheduled ||
    session.calendarStatus == SessionCalendarStatus.makeup ||
    session.calendarStatus == SessionCalendarStatus.noCall;

class AbsenceDashboardPage extends StatefulWidget {
  const AbsenceDashboardPage({
    required this.courses,
    required this.repository,
    required this.location,
    required this.now,
    super.key,
  });

  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;
  final DateTime Function() now;

  @override
  State<AbsenceDashboardPage> createState() => _AbsenceDashboardPageState();
}

class _AbsenceDashboardPageState extends State<AbsenceDashboardPage> {
  List<CourseAbsenceSummary> _summaries = const [];
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final summaries = await Future.wait([
        for (final course in widget.courses)
          widget.repository
              .listSessions(course.id)
              .then(
                (sessions) => CourseAbsenceSummary.from(
                  course,
                  sessions,
                  now: widget.now(),
                  location: widget.location,
                ),
              ),
      ]);
      summaries.sort(
        (left, right) => left.course.code.compareTo(right.course.code),
      );
      if (mounted) setState(() => _summaries = summaries);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Faltas restantes')),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Padding(padding: const EdgeInsets.all(20), child: _content()),
        ),
      ),
    ),
  );

  Widget _content() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_failed) {
      return _MessageState(
        title: 'Não foi possível calcular suas faltas.',
        actionLabel: 'Tentar novamente',
        onAction: _load,
      );
    }
    if (_summaries.isEmpty) {
      return const Center(child: Text('Nenhuma disciplina cadastrada'));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'O limite corresponde a 25% das aulas sujeitas a chamada.',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        Expanded(
          child: ListView.separated(
            itemCount: _summaries.length,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (_, index) => _SummaryCard(
              summary: _summaries[index],
              location: widget.location,
            ),
          ),
        ),
      ],
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.summary, required this.location});

  final CourseAbsenceSummary summary;
  final tz.Location location;

  @override
  Widget build(BuildContext context) {
    final course = summary.course;
    return Card(
      elevation: 0,
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        title: Text(course.code),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(course.name),
            const SizedBox(height: 4),
            Text(
              '${summary.consumedAbsences} de ${summary.absenceLimit} faltas usadas'
              ' • ${_pendingLabel(summary.pendingSessions)}',
            ),
            const SizedBox(height: 10),
            _RemainingBadge(label: summary.remainingMeetingsLabel),
            const SizedBox(height: 12),
            _AttendanceBar(summary: summary),
          ],
        ),
        children: [
          if (summary.sessions.isEmpty)
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 4, 20, 20),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('Nenhuma sessão válida gerada'),
              ),
            )
          else
            for (final session in summary.sessions)
              _SessionImpactTile(session: session, location: location),
        ],
      ),
    );
  }
}

class _RemainingBadge extends StatelessWidget {
  const _RemainingBadge({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Text(
    label,
    style: Theme.of(context).textTheme.labelLarge?.copyWith(
      color: Theme.of(context).colorScheme.primary,
      fontWeight: FontWeight.w700,
    ),
  );
}

class _AttendanceBar extends StatelessWidget {
  const _AttendanceBar({required this.summary});

  final CourseAbsenceSummary summary;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      label:
          '${summary.presentLessons} presenças, '
          '${summary.consumedAbsences} faltas e '
          '${summary.unresolvedLessons} aulas ainda não definidas; '
          'marco de frequência mínima em 75%',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final width = min(232.0, constraints.maxWidth);
              return SizedBox(
                key: ValueKey('attendance-bar-${summary.course.id}'),
                width: width,
                height: width / 2 + 8,
                child: CustomPaint(
                  painter: _AttendanceBarPainter(
                    present: summary.presentLessons,
                    unresolved: summary.unresolvedLessons,
                    absent: summary.consumedAbsences,
                    presentColor: Colors.green.shade600,
                    unresolvedColor: colors.outlineVariant,
                    absentColor: colors.error,
                    markerColor: colors.onSurface,
                  ),
                ),
              );
            },
          ),
          const SizedBox(height: 4),
          Text(
            summary.minimumAttendanceGuaranteed
                ? 'Frequência mínima garantida'
                : 'Marco de frequência mínima: 75%',
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ],
      ),
    );
  }
}

class _AttendanceBarPainter extends CustomPainter {
  const _AttendanceBarPainter({
    required this.present,
    required this.unresolved,
    required this.absent,
    required this.presentColor,
    required this.unresolvedColor,
    required this.absentColor,
    required this.markerColor,
  });

  final int present;
  final int unresolved;
  final int absent;
  final Color presentColor;
  final Color unresolvedColor;
  final Color absentColor;
  final Color markerColor;

  @override
  void paint(Canvas canvas, Size size) {
    final total = present + unresolved + absent;
    if (total == 0 || size.isEmpty) return;
    const strokeWidth = 18.0;
    final center = Offset(size.width / 2, size.height - strokeWidth / 2);
    final radius = min(
      (size.width - strokeWidth) / 2,
      center.dy - strokeWidth / 2,
    );
    final rect = Rect.fromCircle(center: center, radius: radius);
    var start = pi;
    final segments = [
      (value: present, color: presentColor),
      (value: unresolved, color: unresolvedColor),
      (value: absent, color: absentColor),
    ];
    for (final segment in segments) {
      if (segment.value == 0) continue;
      final sweep = pi * segment.value / total;
      canvas.drawArc(
        rect,
        start,
        sweep,
        false,
        Paint()
          ..color = segment.color
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth
          ..strokeCap = StrokeCap.butt,
      );
      start += sweep;
    }
    final nonEmpty = segments.where((segment) => segment.value > 0).toList();
    canvas
      ..drawCircle(
        Offset(center.dx - radius, center.dy),
        strokeWidth / 2,
        Paint()..color = nonEmpty.first.color,
      )
      ..drawCircle(
        Offset(center.dx + radius, center.dy),
        strokeWidth / 2,
        Paint()..color = nonEmpty.last.color,
      );

    final markerAngle = pi * 1.75;
    final direction = Offset(cos(markerAngle), sin(markerAngle));
    canvas.drawLine(
      center + direction * (radius - strokeWidth / 2 - 4),
      center + direction * (radius + strokeWidth / 2 + 4),
      Paint()
        ..color = markerColor
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(_AttendanceBarPainter oldDelegate) =>
      present != oldDelegate.present ||
      unresolved != oldDelegate.unresolved ||
      absent != oldDelegate.absent ||
      presentColor != oldDelegate.presentColor ||
      unresolvedColor != oldDelegate.unresolvedColor ||
      absentColor != oldDelegate.absentColor ||
      markerColor != oldDelegate.markerColor;
}

class _SessionImpactTile extends StatelessWidget {
  const _SessionImpactTile({required this.session, required this.location});

  final SessionRecord session;
  final tz.Location location;

  @override
  Widget build(BuildContext context) {
    final localDate = tz.TZDateTime.from(session.startsAt, location);
    final absences = session.absences;
    return ListTile(
      dense: true,
      title: Text(
        '${_date(localDate)} • '
        '${session.calendarStatus == SessionCalendarStatus.noCall ? 'Presença garantida' : _statusName(session.attendanceStatus)}',
      ),
      subtitle: Text(
        session.calendarStatus == SessionCalendarStatus.noCall
            ? 'Aula realizada sem chamada • 0 faltas'
            : absences == null
            ? 'Uma ausência consumiria ${_absenceLabel(session.lessonCount.value)}'
            : '${_registeredLabel(absences)} • máximo de '
                  '${_absenceLabel(session.lessonCount.value)} nesta sessão',
      ),
    );
  }
}

class _MessageState extends StatelessWidget {
  const _MessageState({
    required this.title,
    required this.actionLabel,
    required this.onAction,
  });

  final String title;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(title, textAlign: TextAlign.center),
        const SizedBox(height: 12),
        OutlinedButton(onPressed: onAction, child: Text(actionLabel)),
      ],
    ),
  );
}

String _pendingLabel(int count) => switch (count) {
  0 => 'nenhuma pendência anterior',
  1 => '1 sessão anterior pendente',
  _ => '$count sessões anteriores pendentes',
};

String _registeredLabel(int count) =>
    count == 1 ? '1 falta registrada' : '$count faltas registradas';

String _absenceLabel(int count) => count == 1 ? '1 falta' : '$count faltas';

String _date(DateTime value) =>
    '${value.day.toString().padLeft(2, '0')}/'
    '${value.month.toString().padLeft(2, '0')}/${value.year}';

String _statusName(SituacaoFrequencia? status) => switch (status) {
  SituacaoFrequencia.present => 'Presente',
  SituacaoFrequencia.arrivedLate => 'Chegou atrasado',
  SituacaoFrequencia.leftEarly => 'Saiu mais cedo',
  SituacaoFrequencia.absent => 'Ausente',
  SituacaoFrequencia.pending || null => 'Sem registro',
};
