import 'dart:math';

import 'package:flutter/material.dart';

import 'course_month_calendar.dart';

class CourseDateRangePickerDialog extends StatefulWidget {
  const CourseDateRangePickerDialog({
    required this.initialMonth,
    required this.firstDate,
    required this.lastDate,
    required this.highlightedWeekdays,
    this.initialRange,
    super.key,
  });

  final DateTime initialMonth;
  final DateTime firstDate;
  final DateTime lastDate;
  final Set<int> highlightedWeekdays;
  final DateTimeRange? initialRange;

  @override
  State<CourseDateRangePickerDialog> createState() =>
      _CourseDateRangePickerDialogState();
}

class _CourseDateRangePickerDialogState
    extends State<CourseDateRangePickerDialog> {
  late DateTime _month;
  DateTime? _start;
  DateTime? _end;
  DateTime? _hovered;

  @override
  void initState() {
    super.initState();
    _month = DateTime(widget.initialMonth.year, widget.initialMonth.month);
    _start = widget.initialRange?.start;
    _end = widget.initialRange?.end;
  }

  DateTime? get _previewEnd {
    if (_end != null) return _end;
    if (_start != null && _hovered != null && !_hovered!.isBefore(_start!)) {
      return _hovered;
    }
    return null;
  }

  void _select(DateTime date) {
    setState(() {
      if (_start == null || _end != null) {
        _start = date;
        _end = null;
      } else if (date.isBefore(_start!)) {
        _start = date;
      } else {
        _end = date;
      }
      _hovered = null;
    });
  }

  void _moveMonth(int delta) =>
      setState(() => _month = DateTime(_month.year, _month.month + delta));

  bool _canMove(int delta, int monthCount) {
    final candidate = DateTime(_month.year, _month.month + delta);
    final latestShown = DateTime(
      candidate.year,
      candidate.month + monthCount,
      0,
    );
    return !latestShown.isBefore(widget.firstDate) &&
        !candidate.isAfter(widget.lastDate);
  }

  @override
  Widget build(BuildContext context) {
    final availableWidth = MediaQuery.sizeOf(context).width - 32;
    final dialogWidth = min(720.0, availableWidth);
    final twoMonths = dialogWidth >= 680;
    final monthCount = twoMonths ? 2 : 1;
    final previewEnd = _previewEnd;
    final teachingDays = _start == null || previewEnd == null
        ? 0
        : _countTeachingDays(_start!, previewEnd, widget.highlightedWeekdays);
    final calendarHeight = twoMonths ? 340.0 : 320.0;
    return AlertDialog(
      insetPadding: const EdgeInsets.all(16),
      title: const Text('Período das aulas'),
      content: SizedBox(
        width: dialogWidth,
        height: min(
          calendarHeight + 96,
          MediaQuery.sizeOf(context).height - 180,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Clique no primeiro e no último dia.'),
            const SizedBox(height: 8),
            Row(
              children: [
                const Icon(Icons.circle, size: 10),
                const SizedBox(width: 6),
                const Expanded(child: Text('Dia em que há aula')),
                if (_start != null && previewEnd == null)
                  const Text('Escolha o último dia')
                else if (previewEnd != null)
                  Text(
                    '$teachingDays ${teachingDays == 1 ? 'dia' : 'dias'} '
                    'de aula no intervalo',
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                IconButton(
                  tooltip: 'Mês anterior',
                  onPressed: _canMove(-1, monthCount)
                      ? () => _moveMonth(-1)
                      : null,
                  icon: const Icon(Icons.chevron_left),
                ),
                const Spacer(),
                IconButton(
                  tooltip: 'Próximo mês',
                  onPressed: _canMove(1, monthCount)
                      ? () => _moveMonth(1)
                      : null,
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
            Flexible(
              child: SizedBox(
                height: calendarHeight,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: _monthView(_month)),
                    if (twoMonths) ...[
                      const SizedBox(width: 20),
                      Expanded(
                        child: _monthView(
                          DateTime(_month.year, _month.month + 1),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _start == null || _end == null
              ? null
              : () => Navigator.of(
                  context,
                ).pop(DateTimeRange(start: _start!, end: _end!)),
          child: const Text('Salvar período'),
        ),
      ],
    );
  }

  Widget _monthView(DateTime month) => CourseMonthCalendar(
    month: month,
    firstDate: widget.firstDate,
    lastDate: widget.lastDate,
    start: _start,
    end: _previewEnd,
    highlightedWeekdays: widget.highlightedWeekdays,
    onSelect: _select,
    onHover: (date) => setState(() => _hovered = date),
  );
}

int _countTeachingDays(DateTime start, DateTime end, Set<int> weekdays) {
  var count = 0;
  for (
    var day = start;
    !day.isAfter(end);
    day = day.add(const Duration(days: 1))
  ) {
    if (weekdays.contains(day.weekday)) count++;
  }
  return count;
}
