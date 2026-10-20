import 'package:flutter/material.dart';

@immutable
class CourseIdentity {
  const CourseIdentity({
    required this.color,
    required this.symbol,
    required this.label,
  });

  final Color color;
  final String symbol;
  final String label;

  static const _identities = <CourseIdentity>[
    CourseIdentity(color: Color(0xFF187A4B), symbol: 'Σ', label: 'Exatas'),
    CourseIdentity(color: Color(0xFF2667A8), symbol: '∿', label: 'Circuitos'),
    CourseIdentity(color: Color(0xFFA45725), symbol: '{}', label: 'Computação'),
    CourseIdentity(color: Color(0xFF7952A3), symbol: '◇', label: 'Formação'),
    CourseIdentity(color: Color(0xFFA13D54), symbol: '○', label: 'Estudos'),
    CourseIdentity(color: Color(0xFF3A7378), symbol: '△', label: 'Disciplina'),
  ];

  factory CourseIdentity.fromCode(String code) {
    final normalized = code.trim().toUpperCase();
    if (normalized.startsWith('MAT')) return _identities[0];
    if (normalized.startsWith('ELE')) return _identities[1];
    if (normalized.startsWith('DCC') || normalized.startsWith('PDS')) {
      return _identities[2];
    }
    final hash = normalized.codeUnits.fold<int>(0, (sum, unit) => sum + unit);
    return _identities[3 + (hash % 3)];
  }

  @override
  bool operator ==(Object other) =>
      other is CourseIdentity &&
      color == other.color &&
      symbol == other.symbol &&
      label == other.label;

  @override
  int get hashCode => Object.hash(color, symbol, label);
}

class CourseMark extends StatelessWidget {
  const CourseMark({required this.code, this.size = 44, super.key});

  final String code;
  final double size;

  @override
  Widget build(BuildContext context) {
    final identity = CourseIdentity.fromCode(code);
    return Semantics(
      label: '${identity.label}, $code',
      image: true,
      child: ExcludeSemantics(
        child: Container(
          width: size,
          height: size,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: identity.color.withValues(alpha: .14),
            borderRadius: BorderRadius.circular(size * .3),
            border: Border.all(color: identity.color.withValues(alpha: .35)),
          ),
          child: Text(
            identity.symbol,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: identity.color,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
      ),
    );
  }
}
