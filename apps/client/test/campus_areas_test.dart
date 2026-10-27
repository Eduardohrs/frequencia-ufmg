import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/domain/campus_detector.dart';

void main() {
  test('six areas use immutable bounded sets of simple rectangles', () {
    expect(CampusAreas.defaultArea.id, 'pampulha');
    expect(CampusAreas.values.length, 6);
    expect(CampusAreas.values.map((a) => a.id).toSet().length, 6);
    for (final area in CampusAreas.values) {
      expect(CampusAreas.find(area.id), same(area));
      expect(area.rectangles.length, inInclusiveRange(1, 3));
      expect(() => area.rectangles.clear(), throwsUnsupportedError);
    }
    expect(CampusAreas.find('unknown'), isNull);
    expect(() => CampusAreas.values.clear(), throwsUnsupportedError);
  });
  test('references, separated sites and campus extremes stay covered', () {
    final references = [
      ('pampulha', -19.8690878, -43.9663841), // Wikidata.
      ('pampulha', -19.86906198215927, -43.96641397153314), // UFMG.
      ('pampulha', -19.8673704, -43.9741342), // CEU.
      ('pampulha', -19.8694067, -43.9709964), // Initial reduced-range gap.
      ('pampulha', -19.8861475, -43.9687), // Southern ecological-station area.
      ('pampulha', -19.8601669, -43.9615),
      ('saude', -19.924560886606738, -43.931375784875286),
      ('saude', -19.9256974, -43.9293),
      ('montes_claros', -16.685339868157754, -43.8445956539673),
      (
        'montes_claros',
        -16.676661970588235,
        -43.83947098823529,
      ), // Junction gap.
      ('montes_claros', -16.6658723, -43.845),
      ('montes_claros', -16.6909443, -43.841),
      ('direito', -19.925667, -43.936686),
      ('arquitetura', -19.932588438856126, -43.932262406747334),
      ('tiradentes', -21.110949, -44.176467), // Museu.
      ('tiradentes', -21.1108059, -44.1768943), // Biblioteca, Padre Toledo158.
      ('tiradentes', -21.1090808, -44.1771411), // Quatro Cantos, Direita5.
    ];
    for (final (id, lat, lon) in references) {
      expect(
        CampusAreas.find(id)!.contains(GeoPoint(lat, lon)),
        isTrue,
        reason: '$id must include $lat,$lon',
      );
    }
  });
  test('reduced ranges exclude unrelated points without losing CEU', () {
    for (final (id, lat, lon) in [
      ('pampulha', -19.8659620, -43.9711239), // Mineirao, OSM178504792.
      ('direito', -19.9268, -43.9378),
      ('arquitetura', -19.9346, -43.9338),
      ('tiradentes', -21.1105, -44.1742),
      ('saude', -19.871904, -43.966248), // Incorrect Medicina Wikidata point.
    ]) {
      expect(
        CampusAreas.find(id)!.contains(GeoPoint(lat, lon)),
        isFalse,
        reason: '$id must exclude $lat,$lon',
      );
    }
    for (final area in CampusAreas.values) {
      expect(area.contains(GeoPoint(-23.55, -46.63)), isFalse);
    }
  });
}
