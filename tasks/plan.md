# Plano de implementação: Frequência UFMG

## Visão geral

O trabalho restante foi dividido em nove sessões de uso do GPT Plus, cada uma
planejada para consumir aproximadamente uma janela de cinco horas incluindo leitura,
implementação, testes, execução do CI, correções, pull request e merge. Uma sessão
termina com a `main` funcional e demonstrável; itens extras só entram depois que a
entrega mínima estiver verde.

## Escopo consolidado

- Um único produto Flutter para Android e web.
- Login Google e dados sincronizados por usuário no Firebase.
- Uso exclusivo por estudantes da UFMG.
- Cadastro e correção manual sempre disponíveis.
- Sessões com 1, 2 ou 4 aulas de 50 minutos; nunca 3.
- Uma ou duas chamadas configuráveis por sessão.
- Pings automáticos no Android 20 minutos após o início e 20 minutos antes do fim.
- Estar no campus é evidência suficiente; localização por sala não será usada.
- Exibição clara de presenças, faltas consumidas e faltas restantes.
- Importação de disciplinas, horários, avaliações e trabalhos a partir dos sistemas
  UFMG quando tecnicamente possível.
- Aviso e preenchimento manual quando uma informação não puder ser importada.
- Sincronização incremental: para ao completar uma disciplina, respeita backoff e
  desiste após um mês ou quando o usuário preencher manualmente.
- Um arquivo Python concentra as classes de POO exigidas pela disciplina, enquanto o
  aplicativo completo continua sendo apresentado normalmente.

## Decisões de arquitetura

- O produto diário usa Flutter, Firebase Authentication, Firestore, Hosting,
  Analytics e Crashlytics, todos já configurados sem conta de faturamento.
- Enquanto serviços Google que executam Python exigirem faturamento, o domínio de
  produção roda em Dart. O arquivo Python de POO implementa as mesmas regras e ambos
  são validados pelos mesmos casos de teste em JSON, evitando duas regras divergentes.
- O cliente acessa apenas documentos sob `users/{uid}`; regras do Firestore mantêm o
  isolamento entre usuários.
- Senha do MinhaUFMG nunca será armazenada. A etapa de investigação determinará se há
  token renovável oficial; se não houver, a interface solicitará reautenticação sem
  prometer uma sessão permanente impossível.
- A automação de presença existe somente no Android. Web e iOS consomem os resultados
  sincronizados e permitem correção manual.
- Cada etapa usa branch curta, PR, Quality Gate, cobertura de 100% do código executável
  alterado e logs para toda nova operação relevante.

## Etapas

### Etapa 0 — Fundação técnica concluída

**Estado:** concluída.

**Entrega existente:** repositório público protegido, CI, Codecov, scanner de
segredos, Firebase, login Google web/Android, observabilidade sanitizada, APK assinado,
Hosting e workflow de releases.

---

### Etapa 1 — Domínio de frequência e MVP manual

**Objetivo da sessão:** entregar o primeiro produto realmente utilizável sem depender
de automação ou da UFMG.

**Entrega mínima:**

- Criar o arquivo Python de POO com aluno, disciplina, sessão, registro de presença e
  regras de cálculo.
- Criar o domínio equivalente em Dart e casos compartilhados cobrindo sessões de 1,
  2 e 4 aulas, uma ou duas chamadas, atraso, saída antecipada, falta e correção.
- Persistir disciplinas e registros por usuário no Firestore.
- Exibir uma tela básica para cadastrar disciplina, registrar presença/falta e ver
  faltas restantes.

**Critérios de aceitação:**

- O usuário consegue usar o fluxo manual no web e reencontrar os dados após recarregar.
- Uma chamada considera presença se pelo menos um momento confirmar campus; duas
  chamadas distinguem presente, atrasado, saída antecipada e ausente.
- Correções manuais substituem o resultado sem exigir motivo ou histórico de auditoria.

**Verificação:** testes Python e Flutter com os mesmos cenários, regras do Firestore e
teste manual no Hosting.

**Extensão se houver limite:** importação e exportação JSON das disciplinas.

**Dependências:** Etapa 0.

---

### Etapa 2 — Grade semanal e geração de sessões

**Objetivo da sessão:** transformar horários recorrentes em um calendário acadêmico
que alimente o registro manual e a futura automação.

**Entrega mínima:**

- Cadastro de dias, horários, duração em aulas de 50 minutos e número de chamadas.
- Geração das sessões do semestre sem duplicatas.
- Exceções para aula cancelada, reposição e feriado informado manualmente.
- Visões “hoje”, “próximas aulas” e histórico por disciplina.

**Critérios de aceitação:**

- Alterar a grade atualiza apenas sessões futuras ainda não confirmadas.
- Sessões passadas e correções do usuário nunca são apagadas silenciosamente.
- Android e web mostram o mesmo calendário vindo do Firestore.

**Verificação:** testes de fuso `America/Sao_Paulo`, virada de dia, duplicação e
alteração de grade; teste manual em web e Android.

**Extensão se houver limite:** importação manual de grade por texto/CSV.

**Dependências:** Etapa 1.

---

### Etapa 3 — Presença automática no Android

**Objetivo da sessão:** automatizar os dois momentos de presença sem tentar localizar
a sala.

**Entrega mínima:**

- Permissões de localização e definição do perímetro do campus.
- Agendamento de um ping 20 minutos após o início e outro 20 minutos antes do fim.
- Fila local quando estiver sem internet e sincronização posterior.
- Classificação automática usando as regras da Etapa 1 e notificações sobre falhas de
  permissão ou execução.

**Critérios de aceitação:**

- Passar pelo campus em um dos momentos conta como presença nas sessões de uma chamada.
- Nas sessões de duas chamadas, os dois resultados classificam atraso e saída antecipada.
- O app não coleta trilha de localização: guarda apenas momento, resultado dentro/fora
  do campus, precisão necessária e identificador da sessão.

**Verificação:** testes com relógio e localização simulados, reinício do aparelho,
modo offline e teste físico pelo usuário com APK da PR.

**Extensão se houver limite:** tela de diagnóstico de bateria/permissões por fabricante.

**Dependências:** Etapas 1 e 2.

---

### Etapa 4 — Investigação e prova de conceito MinhaUFMG/Moodle

**Objetivo da sessão:** resolver cedo o maior risco externo antes de construir o
sincronizador definitivo.

**Entrega mínima:**

- Mapear login, SSO, cookies, APIs e recursos do Moodle/MinhaUFMG usando uma sessão
  autenticada pelo usuário.
- Confirmar de onde vêm disciplinas, horários, calendário, tarefas e arquivos.
- Construir uma prova de conceito somente leitura que liste ao menos as disciplinas
  atuais ou documentar tecnicamente por que isso não é possível.
- Decidir como renovar a conexão sem armazenar senha.

**Critérios de aceitação:**

- Documento com endpoints, validade da sessão, campos úteis e limites encontrados.
- Nenhuma credencial, cookie ou página privada entra no Git ou nos logs.
- A decisão final distingue claramente integração suportada, scraping tolerável e
  operações que exigirão reautenticação.

**Verificação:** repetição da prova de conceito após fechar e reabrir o aplicativo;
scanner de segredos e revisão de segurança.

**Extensão se houver limite:** protótipo da tela “Conectar MinhaUFMG”.

**Dependências:** Etapa 0; pode ocorrer após a Etapa 1 se houver urgência.

---

### Etapa 5 — Sincronização de disciplinas e horários

**Objetivo da sessão:** substituir o cadastro inicial manual pelos dados encontrados
na Etapa 4, preservando o controle do usuário.

**Entrega mínima:**

- Conectar/desconectar MinhaUFMG e mostrar estado da conexão.
- Importar disciplinas e horários sem duplicar registros manuais.
- Executar sincronização ao abrir o painel apenas quando houver dados pendentes.
- Aplicar backoff, estado por disciplina, encerramento após sucesso e desistência após
  um mês.

**Critérios de aceitação:**

- Um novo semestre importa novas disciplinas sem exigir novamente o login quando o
  mecanismo institucional permitir renovação.
- Falha em uma disciplina não força consultas repetidas nas disciplinas completas.
- O usuário vê último sucesso, próxima tentativa, falha sanitizada e ação manual.

**Verificação:** testes com respostas gravadas e sanitizadas, limites de requisição,
repetição idempotente e fluxo real com a conta do usuário.

**Extensão se houver limite:** reconciliação assistida entre disciplina manual e
disciplina importada.

**Dependências:** Etapas 2 e 4.

---

### Etapa 6 — Trabalhos, provas e fontes estruturadas

**Objetivo da sessão:** importar automaticamente tudo que o Moodle disponibilizar de
forma estruturada.

**Entrega mínima:**

- Importar calendário, tarefas, questionários e eventos com data.
- Associar cada item à disciplina e permitir edição manual.
- Exibir status “completo”, “ainda sem data”, “falhou” ou “preenchido manualmente”.
- Parar de consultar itens completos e retomar somente quando houver evidência de
  mudança ou novo semestre.

**Critérios de aceitação:**

- Repetir a sincronização não cria duplicatas nem desfaz edição manual.
- Itens sem data geram aviso, não uma data inventada.
- A tela inicial mostra os próximos compromissos de todas as disciplinas.

**Verificação:** testes idempotentes com eventos reais sanitizados, alterações de data
e indisponibilidade do Moodle.

**Extensão se houver limite:** notificações configuráveis para prazos próximos.

**Dependências:** Etapa 5.

---

### Etapa 7 — Extração de cronogramas e fallback inteligente

**Objetivo da sessão:** cobrir professores que publicam datas em PDF, texto, arquivo
ou não publicam.

**Entrega mínima:**

- Descobrir textos e arquivos candidatos dentro da disciplina.
- Extrair datas de texto e PDF com indicação da fonte e nível de confiança.
- Pedir confirmação antes de salvar resultado ambíguo.
- Encerrar tentativas quando todas as datas forem encontradas, o usuário preencher
  manualmente ou o prazo de um mês terminar.

**Critérios de aceitação:**

- O sistema nunca apresenta uma extração incerta como verdade confirmada.
- Arquivos e textos sem data produzem aviso claro e não entram em loop.
- A sincronização evita baixar novamente conteúdo que não mudou.

**Verificação:** conjunto de cronogramas sanitizados em formatos diferentes, datas
ambíguas, documento sem datas e edição manual.

**Extensão se houver limite:** reconhecimento de imagens, somente se houver solução
gratuita local e necessidade comprovada.

**Dependências:** Etapa 6.

---

### Etapa 8 — Experiência final web e Android

**Objetivo da sessão:** transformar os fluxos funcionais em uma interface coesa para
uso diário e apresentação.

**Entrega mínima:**

- Dashboard responsivo com aula atual/próxima, faltas restantes e próximos prazos.
- Tela de disciplina com frequência, grade, avaliações, fonte dos dados e correções.
- Navegação, estados vazios, carregamento, erro e acessibilidade básica.
- Diagnóstico de sincronização e automação Android compreensível sem abrir logs.

**Critérios de aceitação:**

- Todos os fluxos principais funcionam em largura de celular e desktop.
- A informação prioritária aparece sem exigir navegação profunda.
- Nenhum erro técnico ou identificador sensível é mostrado ao usuário comum.

**Verificação:** testes de widget, contraste, tamanhos de tela, teclado web e revisão
visual nos dois clientes.

**Extensão se houver limite:** modo escuro e animações discretas.

**Dependências:** Etapas 1–7; pode começar com componentes estáveis antes da Etapa 7.

---

### Etapa 9 — Beta, release e entrega acadêmica

**Objetivo da sessão:** encerrar um ciclo utilizável, recuperável e apresentável.

**Entrega mínima:**

- Testes end-to-end dos fluxos críticos e revisão de regras do Firestore.
- Exportação/exclusão dos dados do usuário, recuperação de falhas e revisão dos logs.
- Correção dos achados críticos/altos de segurança e desempenho.
- Release versionada com APK final e web publicada.
- Material da disciplina de POO: código em um arquivo, diagrama/explicação curta e
  entregas retroativas coerentes com o projeto construído.

**Critérios de aceitação:**

- Um usuário novo completa login, configuração, registro de presença e consulta de
  faltas sem intervenção técnica.
- Um usuário existente troca entre Android e web sem divergência de dados.
- APK atualiza a instalação anterior usando a assinatura estável.
- Demonstração e código de POO correspondem às mesmas regras do produto.

**Verificação:** ensaio completo da apresentação, checklist de release, instalação e
atualização física do APK pelo usuário e smoke test da web publicada.

**Extensão se houver limite:** vídeo curto de demonstração e screenshots da release.

**Dependências:** Etapas 1–8.

## Checkpoints

- **Após Etapa 1:** MVP manual útil e requisitos centrais de POO demonstráveis.
- **Após Etapa 3:** produto de frequência completo sem depender dos sistemas UFMG.
- **Após Etapa 5:** disciplinas e horários sincronizados automaticamente.
- **Após Etapa 7:** rotina acadêmica e avaliações cobertas com fallback manual.
- **Após Etapa 9:** beta instalável, web publicada e trabalho acadêmico pronto.

## Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| MinhaUFMG não oferece token renovável | Alto | Etapa 4 isolada e reautenticação explícita; nunca armazenar senha |
| Android atrasar tarefas em segundo plano | Alto | tolerância temporal, diagnóstico de bateria e correção manual |
| Regras Python e Dart divergirem | Alto | mesmos casos JSON executados nas duas implementações |
| PDFs sem padrão ou datas ausentes | Médio | confiança, confirmação e fallback manual; nunca inventar dados |
| Firestore gratuito atingir limites | Baixo no uso pessoal | leituras incrementais, cache e sincronização somente quando pendente |
| Uma etapa consumir toda a cota antes do merge | Médio | entrega mínima primeiro; extensão somente depois do CI verde |

## Pontos a validar durante a execução

- Mecanismo real de autenticação e renovação de sessão da UFMG.
- Limites exatos do campus usados pelo geofence.
- Fonte oficial ou regra final para feriados e calendário acadêmico.
- Comportamento físico das tarefas em segundo plano no aparelho do usuário.
- Materiais e rubrica exatos das próximas etapas da disciplina de POO.
