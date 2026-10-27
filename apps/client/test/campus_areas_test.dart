import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/domain/campus_detector.dart';

void main() {
  test('Pampulha is the default and each configured area has a stable ID', () {
    expect(CampusAreas.defaultArea.id, 'pampulha');
    expect(
      CampusAreas.values.map((a) => a.id).toSet().length,
      CampusAreas.values.length,
    );
    for (final area in CampusAreas.values) {
      expect(CampusAreas.find(area.id), same(area));
    }
    expect(CampusAreas.find('unknown'), isNull);
    expect(() => CampusAreas.values.clear(), throwsUnsupportedError);
  });

  test('each approximate rectangle contains its public reference point', () {
    final points = {
      'pampulha': GeoPoint(-19.8690878, -43.9663841),
      'saude': GeoPoint(-19.924560886606738, -43.931375784875286),
      'montes_claros': GeoPoint(-16.685339868157754, -43.8445956539673),
      'direito': GeoPoint(-19.925667, -43.936686),
      'arquitetura': GeoPoint(-19.932588438856126, -43.932262406747334),
      'tiradentes': GeoPoint(-21.110949, -44.176467),
    };
    for (final area in CampusAreas.values) {
      expect(area.contains(points[area.id]!), isTrue);
      expect(area.contains(GeoPoint(-23.55, -46.63)), isFalse);
    }
    expect(points.length, CampusAreas.values.length);
    // Independent UFMG reference agrees with Pampulha's Wikidata point.
    expect(
      CampusAreas.defaultArea.contains(
        GeoPoint(-19.86906198215927, -43.96641397153314),
      ),
      isTrue,
    );
    // The incorrect Medicina item cannot silently make Saúde overlap Pampulha.
    expect(
      CampusAreas.find('saude')!.contains(GeoPoint(-19.871904, -43.966248)),
      isFalse,
    );
    // Small central units must not inherit Pampulha's much larger extent.
    final pampulha = CampusAreas.defaultArea;
    for (final id in ['direito', 'arquitetura']) {
      final area = CampusAreas.find(id)!;
      expect(
        area.north - area.south,
        lessThan(pampulha.north - pampulha.south),
      );
      expect(area.east - area.west, lessThan(pampulha.east - pampulha.west));
    }
  });
}
