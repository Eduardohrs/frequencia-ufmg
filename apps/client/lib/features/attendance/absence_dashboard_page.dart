import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../domain/attendance.dart';

final class CourseAbsenceSummary {
  CourseAbsenceSummary.from(this.course, Iterable<SessionRecord> allSessions)
    : sessions =
          allSessions
              .where(
                (session) =>
                    session.calendarStatus == SessionCalendarStatus.scheduled ||
                    session.calendarStatus == SessionCalendarStatus.makeup,
              )
              .toList()
            ..sort((left, right) => left.startsAt.compareTo(right.startsAt));

  final CourseRecord course;
  final List<SessionRecord> sessions;

  int get consumedAbsences =>
      sessions.fold(0, (total, session) => total + (session.absences ?? 0));

  int get absenceLimit => course.workload ~/ 4;

  int get remainingAbsences => max(0, absenceLimit - consumedAbsences);

  int get pendingSessions =>
      sessions.where((session) => session.absences == null).length;
}

class AbsenceDashboardPage extends StatefulWidget {
  const AbsenceDashboardPage({
    required this.courses,
    required this.repository,
    required this.location,
    super.key,
  });

  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;

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
              .then((sessions) => CourseAbsenceSummary.from(course, sessions)),
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
          'O limite corresponde a 25% da carga horária de cada disciplina.',
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
          ],
        ),
        leading: _RemainingBadge(value: summary.remainingAbsences),
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
  const _RemainingBadge({required this.value});

  final int value;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 88,
    child: Text(
      '$value ${value == 1 ? 'falta restante' : 'faltas restantes'}',
      textAlign: TextAlign.center,
      style: Theme.of(context).textTheme.labelMedium?.copyWith(
        color: Theme.of(context).colorScheme.primary,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
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
        '${_date(localDate)} • ${_statusName(session.attendanceStatus)}',
      ),
      subtitle: Text(
        absences == null
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
  0 => 'nenhuma sessão pendente',
  1 => '1 sessão pendente',
  _ => '$count sessões pendentes',
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
