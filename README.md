# Frequência UFMG

Sistema pessoal para acompanhamento de frequência e rotina acadêmica de estudantes da UFMG.

## Estrutura

- backend/: API Python e regras de negócio usadas pelo produto e pela avaliação de POO.
- apps/client/: aplicativo Flutter para Android e web.
- docs/: decisões de arquitetura e documentação do projeto.
- firebase.json: configuração de Hosting, Firestore e emuladores locais.

## Qualidade

Toda alteração deve ser feita em uma branch e enviada por pull request. O CI executa
análise estática, testes, varredura de segredos e exige 100% de cobertura no backend
e no cliente. O Codecov recebe os relatórios por OIDC, sem token armazenado no
repositório, e complementa a verificação com a cobertura do código alterado.
Dependabot, auditoria Python e varredura de segredos monitoram vulnerabilidades e
credenciais. As GitHub Actions externas são fixadas por SHA para impedir alterações
silenciosas em tags.

Consulte CONTRIBUTING.md para o fluxo de desenvolvimento.

## Desenvolvimento local

### Backend

    cd backend
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev]"
    pytest

### Cliente Flutter

    cd apps/client
    flutter pub get
    flutter test --coverage
    flutter run -d chrome

### Firebase

O projeto usa `frequencia-ufmg-eduardo`. As configurações públicas dos clientes
Android e web ficam versionadas; credenciais administrativas permanecem fora do
repositório.

    firebase emulators:start

## Releases

Uma tag no formato `vMAJOR.MINOR.PATCH` cria uma GitHub Release com APK assinado e
pacote web. Os arquivos da release permanecem disponíveis até que a própria release
seja removida; os artefatos temporários de teste continuam expirando em um dia.

    git tag -a v1.0.0 -m "Release 1.0.0"
    git push origin v1.0.0

Consulte `SECURITY.md` e `docs/observability.md` para os contratos de segurança e
telemetria.

As regras funcionais de presença, atraso, saída antecipada e faltas por sessão estão
definidas em `docs/attendance-rules.md`.
