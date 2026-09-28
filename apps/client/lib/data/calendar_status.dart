enum SessionCalendarStatus {
  scheduled('scheduled'),
  cancelled('cancelled'),
  holiday('holiday'),
  makeup('makeup');

  const SessionCalendarStatus(this.code);

  final String code;

  static SessionCalendarStatus fromCode(String code) => values.firstWhere(
    (value) => value.code == code,
    orElse: () => throw ArgumentError.value(code, 'code'),
  );
}
