import 'campus_detector.dart';

/// Approximate areas for personal attendance, not official property boundaries.
/// Rectangles are chosen here with deliberately generous margins, using public
/// reference points from Wikidata (CC0) and UFMG's own location pages, checked
/// 2026-10-27. These are not copied map contours or official property boundaries.
/// No maps, geocoding services or network requests are used at runtime.
abstract final class CampusAreas {
  // Q132140, revision 2558195491: -19.8690878, -43.9663841.
  static final defaultArea = CampusArea(
    id: 'pampulha',
    name: 'Campus Pampulha',
    south: -19.888,
    north: -19.858,
    west: -43.980,
    east: -43.953,
  );

  static final List<CampusArea> values = List.unmodifiable([
    defaultArea,
    // UFMG Faculty of Medicine's own location section (Alfredo Balena, 190):
    // https://www.medicina.ufmg.br/ reference -19.9245609, -43.9313758.
    // Q5428838 is deliberately NOT used: its coordinate incorrectly points to
    // Pampulha rather than the school's published address in the city center.
    CampusArea(
      id: 'saude',
      name: 'Campus Saúde',
      south: -19.927,
      north: -19.922,
      west: -43.933,
      east: -43.926,
    ),
    // UFMG publishes the campus reference -16.6853399, -43.8445957 at:
    // https://www.ufmg.br/semanadoconhecimento/2017/localizacao/
    // Address confirmed by https://www.ufmg.br/montesclaros/historico/ .
    // Generous rectangle includes the teaching area and the campus farm.
    CampusArea(
      id: 'montes_claros',
      name: 'Campus Montes Claros',
      south: -16.693,
      north: -16.663,
      west: -43.854,
      east: -43.834,
    ),
    // Q5428829, revision 2541495363: -19.925667, -43.936686.
    CampusArea(
      id: 'direito',
      name: 'Faculdade de Direito',
      south: -19.927,
      north: -19.924,
      west: -43.938,
      east: -43.935,
    ),
    // Q10274572, revision 2482336269: -19.932588438856126, -43.932262406747334.
    CampusArea(
      id: 'arquitetura',
      name: 'Escola de Arquitetura',
      south: -19.935,
      north: -19.931,
      west: -43.934,
      east: -43.930,
    ),
    // Q105062226: Casa do Padre Toledo, -21.110949, -44.176467.
    // Broad central-area estimate, not a surveyed outline of the cultural sites.
    CampusArea(
      id: 'tiradentes',
      name: 'Campus Cultural de Tiradentes',
      south: -21.115,
      north: -21.107,
      west: -44.181,
      east: -44.172,
    ),
  ]);

  // Unknown/unconfigured areas stay explicit; never silently use Pampulha when
  // a caller requests another campus, which could turn an unknown into absence.
  static CampusArea? find(String id) {
    for (final area in values) {
      if (area.id == id) return area;
    }
    return null;
  }
}
