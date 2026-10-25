enum CourseModality {
  inPerson('in_person', 'Presencial'),
  online('online', 'Online');

  const CourseModality(this.code, this.label);
  final String code;
  final String label;

  static CourseModality fromCode(Object? code) => switch (code) {
    null || 'in_person' => inPerson,
    'online' => online,
    _ => throw const FormatException('Invalid course modality'),
  };
}

enum CourseAttendancePolicy {
  required('required', 'Com chamada'),
  noCall('no_call', 'Sem chamada');

  const CourseAttendancePolicy(this.code, this.label);
  final String code;
  final String label;

  static CourseAttendancePolicy fromCode(Object? code) => switch (code) {
    null || 'required' => required,
    'no_call' => noCall,
    _ => throw const FormatException('Invalid course attendance policy'),
  };
}
