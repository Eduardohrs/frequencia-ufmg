import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_period.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';

void main() {
  test('uses civil half-years as the provisional academic calendar', () {
    final first = AcademicPeriod.current(DateTime.utc(2026, 3, 10));
    final second = AcademicPeriod.current(DateTime.utc(2026, 9, 28));

    expect(first.term, '2026-1');
    expect(first.startsOn, DateTime.utc(2026));
    expect(first.endsOn, DateTime.utc(2026, 6, 30));
    expect(second.term, '2026-2');
    expect(second.startsOn, DateTime.utc(2026, 7));
    expect(second.endsOn, DateTime.utc(2026, 12, 31));
  });

  test('allows only the current and next terms', () {
    final policy = AcademicPeriodPolicy(DateTime.utc(2026, 9, 28));

    expect(policy.allowedTerms, ['2026-2', '2027-1']);
    expect(policy.allows('2026-2'), isTrue);
    expect(policy.allows('2027-1'), isTrue);
    expect(policy.allows('2026-1'), isFalse);
    expect(policy.allows('2027-2'), isFalse);
  });

  test('rejects malformed academic terms', () {
    expect(() => AcademicPeriod.forTerm('2026-3'), throwsFormatException);
  });

  test('expires a previous course thirty days after its effective end', () {
    final course = _course(term: '2026-1', endsOn: DateTime.utc(2026, 6, 30));

    expect(
      AcademicPeriodPolicy(DateTime.utc(2026, 7, 29)).isExpired(course),
      isFalse,
    );
    expect(
      AcademicPeriodPolicy(DateTime.utc(2026, 7, 30)).isExpired(course),
      isTrue,
    );
  });

  test('never expires the current or next term', () {
    final policy = AcademicPeriodPolicy(DateTime.utc(2026, 9, 28));

    expect(
      policy.isExpired(
        _course(term: '2026-2', endsOn: DateTime.utc(2026, 7, 1)),
      ),
      isFalse,
    );
    expect(policy.isExpired(_course(term: '2027-1')), isFalse);
  });

  test('falls back to the term end for legacy courses without dates', () {
    final policy = AcademicPeriodPolicy(DateTime.utc(2026, 7, 30));

    expect(policy.isExpired(_course(term: '2026-1')), isTrue);
  });
}

CourseRecord _course({required String term, DateTime? endsOn}) => CourseRecord(
  id: 'course',
  code: 'DCC203',
  name: 'POO',
  workload: 60,
  term: term,
  startsOn: endsOn == null ? null : DateTime.utc(2026),
  endsOn: endsOn,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
);
