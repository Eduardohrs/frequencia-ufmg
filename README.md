# Frequência UFMG

Sistema pessoal para acompanhamento de frequência e rotina acadêmica de estudantes da UFMG.

## Estrutura

- backend/: API Python e regras de negócio usadas pelo produto e pela avaliação de POO.
- apps/client/: aplicativo Flutter para Android e web.
- docs/: decisões de arquitetura e documentação do projeto.
- firebase.json: configuração de Hosting, Firestore e emuladores locais.

## Qualidade

Toda alteração deve ser feita em uma branch e enviada por pull request. O CI executa análise estática, testes e exige 100% de cobertura no backend e no cliente. O Codecov complementa a verificação com relatório e cobertura do código alterado.

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
