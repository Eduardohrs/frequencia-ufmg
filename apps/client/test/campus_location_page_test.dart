import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/campus_location.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/domain/campus_detector.dart';
import 'package:frequencia_ufmg/features/attendance/campus_location_page.dart';
import 'fixtures/campus_location_fixture.dart';

void main() {
  Future<void> show(
    WidgetTester tester,
    _Selection store,
    _Check check,
    CampusTestLogger logger,
  ) => tester.pumpWidget(
    MaterialApp(
      home: CampusLocationPage(
        selection: store,
        checker: check,
        logger: logger,
      ),
    ),
  );
  Future<void> select(WidgetTester tester, String name) async {
    await tester.tap(find.byKey(const Key('campus-selector')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text(name).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text(name).last);
    await tester.pumpAndSettle();
  }

  testWidgets('defaults to Pampulha without automatically obtaining location', (
    tester,
  ) async {
    final check = _Check();
    final logger = CampusTestLogger();
    await show(tester, _Selection(), check, logger);
    await tester.pumpAndSettle();
    expect(find.text('Campus Pampulha'), findsOneWidget);
    expect(check.calls, isEmpty);
    expect(logger.events.any((e) => e.$1 == 'campus_selection_loaded'), isTrue);
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(check.calls, ['pampulha']);
    expect(find.text('Dentro da área selecionada'), findsOneWidget);
    expect(find.textContaining('5 m'), findsOneWidget);
  });

  testWidgets(
    'restores selection, persists a change and clears obsolete results',
    (tester) async {
      final store = _Selection()..saved = 'direito';
      final check = _Check();
      final logger = CampusTestLogger();
      await show(tester, store, check, logger);
      await tester.pumpAndSettle();
      expect(find.text('Faculdade de Direito'), findsOneWidget);
      await tester.tap(find.text('Verificar minha localização'));
      await tester.pumpAndSettle();
      expect(find.text('Fora da área selecionada'), findsOneWidget);
      await select(tester, 'Campus Pampulha');
      expect(store.saved, 'pampulha');
      expect(find.text('Fora da área selecionada'), findsNothing);
      expect(
        logger.events.any(
          (e) =>
              e.$1 == 'campus_selection_saved' &&
              e.$2?['campus_id'] == 'pampulha',
        ),
        isTrue,
      );
    },
  );

  testWidgets(
    'unknown or unreadable saved selection requires explicit recovery',
    (tester) async {
      final store = _Selection()..saved = 'unknown';
      await show(tester, store, _Check(), CampusTestLogger());
      await tester.pumpAndSettle();
      expect(find.textContaining('recuperar'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('campus-check')))
            .onPressed,
        isNull,
      );
      store.saved = null;
      await tester.tap(find.text('Tentar novamente'));
      await tester.pumpAndSettle();
      expect(find.text('Campus Pampulha'), findsOneWidget);
    },
  );

  testWidgets('failed save keeps previous choice and can be retried', (
    tester,
  ) async {
    final store = _Selection()..saveError = StateError('disk unavailable');
    final logger = CampusTestLogger()..failLogging = true;
    await show(tester, store, _Check(), logger);
    await tester.pumpAndSettle();
    await select(tester, 'Faculdade de Direito');
    expect(find.text('Campus Pampulha'), findsOneWidget);
    expect(find.textContaining('salvar'), findsOneWidget);
    store.saveError = null;
    await select(tester, 'Faculdade de Direito');
    expect(store.saved, 'direito');
    expect(find.textContaining('salvar'), findsNothing);
  });

  testWidgets('check errors and poor readings stay recoverable', (
    tester,
  ) async {
    final check = _Check()
      ..error = const CampusCheckFailure(
        'permission_denied',
        'permissions',
        'pampulha',
      );
    await show(tester, _Selection(), check, CampusTestLogger());
    await tester.pumpAndSettle();
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Permita'), findsOneWidget);
    check.error = StateError('unexpected');
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Não foi possível consultar'), findsOneWidget);
    check
      ..error = null
      ..accuracy = 500;
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(find.text('Localização inconclusiva'), findsOneWidget);
    check
      ..accuracy = 5
      ..old = true;
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(find.textContaining('antiga'), findsOneWidget);
    check
      ..old = false
      ..future = true;
    await tester.tap(find.text('Verificar minha localização'));
    await tester.pumpAndSettle();
    expect(find.textContaining('horário'), findsOneWidget);
  });

  testWidgets(
    'busy state prevents duplicate checks and late completion is safe',
    (tester) async {
      final check = _Check()..pending = Completer<CampusDetection>();
      await show(tester, _Selection(), check, CampusTestLogger());
      await tester.pumpAndSettle();
      await tester.tap(find.text('Verificar minha localização'));
      await tester.tap(find.text('Verificar minha localização'));
      await tester.pump();
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('campus-check')))
            .onPressed,
        isNull,
      );
      expect(check.calls.length, 1);
      await tester.pumpWidget(const SizedBox());
      check.pending!.complete(check.result(CampusAreas.defaultArea));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('late load after disposal cannot update a dead page', (
    tester,
  ) async {
    final store = _Selection()..pendingRead = Completer<String?>();
    await show(tester, store, _Check(), CampusTestLogger());
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    store.pendingRead!.completeError(StateError('late read'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'a failed pending save after leaving does not touch a disposed page',
    (tester) async {
      final store = _Selection()..pendingSave = Completer<void>();
      await show(tester, store, _Check(), CampusTestLogger());
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('campus-selector')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Faculdade de Direito').last);
      await tester.pump();
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      store.pendingSave!.completeError(StateError('late disk failure'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'small screen and large text remain scrollable without overflow',
    (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final previous = WidgetController.hitTestWarningShouldBeFatal;
      WidgetController.hitTestWarningShouldBeFatal = true;
      addTearDown(
        () => WidgetController.hitTestWarningShouldBeFatal = previous,
      );
      final checker = _Check();
      await tester.pumpWidget(
        MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(2)),
            child: child!,
          ),
          home: CampusLocationPage(
            selection: _Selection(),
            checker: checker,
            logger: CampusTestLogger(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await select(tester, 'Campus Cultural de Tiradentes');
      await tester.ensureVisible(find.byKey(const Key('campus-check')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('campus-check')));
      await tester.pumpAndSettle();
      expect(checker.calls, ['tiradentes']);
      expect(find.text('Fora da área selecionada'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}

class _Selection implements CampusSelectionGateway {
  String? saved;
  Object? saveError;
  Completer<String?>? pendingRead;
  Completer<void>? pendingSave;
  @override
  Future<String?> read() async =>
      pendingRead == null ? saved : pendingRead!.future;
  @override
  Future<void> save(String id) async {
    await pendingSave?.future;
    if (saveError case final e?) throw e;
    saved = id;
  }
}

class _Check implements CampusCheckGateway {
  final calls = <String>[];
  Object? error;
  double accuracy = 5;
  bool old = false, future = false;
  Completer<CampusDetection>? pending;
  CampusDetection result(CampusArea area) {
    final now = DateTime.utc(2026, 10, 27);
    return CampusDetector(
      area: area,
      maxAge: const Duration(minutes: 2),
      maxAccuracyMeters: 100,
    ).classify(
      LocationReading(
        point: GeoPoint(-19.869, -43.966),
        accuracyMeters: accuracy,
        recordedAt: old
            ? now.subtract(const Duration(minutes: 3))
            : future
            ? now.add(const Duration(minutes: 1))
            : now,
      ),
      now: now,
    );
  }

  @override
  Future<CampusDetection> check(CampusArea area) async {
    calls.add(area.id);
    if (error case final e?) throw e;
    return pending == null ? result(area) : pending!.future;
  }
}
