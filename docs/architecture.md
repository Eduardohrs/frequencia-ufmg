# Arquitetura inicial

O Frequência UFMG é um único produto com clientes Flutter para Android e web e um backend Python responsável pelas regras de negócio.

## Componentes

- Flutter: interface, autenticação do usuário e captura dos pings no Android.
- Backend Python: domínio, classificação de presença, cálculos, validações e API.
- Firebase Authentication: login Google.
- Cloud Firestore: dados sincronizados por usuário.
- Firebase Hosting: publicação do cliente web.
- Firebase Analytics: eventos operacionais sanitizados no Android e na web.
- Firebase Crashlytics: crashes e erros não tratados no Android.
- Logs JSON em `stdout`: diagnóstico local do backend, sem conteúdo do usuário.
- Appwrite TablesDB: somente rate limit e anti-replay do backend, com chaves
  derivadas e expiração; não armazena dados acadêmicos.

As leituras interativas usam Firestore/cache diretamente para não bloquear a UI em
cold starts. As escritas de grade e sessões passam pelo Python, que verifica o token
Firebase e o App Check e acessa o Firestore com a identidade do próprio usuário.
Credenciais administrativas nunca ficam no aplicativo ou no repositório.

## Fluxo de presença

1. O cliente recebe o horário da sessão.
2. O Android coleta um ping 20 minutos após o início e outro 20 minutos antes do término.
3. Os registros são enviados ao backend.
4. O domínio Python classifica a sessão e calcula as faltas.
5. O resultado sincronizado é exibido no Android e na web.

Quando a coleta falhar, o registro permanece pendente e pode ser corrigido manualmente.

## Observabilidade e custo

O projeto permanece sem conta de faturamento vinculada. A observabilidade usa
somente Analytics e Crashlytics, produtos sem custo do Firebase. O backend não
registra corpos, parâmetros de consulta, cabeçalhos, tokens, e-mails ou dados de
localização. Cada requisição recebe apenas um identificador aleatório de correlação.

Serviços que exigem faturamento, como Cloud Run, não devem ser habilitados sem uma
decisão explícita de arquitetura e autorização do responsável pelo projeto.

## Recuperação

O Git e as releases preservam código e artefatos, mas não os dados acadêmicos. O
cache local é uma réplica para disponibilidade e não constitui backup. Como backup,
PITR e exportação gerenciada do Firestore exigem Blaze, o MVP mantém faturamento
desativado e usa cópias privadas somente antes de mudanças de risco. Antes do beta,
o aplicativo deve oferecer exportação versionada, validação e restauração explícita
dos dados do próprio usuário; consulte `docs/backup-recovery.md`.

## CI, builds e releases

As pull requests executam verificações rápidas, cobertura, scanner de segredos e o
build web. O build Android, mais demorado, fica no workflow manual `Build test
artifacts`, executado pela aba Actions do GitHub. Os artefatos de teste expiram em
um dia para limitar o uso de armazenamento.

Uma GitHub Release de produção só deve ser ativada após configurar uma chave de
assinatura Android guardada em GitHub Secrets. APKs de teste usam assinatura de
debug e não devem ser distribuídos como versão final.
