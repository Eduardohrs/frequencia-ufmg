# Segurança

## Relato responsável

Não abra uma issue pública para uma vulnerabilidade. Use **Security → Advisories →
New draft security advisory** no GitHub do projeto para enviar o relato de forma
privada.

## Fronteiras de confiança

- O cliente Android/web e seus dados de entrada são não confiáveis.
- Firebase Authentication prova identidade; as regras do Firestore autorizam cada
  usuário somente em `users/{uid}/...`.
- Firebase App Check atesta a instância do cliente antes de qualquer rota Python
  autenticada;
  ele reduz abuso, mas não substitui autenticação nem autorização.
- O backend Python deriva o usuário exclusivamente do token Firebase verificado e
  acessa o Firestore com esse mesmo token, mantendo as Security Rules no caminho.
- O TablesDB do Appwrite guarda somente limites e provas anti-replay derivados,
  nunca dados acadêmicos, credenciais Firebase ou conteúdo do usuário.
- Respostas futuras da UFMG/Moodle serão tratadas como dados externos não confiáveis.
- GitHub Actions só recebe credenciais pelos Secrets do repositório; ações externas
  são fixadas por SHA.

## Dados e segredos

- E-mail, identificadores de usuário e localização são dados pessoais e devem ser
  coletados somente quando necessários ao controle de frequência.
- Tokens, cookies, senhas e credenciais nunca entram em logs ou no Git.
- Chaves públicas de configuração dos clientes Firebase podem ser versionadas;
  contas de serviço, keystores e chaves privadas não podem.
- O cache local contém uma réplica dos dados acadêmicos, isolada pelo UID, mas não é
  backup nem cofre de credenciais. O usuário deve tratar o aparelho e o perfil do
  navegador como parte da sua fronteira de segurança.
- Exportação, restauração e exclusão integral pelo usuário são requisitos do gate de
  privacidade antes do beta; até lá, o produto não deve prometer recuperação após
  exclusão ou corrupção do Firestore.

## Controles automatizados

Toda pull request passa por análise estática, testes, cobertura integral do código
executável, auditoria de dependências Python, Codecov e Gitleaks. A `main` rejeita
push direto, force push, exclusão e merge sem o `Quality Gate` verde.

Um teste do repositório exige SHA completo em todas as referências de Actions que
controlamos. A imposição global do GitHub não pode ser ativada enquanto a Action do
Flutter usar internamente uma referência por tag; ativá-la impede o job de iniciar.
Dependabot monitora semanalmente os pacotes Dart, npm, os dois projetos Python e
GitHub Actions.

## Limites aceitos neste checkpoint

- O plano Spark não oferece backup, restauração ou PITR gerenciado do Firestore.
  Nenhum desses recursos deve ser ativado porque exigiria Blaze e poderia cobrar.
- A cópia privada manual existente é apenas uma referência de recuperação anterior
  a mudanças arriscadas; não oferece RPO contínuo. O plano de recuperação completo
  está descrito em `docs/backup-recovery.md`.
- Uma CSP estrita ainda não é imposta: o cliente Flutter, o login Google e o App
  Check dependem de origens externas que precisam ser validadas juntas para não
  bloquear autenticação. Até esse teste, permanecem HSTS, `nosniff`, bloqueio de
  frames, política de referência e política de permissões.
- Linhas anti-replay e de rate limit carregam vencimento lógico, mas a limpeza
  física periódica do TablesDB ainda deve ser fechada junto das cotas e retenção
  antes do beta.
