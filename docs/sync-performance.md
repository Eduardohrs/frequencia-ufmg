# Ledger de performance da sincronização Moodle

Baseline medida de uma execução real autenticada em 2026-11-25
(`operation_id=sync-hoi5z6p8qg-7rtfsx`): **51,495 ms (51.495 s) de parede**, HTTP 200.

| Estágio | Baseline (ms) | Detalhe medido |
| --- | --- | --- |
| SIGA | 2.625 | 1x `GET /siga-ws/.../WsMatriculas` (1.140 ms) |
| Moodle (pai) | 45.030 | ver abaixo |
| Firestore | 12.672 | 106 leituras + 17 escritas (maiores grupos: materialCatalog 27, syncState 21, activitySnapshots 18, meetings 14) |

Dentro do estágio Moodle (baseline): 10x `core_course_get_enrolled_courses_by_timeline_classification`
(8.522 ms acumulados), 10x `core_courseformat_get_state` (5.841 ms), 8x
`core_course_get_updates_since` (5.628 ms), 2x `core_course_get_contents`
(1.594 ms), 2x `mod_quiz_get_quizzes_by_courses` (1.725 ms), 11x fallback HTML
`GET /mod/quiz/view.php` (13.234 ms; motivo `missing_bulk_fields` — `description`
e `attachments` ausentes no bulk; 6x FIS086 + 5x UNI001), 2x
`core_calendar_get_calendar_monthly_view` com 43 eventos correspondidos, estágio
de atividades 32.058 ms (115 entradas, 104 detalhes reutilizados, 9 snapshots
atualizados, concorrência 4). Planos do Diário: 5 inalterados, 1 conflito manual
preservado (ELE631).

**Regra deste ledger:** tempo acumulado de requisições concorrentes não é tempo
de parede. Nenhum número abaixo afirma um novo tempo de parede; a parede só
volta a ser medida em uma execução real autenticada após o deploy.

## Experimentos nesta branch

| # | Mudança | Evidência | Resultado | Decisão |
| --- | --- | --- | --- | --- |
| A | Cache por sync de descoberta/estado: chave `(sha256 do token, termo)` para matrículas e `(sha256, termo, course_id)` para estados; uma resposta de `core_courseformat_get_state` parseada nos dois pontos de vista (materiais e atividades); tampas `MAX_DISCOVERY_CACHE_ENTRIES`/`MAX_ACTIVITY_PAGE_CACHE`; limpeza quando o digest do token muda | `tests/test_sync_discovery_cache.py`, replay em `tests/test_sync_replay_benchmark.py` | matrículas 10→1 por termo e estados 10→1 lote por termo no replay; 115 entradas e 11 quizzes preservados | keep |
| B | Fallback HTML dos 11 quizzes mantido (o cliente exibe `description` e lista `attachments` para download); memo por `(termo, source_id, kind)` evita página duplicada quando o mesmo módulo aparece em curso canônico e metaturma; contadores `fallback_by_kind`/`fallback_reasons` no resumo | `tests/test_sync_replay_benchmark.py` (11 páginas, `missing_bulk_fields`) | 11 páginas no replay, sem duplicar; nenhum endpoint estruturado novo foi inventado (gate de evidência de autenticação) | keep fallback bounded |
| C | Calendário: nenhuma chamada removida (os 2 `monthly_view` continuam necessários para eventos gerais); histograma `moodle_calendar_event_kinds` (kind, matched/unmatched, ids únicos) | `tests/test_moodle_date_import.py`, replay do calendário (43/43) | 43 eventos preservados; histograma evidenciado | keep + observabilidade |
| D | Firestore: snapshot por disciplina carregado 1x e passado à captura; estado do `syncState` lido no máximo 1x por disciplina e reutilizado em `run(state=...)`; `persist_success_batch` grava os sucessos adiados em 1 commit (fallback para patch individual); contadores em `sync_read_cache` | `tests/test_sync_discovery_cache.py` | no replay: `catalog_reads=0`, `snapshot_reads=10`, 1 commit de política | keep |
| E | Replay/benchmark a partir da forma da run gravada + este ledger | `tests/test_sync_replay_benchmark.py` | contagens de chamadas e dados preservados asserted; tempo de parede não afirmado | keep |
| F | Descoberta combinada: o estado de cada curso já parseado para o catálogo também entrega o índice de atividades em memória; a captura não repete `discover/list_activities` por disciplina. A lista de atividades é transitória e não entra no catálogo persistido. | `tests/test_moodle_content_discovery.py`, `tests/test_sync_replay_benchmark.py` | replay preserva 115 entradas sem uma segunda leitura do índice; contrato do catálogo continua somente com materiais | keep |
| G | `batchGet` para documentos `materialCatalog/current` conhecidos e pool HTML padrão 8 (limite 8 já existente). O lote reduz requests REST de documentos conhecidos; o pool reduz ondas do fallback quiz sem descartar descrição/anexos. | `tests/test_firestore_rest.py`, `tests/test_moodle_material_catalog_repository.py`, `tests/test_course_activity_concurrency.py` | fakes verificam nomes/missing e os detalhes do fallback continuam preservados; a parede real ainda exige uma nova execução autenticada | keep + medir |

## Critérios de reversão

Reverter o cache do experimento A se uma run real mostrar perda de eventos de
calendário, entradas de atividade ou detalhes reutilizados, ou se o memo
sobreviver a uma troca de token (chaves incluem o digest do token e são
limpadas em `_connect`). Reverter o lote do experimento D se um commit rejeitado
não cair no fallback individual. Nada nesta branch altera semântica de
persistência: snapshots antigos nunca são substituídos por dados vazios e a
falha continua best-effort por disciplina.
