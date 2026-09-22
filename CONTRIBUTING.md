# Contribuição

## Fluxo obrigatório

1. Atualize a main local.
2. Crie uma branch com prefixo feat/, fix/, test/, docs/ ou chore/.
3. Faça commits pequenos e objetivos.
4. Abra uma pull request.
5. Aguarde o status Quality Gate ficar verde.
6. Faça merge por squash e remova a branch.

Push direto, force push e exclusão da `main` são bloqueados pela proteção remota.
Toda mudança passa por pull request e pelo `Quality Gate`, inclusive alterações de
administradores do repositório.

## Critérios para merge

- Testes passando.
- Cobertura total de linhas em 100% para todo código executável alterado.
- Análise estática sem erros.
- Secret Scan passando sem nenhum segredo, credencial, chave privada, keystore ou
  arquivo de conta de serviço versionado.
- Descrição da PR preenchida com comportamento, testes e riscos.
