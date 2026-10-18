import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';
import 'package:frequencia_ufmg/features/ufmg/material_cache_card.dart';

void main() {
  testWidgets('shows actionable native states without stale history', (
    tester,
  ) async {
    MaterialDownloadProgress? retried;
    MaterialDownloadProgress? dismissed;
    final downloads = [
      for (final state in MaterialDownloadState.values)
        MaterialDownloadProgress(
          id: state.name,
          name: '${state.name}.pdf',
          state: state,
          downloaded: state == MaterialDownloadState.running ? 25 : 0,
          total: state == MaterialDownloadState.running ? 100 : 0,
          failureCode: state == MaterialDownloadState.failed ? 'timeout' : '',
        ),
      const MaterialDownloadProgress(
        id: 'upstream',
        name: 'upstream.pdf',
        state: MaterialDownloadState.failed,
        downloaded: 0,
        total: 10,
        failureCode: 'upstream_503',
      ),
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MaterialCacheCard(
            files: const [],
            downloads: downloads,
            onOpen: (_) {},
            onRemove: (_) {},
            onRetry: (download) => retried = download,
            onDismiss: (download) => dismissed = download,
            onClear: () {},
          ),
        ),
      ),
    );

    expect(find.text('2 em andamento'), findsOneWidget);
    expect(find.text('Na fila'), findsOneWidget);
    expect(find.text('Baixando'), findsOneWidget);
    expect(find.text('Concluído'), findsNothing);
    expect(
      find.text('Falhou: o Moodle demorou para responder'),
      findsOneWidget,
    );
    expect(find.text('Cancelado'), findsNothing);
    expect(find.text('Falhou: resposta HTTP 503'), findsOneWidget);
    await tester.tap(find.byKey(const Key('material-download-retry-failed')));
    expect(retried?.id, 'failed');
    await tester.tap(find.byKey(const Key('material-download-dismiss-failed')));
    expect(dismissed?.id, 'failed');
  });
}
