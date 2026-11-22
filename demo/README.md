# Frequência UFMG — produto acadêmico PF-02-AGENDA

Python 3.11 ou superior. Usa somente a biblioteca padrão, incluindo SQLite. Não exige contas ou internet.
Extraia o ZIP, abra o terminal **dentro da pasta `demo/`** e execute um comando:

```text
python web.py
```

O navegador abre automaticamente quando o terminal é interativo. Se não abrir,
acesse **http://127.0.0.1:8878**. O servidor aceita conexões apenas do próprio
computador. Na tela vazia, clique em **Usar dados de exemplo** para preencher
uma disciplina fictícia, dois registros de frequência e uma prova. O botão só aparece quando
não há disciplinas; **Ajustes → Apagar dados da demo** permite recomeçar.
Para preencher manualmente, use **Nova disciplina** e informe nome, código,
chamadas, aulas por encontro e adicionar cada data da grade. A matéria aparece
imediatamente na lista pelo nome. Abra uma data e escolha a situação de
frequência; a mesma linha oferece **Corrigir** depois de um registro. O cartão
mostra faltas usadas, limite, saldo e frequência quando todas as aulas tiverem
sido resolvidas. No celular, use o seletor **Disciplina** para alternar entre
matérias; não é necessário memorizar códigos. **Agenda** guarda provas e
trabalhos vinculados à matéria e mostra o ano de cada prazo.
Use **Corrigir data** no encontro se a data da grade estiver errada: a presença,
as faltas e os totais ficam preservados, inclusive após reabrir o navegador.
Essa correção existe na interface visual; o menu de terminal conserva o fluxo
principal de cadastro e frequência.

**Renomear** altera só o nome. Em **Ajustes**, **Apagar dados da demo** requer
digitar `APAGAR`; cancelar preserva tudo. O botão **Executar testes** roda os
testes em bancos temporários e mostra o resultado nessa mesma tela. A mesma
verificação pode ser executada no terminal com um único comando:

```text
python -m unittest discover -v
```

Se o banco local estiver temporariamente indisponível, a tela mostra o erro e
**Tentar novamente**. Se já houver dados carregados, eles permanecem visíveis
com aviso de que podem estar desatualizados.

O navegador só mostra os dados e envia as ações. `web.py` transforma essas ações
em chamadas às classes de `models.py`, onde ficam validações e cálculos. `database.py`
salva no arquivo `frequencia.db`, que permanece ao fechar e reabrir. Para encerrar
o servidor, volte ao terminal e pressione Ctrl+C.

Também é possível usar a mesma demo pelo terminal com `python main.py`. Nesse
menu, as matérias aparecem por nome e número; o código é só referência. A opção
8 reinicia os dados após `APAGAR`. Terminal e navegador compartilham o mesmo
banco local quando executados na mesma pasta.

## Exemplo a partir do zero

- Crie `DEMO01`, nome `Disciplina de teste`, duas chamadas e duas aulas por encontro.
- Informe as datas `02/11/2026,04/11/2026,09/11/2026,11/11/2026`.
- Registre `presente` em `02/11/2026`: zero faltas, seis aulas pendentes.
- Registre `ausente` em `04/11/2026`: duas faltas usadas, limite de duas e saldo zero.
- Tente cadastrar `demo01` novamente: o cadastro deve ser rejeitado, sem apagar o primeiro.

Cada aula vale 50 minutos. Cancelamentos saem da base; aula sem chamada entra
com zero faltas. O limite é 25% da grade, arredondado para baixo. O percentual
só aparece quando não há pendências. Uma chamada não desconta atraso/saída
antecipada; duas descontam metade do encontro. Uma aula não admite duas chamadas.

`models.py` contém as regras, `database.py` a persistência SQLite, `web.py` a
ponte HTTP local, `web/` a interface visual, `main.py` o menu alternativo,
`test_*.py` os testes independentes. O botão de exemplo usa as mesmas classes
Python do cadastro manual e grava a amostra numa transação SQLite.
Esta pasta é uma versão independente para avaliação de POO.
O aplicativo completo está em https://github.com/Eduardohrs/frequencia-ufmg.
