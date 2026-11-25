# Auditoria de tempo e linhagem da sincronização acadêmica

Este documento define como decompor uma execução de sincronização sem confundir
tempo de rede, processamento local e persistência. Ele também registra por que
o calendário e as atividades existem como fontes distintas no produto.

## Fluxo observado

```text
gatilho HTTP
  -> criação/retomada do job
  -> worker
     -> sessão SIGA + matrículas
        -> cursos e horários locais
     -> sessão Moodle (reutilizada por termo)
        -> calendário mensal estruturado
           -> parse -> correspondência curso/evento -> datas locais
        -> descoberta de cursos/estados
           -> candidatos de materiais -> catálogo local
        -> índice de atividades por disciplina
           -> detecção incremental -> endpoint em lote -> fallback HTML, se necessário
           -> snapshot de atividades/anexos
     -> planos oficiais do Diário
        -> parse -> avaliações -> prévia de reconciliação -> aplicação segura
     -> finalização do job
```

Cada seta é uma etapa mensurável. O worker continua executando as disciplinas
independentes quando uma delas falha; a falha é registrada no item da disciplina
e a execução geral só falha quando o contrato marca a dependência como fatal.

## Origem, transformação, armazenamento e uso

| Origem/dataset | Transformação | Persistência | Consumidores |
| --- | --- | --- | --- |
| SIGA `WsMatriculas` / `courses_and_schedule` | validação e importação idempotente | `courses`, `schedules` | lista de disciplinas, horários e vínculo com Moodle |
| Moodle calendário mensal / `calendar_events` | parse, correspondência por código/termo e deduplicação | `academicDates` | agenda geral e datas da disciplina |
| Moodle estados de curso / `resource_candidates` | seleção canônica, metaturma e status de vínculo | catálogo de materiais | materiais da disciplina e seleção do plano |
| Moodle índice de atividades / `activity_metadata` | comparação incremental com snapshot anterior | snapshot por disciplina | agenda de atividades, materiais e modo offline |
| Moodle `core_course_get_contents` / `activity_details` | parse em lote de descrições, datas e anexos | snapshot por disciplina | detalhe da atividade e download direto |
| Diário de Classe / `assessments_and_schedule` | parse do plano, importação de avaliações e reconciliação | plano e datas da disciplina | cronograma e revisão de alterações |

## Calendário versus atividades: não são a mesma coisa

Uma atividade do Moodle pode possuir `duedate` e, portanto, aparecer também no
calendário. Ainda assim, os dois fluxos têm contratos diferentes:

- o calendário é a fonte de **eventos da agenda**: aulas, prazos e eventos que
  não são módulos de atividade;
- o snapshot é a fonte de **detalhes da atividade**: nome, tipo, descrição,
  anexos, URL e estado incremental/offline;
- o plano do Diário é a fonte oficial de avaliações e cronograma quando está
  publicado; suas avaliações entram na mesma coleção de datas por meio da
  reconciliação.

A chave de deduplicação local é `course_id + source_id + term`. O calendário
continua dono das datas de agenda; o snapshot continua dono dos detalhes da
atividade. Assim, o mesmo prazo pode ser exibido uma vez na agenda sem perder o
link e os anexos da atividade.

Há uma redundância real, agora medida e explicitamente documentada: a descoberta
de conteúdo chama `discover(..., activities=False)` por termo, enquanto o índice
de atividades chama `discover(..., activities=True)` por disciplina. A primeira
é necessária para catalogar materiais e escolher o plano; a segunda é necessária
para o índice incremental. O código não remove essa chamada especulativamente:
os eventos de consumidor e quantidade de chamadas permitem comparar uma futura
cache compartilhada com evidência.

## Como ler os tempos sem somar duas vezes

Os tempos são durações de parede (`duration_ms`) usando relógio monotônico. Um
evento pai inclui seus filhos; portanto, use um nível por vez:

1. `academic_sync_stage_completed/failed` mostra o tempo do estágio do worker
   (`siga`, `moodle`, `moodle_date_import`, `moodle_activity_snapshots`, etc.).
2. `moodle_http_request_completed` e `siga_http_request_completed` mostram a
   chamada externa, incluindo leitura da resposta; não incluem o parse posterior.
3. `academic_sync_stage_completed` com estágios de parse, correspondência,
   persistência e reconciliação mostra o custo local específico.
4. `firestore_request_completed` mostra cada leitura/escrita, recurso redigido,
   tamanho do corpo, status e duração.

Não some `moodle` + `moodle_date_import` + `moodle_term_calendar` como se fossem
três blocos independentes: os dois últimos estão dentro do primeiro. Para obter
o custo total, use o estágio pai; para localizar a causa, desça para os filhos.

## Eventos de diagnóstico

Os eventos novos preservam correlação e não armazenam senha, cookie, token,
corpo de resposta ou identificador do usuário:

- `siga_http_request_completed`: status, resultado, motivo, bytes e duração da
  resposta de matrículas;
- `moodle_http_request_completed`: host, caminho permitido, método, status,
  motivo, timeout, bytes, tipo de conteúdo e duração;
- `moodle_ajax_batch_completed`: quantidade e nomes dos métodos do lote Moodle,
  bytes e consumidor;
- `moodle_session_connection_created/reused`: custo lógico de criar/reutilizar
  a sessão SAML por termo;
- `moodle_calendar_batch_parse`, `moodle_course_list_parse`,
  `moodle_course_state_parse`, `moodle_activity_updates_parse`,
  `moodle_activity_bulk_parse`, `moodle_activity_module_bulk_parse` e
  `teaching_plan_parse`: custo de cada parser e seu consumidor;
- `moodle_event_unmatched`: evento de calendário que não pôde ser atribuído a
  exatamente uma disciplina;
- `activity_snapshot_course_decision`: por disciplina, informa `reused`,
  `refreshed` ou `failed_retained_previous`, quantidade e duração;
- `academic_sync_lineage`: relação origem→dataset→consumidor e contagens
  (`extracted`, `matched`, `created`, `updated`, `unchanged`, falhas, etc.);
- `firestore_request_completed`: operação, recurso com IDs redigidos, bytes,
  status e duração.

## Consultas operacionais

Os campos podem ser consultados no Appwrite usando a ferramenta/CLI já usada
para os jobs. Exemplos (substitua os placeholders pela configuração local; não
coloque tokens no shell, no README ou neste documento):

```text
filtrar event = academic_sync_stage_completed
agrupar por stage e somar duration_ms

filtrar event = moodle_http_request_completed
agrupar por path, outcome e status_code

filtrar event = activity_snapshot_course_decision
agrupar por course_code e outcome

filtrar event = academic_sync_lineage
comparar dataset, consumer e contagens
```

Para uma execução, primeiro fixe `execution_id`/`operation_id` e o horário do
job. Depois compare os estágios filhos apenas dentro dessa correlação. Se um
campo não existir numa execução antiga, o resultado deve ser marcado como
“não instrumentado”, nunca inferido a partir do tempo total.

## Critérios para a próxima otimização

1. medir o número de chamadas AJAX e o tempo de cada endpoint;
2. medir separadamente rede, parse e Firestore;
3. verificar se a resposta já contém a data necessária antes de repetir uma
   consulta de calendário;
4. testar uma cache compartilhada de descoberta sem alterar a fonte de verdade;
5. comparar a execução anterior e a nova por `stage`, `path`, `course_code` e
   `outcome`; só então remover ou agrupar chamadas.

