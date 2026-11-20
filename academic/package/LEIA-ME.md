# Frequência UFMG — entrega acadêmica

- **Versão:** PF-02-AGENDA
- **Integrante:** Eduardo Henrique Rodrigues Silva
- **Disciplina:** APPOO, 2026/2

Este ZIP reúne as duas etapas:

- `relatorio/Frequencia_UFMG_Produto_Final.pdf`: escopo, contratos, regras, diagramas e implementação.
- `relatorio/Frequencia_UFMG_Verificacao.pdf`: matriz de cenários e resultados observados.
- `demo/`: interface local em HTML, programa Python independente, testes, banco SQLite vazio e gerador de dados fictícios.
- `evidencias/unittest.txt`: saída integral da última execução dos testes.

Para usar ou testar, comece em `demo/README.md`. Entre em `demo/`, rode `python web.py`
e abra http://127.0.0.1:8878. Python 3.11 ou superior é suficiente; o programa
não precisa de conta, internet nem pacotes externos. Há também um menu opcional
com `python main.py`. As duas interfaces compartilham as mesmas classes e o mesmo
SQLite local. O reset exige a confirmação `APAGAR`.
Na interface visual, **Corrigir data** muda a data de um encontro sem perder a
presença registrada. A agenda de provas e trabalhos não muda com essa ação.
