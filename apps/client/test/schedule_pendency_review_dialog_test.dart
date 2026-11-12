import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/features/ufmg/schedule_pendency_review_dialog.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  testWidgets('lists pendencies and applies a decision end to end', (
    tester,
  ) async {
    final gateway = _PendencyGateway();
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(gateway: gateway, logger: logger),
      ),
    );
    await tester.tap(find.byKey(const Key('open-review')));
    await tester.pumpAndSettle();

    expect(find.text('Pendências de horário'), findsOneWidget);
    expect(find.textContaining('DCC203'), findsOneWidget);
    expect(find.textContaining('POO'), findsOneWidget);
    expect(find.text('Atual: seg 07:30 (2 aulas)'), findsOneWidget);
    expect(find.text('Novo: qua 10:00 (2 aulas)'), findsOneWidget);
    expect(find.text('Motivo: manual_schedule_diverged'), findsOneWidget);
    expect(find.byKey(const Key('pendency-keep-pend-1')), findsOneWidget);
    expect(find.byKey(const Key('pendency-apply-pend-1')), findsOneWidget);

    await tester.tap(find.byKey(const Key('pendency-apply-pend-1')));
    await tester.pumpAndSettle();

    expect(gateway.decisions, [
      ('pend-1', PythonScheduleDecision.aplicarMudanca),
    ]);
    expect(gateway.listCalls, 2);
    expect(find.text('Mudança aplicada'), findsOneWidget);
    expect(find.byKey(const Key('pendency-keep-pend-1')), findsNothing);
    expect(find.byKey(const Key('pendency-apply-pend-1')), findsNothing);

    await tester.tap(find.byKey(const Key('pendency-review-close')));
    await tester.pumpAndSettle();
    expect(find.text('Pendências de horário'), findsNothing);
  });

  testWidgets('keeps the current schedule and refreshes manually', (
    tester,
  ) async {
    final gateway = _PendencyGateway();
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.tap(find.byKey(const Key('open-review')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('pendency-keep-pend-1')));
    await tester.pumpAndSettle();
    expect(gateway.decisions, [('pend-1', PythonScheduleDecision.manterAtual)]);
    expect(find.text('Horário atual mantido'), findsOneWidget);

    gateway.extra = const [
      PythonSchedulePendency(
        id: 'pend-9',
        courseId: 'c9',
        courseCode: 'DCC999',
        courseName: 'Teste',
        currentSchedule: 'sex 08:00 (1 aula)',
        newSchedule: 'sex 09:00 (1 aula)',
        reason: 'destructive_change',
        status: 'pending',
      ),
    ];
    await tester.tap(find.byKey(const Key('pendency-review-refresh')));
    await tester.pumpAndSettle();
    expect(find.textContaining('DCC999'), findsOneWidget);
    expect(gateway.listCalls, 3);
  });

  testWidgets('shows empty, error and recovery states', (tester) async {
    final gateway = _PendencyGateway()..empty = true;
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(gateway: gateway, logger: logger),
      ),
    );
    await tester.tap(find.byKey(const Key('open-review')));
    await tester.pumpAndSettle();
    expect(
      find.text('Nenhuma pendência de horário no momento.'),
      findsOneWidget,
    );

    gateway.empty = false;
    gateway.listError = StateError('offline');
    await tester.tap(find.byKey(const Key('pendency-review-refresh')));
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível carregar as pendências de horário.'),
      findsOneWidget,
    );
    expect(logger.errorContexts, contains('schedule_pendency_list'));

    gateway.listError = null;
    await tester.tap(find.byKey(const Key('pendency-review-refresh')));
    await tester.pumpAndSettle();
    expect(find.textContaining('DCC203'), findsOneWidget);
  });

  testWidgets('reports a failed decision without losing the list', (
    tester,
  ) async {
    final gateway = _PendencyGateway()..decideError = StateError('boom');
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(gateway: gateway, logger: logger),
      ),
    );
    await tester.tap(find.byKey(const Key('open-review')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('pendency-keep-pend-1')));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível registrar a decisão.'), findsOneWidget);
    expect(logger.errorContexts, contains('schedule_pendency_decide'));
    expect(find.textContaining('DCC203'), findsOneWidget);
    expect(find.byKey(const Key('pendency-keep-pend-1')), findsOneWidget);
  });

  testWidgets('labels an unknown stored decision generically', (tester) async {
    final gateway = _PendencyGateway()
      ..extra = const [
        PythonSchedulePendency(
          id: 'pend-7',
          courseId: 'c7',
          courseCode: 'DCC777',
          courseName: 'Antiga',
          currentSchedule: 'seg 08:00 (2 aulas)',
          newSchedule: 'ter 08:00 (2 aulas)',
          reason: 'schedule_overlap',
          status: 'resolved',
          decision: 'outra_decisao',
        ),
      ];
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.tap(find.byKey(const Key('open-review')));
    await tester.pumpAndSettle();
    expect(find.text('Decisão registrada'), findsOneWidget);
  });
}

class _Host extends StatelessWidget {
  const _Host({required this.gateway, required this.logger});

  final BackendSchedulePendencyGateway gateway;
  final AppLogger logger;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: TextButton(
          key: const Key('open-review'),
          onPressed: () => showDialog<void>(
            context: context,
            builder: (context) =>
                SchedulePendencyReviewDialog(gateway: gateway, logger: logger),
          ),
          child: const Text('Abrir revisão'),
        ),
      ),
    );
  }
}

class _PendencyGateway implements BackendSchedulePendencyGateway {
  bool empty = false;
  Object? listError;
  Object? decideError;
  List<PythonSchedulePendency> extra = const [];
  int listCalls = 0;
  final decisions = <(String, PythonScheduleDecision)>[];

  PythonSchedulePendency get _base => const PythonSchedulePendency(
    id: 'pend-1',
    courseId: 'course-1',
    courseCode: 'DCC203',
    courseName: 'POO',
    currentSchedule: 'seg 07:30 (2 aulas)',
    newSchedule: 'qua 10:00 (2 aulas)',
    reason: 'manual_schedule_diverged',
    status: 'pending',
  );

  PythonSchedulePendency _resolved(
    PythonSchedulePendency pendency,
    PythonScheduleDecision decision,
  ) => PythonSchedulePendency(
    id: pendency.id,
    courseId: pendency.courseId,
    courseCode: pendency.courseCode,
    courseName: pendency.courseName,
    currentSchedule: pendency.currentSchedule,
    newSchedule: pendency.newSchedule,
    reason: pendency.reason,
    status: 'resolved',
    decision: decision.wire,
  );

  final Map<String, PythonScheduleDecision> _resolvedById = {};

  @override
  Future<List<PythonSchedulePendency>> listSchedulePendencies() async {
    listCalls++;
    if (listError case final error?) throw error;
    final base = _resolvedById.containsKey(_base.id)
        ? _resolved(_base, _resolvedById[_base.id]!)
        : _base;
    if (empty) return [...extra];
    return [base, ...extra];
  }

  @override
  Future<PythonSchedulePendency> decideSchedulePendency(
    String pendencyId, {
    required PythonScheduleDecision decision,
  }) async {
    if (decideError case final error?) throw error;
    decisions.add((pendencyId, decision));
    _resolvedById[pendencyId] = decision;
    return _resolved(_base, decision);
  }
}

class _Logger implements AppLogger {
  final events = <String>[];
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
  }
}
