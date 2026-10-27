import 'campus_detector.dart';

/// Approximate ranges for personal attendance, not surveyed property boundaries.
/// Audited 2026-10-27 against public UFMG references, Wikidata(CC0) and
/// OpenStreetMap contributors(ODbL): https://www.openstreetmap.org/copyright .
/// A few rectangles cover separated sites without a detailed polygon engine.
/// The app performs only local numeric comparisons: no map, API or new dependency.
abstract final class CampusAreas {
  // Main teaching site + ecological station + CEU. Mineirao center is excluded.
  // UFMG reference: https://www.ufmg.br/semanadoconhecimento/2017/localizacao/
  // OSM reference audit: relations3892557 and5462802; Wikidata Q132140.
  static final defaultArea = CampusArea(
    id: 'pampulha',
    name: 'Campus Pampulha',
    rectangles: [
      CampusRectangle(
        south: -19.8745,
        north: -19.8597,
        west: -43.9708,
        east: -43.9553,
      ),
      CampusRectangle(
        south: -19.8866,
        north: -19.8689,
        west: -43.9773,
        east: -43.9647,
      ),
      CampusRectangle(
        south: -19.8704,
        north: -19.8636,
        west: -43.9765,
        east: -43.9716,
      ),
    ],
  );

  static final List<CampusArea> values = List.unmodifiable([
    defaultArea,
    // UFMG reference: https://www.medicina.ufmg.br/ (Alfredo Balena190).
    // OSM reference audit: way314938410. Q5428838 points to Pampulha and is NOT used.
    CampusArea(
      id: 'saude',
      name: 'Campus Saúde',
      rectangles: [
        CampusRectangle(
          south: -19.9262,
          north: -19.9226,
          west: -43.9316,
          east: -43.927,
        ),
      ],
    ),
    // UFMG reference: https://www.ufmg.br/semanadoconhecimento/2017/localizacao/
    // Two broad ranges cover the mapped teaching site and farm without a diagonal polygon.
    // OSM reference audit: relation7824059.
    CampusArea(
      id: 'montes_claros',
      name: 'Campus Montes Claros',
      rectangles: [
        CampusRectangle(
          south: -16.678,
          north: -16.6654,
          west: -43.8524,
          east: -43.839,
        ),
        CampusRectangle(
          south: -16.6915,
          north: -16.6768,
          west: -43.8483,
          east: -43.8358,
        ),
      ],
    ),
    // Wikidata Q5428829; OSM audit way29442348; unit plus roughly40m margins.
    CampusArea(
      id: 'direito',
      name: 'Faculdade de Direito',
      rectangles: [
        CampusRectangle(
          south: -19.9265,
          north: -19.9251,
          west: -43.9374,
          east: -43.9361,
        ),
      ],
    ),
    // Wikidata Q10274572; OSM audit way133000266; unit plus roughly40m margins.
    CampusArea(
      id: 'arquitetura',
      name: 'Escola de Arquitetura',
      rectangles: [
        CampusRectangle(
          south: -19.9341,
          north: -19.9321,
          west: -43.9331,
          east: -43.9314,
        ),
      ],
    ),
    // Museu + Biblioteca together, with Quatro Cantos in a separated rectangle.
    // Official addresses: https://www.ufmg.br/campustiradentes/fale-conosco-2/
    // Wikidata Q105062226; OSM audit ways1042400242/1042400245/1167234133.
    CampusArea(
      id: 'tiradentes',
      name: 'Campus Cultural de Tiradentes',
      rectangles: [
        CampusRectangle(
          south: -21.1116,
          north: -21.1104,
          west: -44.1774,
          east: -44.1759,
        ),
        CampusRectangle(
          south: -21.1095,
          north: -21.1086,
          west: -44.1776,
          east: -44.1766,
        ),
      ],
    ),
  ]);

  // Unknown area must not silently fall back to Pampulha and imply absence.
  static CampusArea? find(String id) {
    for (final area in values) {
      if (area.id == id) return area;
    }
    return null;
  }
}
