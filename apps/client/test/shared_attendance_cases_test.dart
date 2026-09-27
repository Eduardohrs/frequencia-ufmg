import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('shared attendance cases cover every supported input combination', () {
    final repositoryRoot = Directory.current.parent.parent;
    final file = File('${repositoryRoot.path}/shared/attendance_cases.json');
    final document =
        jsonDecode(file.readAsStringSync()) as Map<String, Object?>;
    final cases = (document['casos']! as List<Object?>)
        .cast<Map<String, Object?>>();

    expect(document['versao'], 1);
    expect(cases, hasLength(45));
    expect(cases.map((item) => item['id']).toSet(), hasLength(45));

    const expectedConfigurations = {'1/1', '2/1', '2/2', '4/1', '4/2'};
    const expectedSituations = {
      'presente',
      'chegou_atrasado',
      'saiu_mais_cedo',
      'ausente',
      'pendente',
    };
    const expectedPingPairs = {
      'no_campus/no_campus',
      'no_campus/fora',
      'no_campus/indisponivel',
      'fora/no_campus',
      'fora/fora',
      'fora/indisponivel',
      'indisponivel/no_campus',
      'indisponivel/fora',
      'indisponivel/indisponivel',
    };

    final actualConfigurations = cases
        .map((item) => '${item['aulas']}/${item['chamadas']}')
        .toSet();
    expect(actualConfigurations, expectedConfigurations);
    expect(
      cases.every((item) => expectedSituations.contains(item['situacao'])),
      isTrue,
    );
    expect(
      cases.every((item) => item['faltas'] == null || item['faltas'] is int),
      isTrue,
    );
    for (final configuration in expectedConfigurations) {
      final actualPingPairs = cases
          .where(
            (item) => '${item['aulas']}/${item['chamadas']}' == configuration,
          )
          .map((item) => '${item['primeiro_ping']}/${item['segundo_ping']}')
          .toSet();
      expect(actualPingPairs, expectedPingPairs, reason: configuration);
    }
  });
}
