import 'academic_records.dart';

final class AcademicPeriod {
  const AcademicPeriod({
    required this.term,
    required this.startsOn,
    required this.endsOn,
  });

  factory AcademicPeriod.current(DateTime date) => AcademicPeriod.forTerm(
    '${date.year}-${date.month <= DateTime.june ? 1 : 2}',
  );

  factory AcademicPeriod.forTerm(String term) {
    final match = RegExp(r'^(\d{4})-([12])$').firstMatch(term);
    if (match == null) throw FormatException('invalid academic term: $term');
    final year = int.parse(match.group(1)!);
    final semester = int.parse(match.group(2)!);
    return AcademicPeriod(
      term: term,
      startsOn: DateTime.utc(
        year,
        semester == 1 ? DateTime.january : DateTime.july,
      ),
      endsOn: DateTime.utc(
        year,
        semester == 1 ? DateTime.june : DateTime.december,
        semester == 1 ? 30 : 31,
      ),
    );
  }

  final String term;
  final DateTime startsOn;
  final DateTime endsOn;

  AcademicPeriod get next {
    final parts = term.split('-');
    final year = int.parse(parts.first);
    return AcademicPeriod.forTerm(
      parts.last == '1' ? '$year-2' : '${year + 1}-1',
    );
  }

  int get sequence {
    final parts = term.split('-');
    return int.parse(parts.first) * 2 + int.parse(parts.last) - 1;
  }
}

final class AcademicPeriodPolicy {
  AcademicPeriodPolicy(DateTime now)
    : _now = now,
      current = AcademicPeriod.current(now);

  final DateTime _now;
  final AcademicPeriod current;

  List<String> get allowedTerms => [current.term, current.next.term];

  bool allows(String term) => allowedTerms.contains(term);

  bool isExpired(CourseRecord course) {
    final coursePeriod = AcademicPeriod.forTerm(course.term);
    if (coursePeriod.sequence >= current.sequence) return false;
    final effectiveEnd = course.endsOn ?? coursePeriod.endsOn;
    final deletionDate = DateTime.utc(
      effectiveEnd.year,
      effectiveEnd.month,
      effectiveEnd.day,
    ).add(const Duration(days: 30));
    final today = DateTime.utc(_now.year, _now.month, _now.day);
    return !today.isBefore(deletionDate);
  }
}
