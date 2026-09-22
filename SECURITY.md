# Segurança

## Relato responsável

Não abra uma issue pública para uma vulnerabilidade. Use **Security → Advisories →
New draft security advisory** no GitHub do projeto para enviar o relato de forma
privada.

## Fronteiras de confiança

- O cliente Android/web e seus dados de entrada são não confiáveis.
- Firebase Authentication prova identidade; as regras do Firestore autorizam cada
  usuário somente em `users/{uid}/...`.
- Respostas futuras da UFMG/Moodle serão tratadas como dados externos não confiáveis.
- GitHub Actions só recebe credenciais pelos Secrets do repositório; ações externas
  são fixadas por SHA.

## Dados e segredos

- E-mail, identificadores de usuário e localização são dados pessoais e devem ser
  coletados somente quando necessários ao controle de frequência.
- Tokens, cookies, senhas e credenciais nunca entram em logs ou no Git.
- Chaves públicas de configuração dos clientes Firebase podem ser versionadas;
  contas de serviço, keystores e chaves privadas não podem.
- A exclusão da conta deverá apagar os documentos do usuário quando o armazenamento
  acadêmico for implementado.

## Controles automatizados

Toda pull request passa por análise estática, testes, cobertura integral do código
executável, auditoria de dependências Python, Codecov e Gitleaks. A `main` rejeita
push direto, force push, exclusão e merge sem o `Quality Gate` verde.
