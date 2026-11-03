import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/cached_academic_overview_repository.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

CourseRecord course({
  String? nickname,
  String name = 'Programação Orientada a Objetos',
}) => CourseRecord(
  id: 'poo',
  code: 'DCC203',
  name: name,
  nickname: nickname,
  workload: 60,
  term: '2026-2',
  createdAt: DateTime.utc(2026, 11, 3),
  updatedAt: DateTime.utc(2026, 11, 3),
);

void main() {
  test('human names preserve official identity and compact Unicode safely', () {
    expect(course().displayName, 'Programação Orientada a Objetos');
    expect(course().shortName, 'POO');
    expect(course(nickname: 'Minha POO').shortName, 'Minha POO');
    expect(course(name: 'Circuitos Elétricos Avançados II').shortName, 'CEAII');
    expect(
      course(name: '😀 Laboratório de Programação Experimental').shortName,
      '😀LPE',
    );
    expect(course(name: 'de ' * 12).shortName, 'de ' * 12);
    expect(course(nickname: 'POO').code, 'DCC203');
    expect(
      compareCourseNames(course(nickname: 'A'), course(nickname: 'Z')),
      lessThan(0),
    );
    expect(compareCourseNames(course(), course()), 0);
  });
  test(
    'Firestore and API accept legacy records and validate personal names',
    () {
      for (final nickname in [null, 'POO', 'x' * 48]) {
        final original = course(nickname: nickname);
        expect(
          CourseRecord.fromFirestore('poo', original.toFirestore()).nickname,
          nickname,
        );
        final api = PythonCourse(
          id: original.id,
          code: original.code,
          name: original.name,
          nickname: nickname,
          workload: 60,
          term: original.term,
          startsOn: null,
          endsOn: null,
          createdAt: original.createdAt,
          updatedAt: original.updatedAt,
        );
        expect(PythonCourse.fromJson(api.toJson()).nickname, nickname);
        expect(
          PythonCourse.fromJson(api.toJson()..remove('nickname')).nickname,
          isNull,
        );
        for (final invalid in ['', ' ', ' POO', 'POO ', 'x' * 49, 42]) {
          expect(
            () => PythonCourse.fromJson({...api.toJson(), 'nickname': invalid}),
            throwsFormatException,
          );
          expect(
            () => CourseRecord.fromFirestore('poo', {
              ...original.toFirestore(),
              'nickname': invalid,
            }),
            throwsFormatException,
          );
        }
      }
    },
  );
  test(
    'offline cache retains the label without leaking across accounts',
    () async {
      var owner = 'alice';
      final cache = _Cache();
      final remote = _Remote();
      final repository = CachedAcademicOverviewRepository(
        remote: remote,
        cache: cache,
        currentUserId: () => owner,
        logger: _Logger(),
      );
      await repository.loadOverview();
      remote.fails = true;
      final offline = await repository.loadOverview();
      expect(offline.courses.single.displayName, 'Minha POO');
      expect(offline.isLocalCopy, isTrue);
      owner = 'bob';
      expect(await repository.loadCachedOverview(), isNull);
      owner = 'alice';
      expect(
        (await repository.loadCachedOverview())!.courses.single.nickname,
        'Minha POO',
      );
    },
  );
}

class _Cache implements AcademicOverviewCache {
  final values = <String, String>{};
  @override
  Future<String?> read(String id) async => values[id];
  @override
  Future<void> write(String id, String value) async {
    values[id] = value;
  }

  @override
  Future<void> remove(String id) async {
    values.remove(id);
  }
}

class _Remote implements AcademicOverviewRepository {
  bool fails = false;
  @override
  Future<AcademicOverviewSnapshot> loadOverview() async {
    if (fails) throw StateError('offline');
    return AcademicOverviewSnapshot(
      courses: [course(nickname: 'Minha POO')],
      sessionsByCourse: {'poo': []},
    );
  }
}

class _Logger implements AppLogger {
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {}
  @override
  Future<void> recordError(
    Object error,
    StackTrace stack, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {}
}
