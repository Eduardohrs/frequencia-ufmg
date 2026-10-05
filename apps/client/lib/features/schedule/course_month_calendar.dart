import 'package:flutter/material.dart';

class CourseMonthCalendar extends StatelessWidget {
  const CourseMonthCalendar({
    required this.month,
    required this.firstDate,
    required this.lastDate,
    required this.start,
    required this.end,
    required this.highlightedWeekdays,
    required this.onSelect,
    required this.onHover,
    super.key,
  });

  final DateTime month;
  final DateTime firstDate;
  final DateTime lastDate;
  final DateTime? start;
  final DateTime? end;
  final Set<int> highlightedWeekdays;
  final ValueChanged<DateTime> onSelect;
  final ValueChanged<DateTime> onHover;

  @override
  Widget build(BuildContext context) {
    final first = DateTime(month.year, month.month);
    final offset = first.weekday - 1;
    final days = DateTime(month.year, month.month + 1, 0).day;
    final rowCount = ((offset + days) / 7).ceil();
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '${_months[month.month - 1]} ${month.year}',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            for (final label in ['S', 'T', 'Q', 'Q', 'S', 'S', 'D'])
              Expanded(child: Center(child: Text(label))),
          ],
        ),
        const SizedBox(height: 4),
        SizedBox(
          height: rowCount * 38,
          child: GridView.builder(
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 7,
              mainAxisExtent: 38,
            ),
            itemCount: rowCount * 7,
            itemBuilder: (context, index) {
              final day = index - offset + 1;
              if (day < 1 || day > days) return const SizedBox.shrink();
              return _day(context, DateTime(month.year, month.month, day));
            },
          ),
        ),
      ],
    );
  }

  Widget _day(BuildContext context, DateTime date) {
    final enabled = !date.isBefore(firstDate) && !date.isAfter(lastDate);
    final boundary = _sameDay(date, start) || _sameDay(date, end);
    final inRange =
        start != null &&
        end != null &&
        !date.isBefore(start!) &&
        !date.isAfter(end!);
    final teachingDay = inRange && highlightedWeekdays.contains(date.weekday);
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: inRange,
      label: '${_dateLabel(date)}${teachingDay ? ', dia de aula' : ''}',
      child: MouseRegion(
        onEnter: enabled ? (_) => onHover(date) : null,
        child: Padding(
          padding: const EdgeInsets.all(2),
          child: InkWell(
            key: ValueKey('date-${_dateId(date)}'),
            borderRadius: BorderRadius.circular(20),
            onTap: enabled ? () => onSelect(date) : null,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              decoration: BoxDecoration(
                color: boundary
                    ? colors.primary
                    : teachingDay
                    ? colors.secondaryContainer
                    : inRange
                    ? colors.primaryContainer
                    : null,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Stack(
                alignment: Alignment.center,
                children: [
                  Text(
                    '${date.day}',
                    style: TextStyle(
                      color: !enabled
                          ? colors.onSurface.withValues(alpha: 0.35)
                          : boundary
                          ? colors.onPrimary
                          : null,
                      fontWeight: teachingDay ? FontWeight.w700 : null,
                    ),
                  ),
                  if (teachingDay)
                    Positioned(
                      bottom: 2,
                      child: Icon(Icons.circle, size: 5, color: colors.primary),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

bool _sameDay(DateTime value, DateTime? other) =>
    other != null &&
    value.year == other.year &&
    value.month == other.month &&
    value.day == other.day;

String _dateId(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

String _dateLabel(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}/'
    '${date.month.toString().padLeft(2, '0')}/${date.year}';

const _months = [
  'Janeiro',
  'Fevereiro',
  'Março',
  'Abril',
  'Maio',
  'Junho',
  'Julho',
  'Agosto',
  'Setembro',
  'Outubro',
  'Novembro',
  'Dezembro',
];
