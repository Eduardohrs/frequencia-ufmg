"""Gera os relatórios acadêmicos a partir das regras e testes da demo."""

# ruff: noqa: E501

from pathlib import Path

from pdf_layout import (
    VERSION,
    P,
    build,
    class_diagram,
    page,
    section,
    sequence_diagram,
    table,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Preformatted, Spacer


def cenarios(story, titulo, preparo, linhas):
    section(story, titulo, preparo)
    story.append(
        table(
            ["ID", "Regra e entrada", "Esperado", "Observado", "Situação", "Evidência"],
            linhas,
            [1.5 * cm, 4.1 * cm, 5.7 * cm, 5.7 * cm, 1.8 * cm, 6.7 * cm],
            dense="tight",
        )
    )
    story.append(Spacer(1, 0.12 * cm))


def produto():
    s = []
    page(s, "Produto final · APPOO 2026/2", "Frequência UFMG")
    s.append(
        P(
            "<b>Integrante:</b> Eduardo Henrique Rodrigues Silva<br/>"
            "<b>Disciplina:</b> APPOO · Prof.ª Luiza Bernardes Real"
        )
    )
    section(
        s,
        "Problema e público",
        "Ao longo do semestre, o estudante precisa saber quantas faltas já registrou em cada disciplina e quantas ainda cabem no limite de frequência. O sistema organiza os encontros da grade, permite registrar e corrigir a situação de cada aula e apresenta o saldo atualizado. Provas e trabalhos vinculados à disciplina aparecem na agenda para apoiar esse acompanhamento.",
    )
    section(
        s,
        "Escopo da entrega",
        "Esta aplicação reúne o núcleo de controle de frequência em Python: cadastro manual da grade, registro e correção, consulta dos cálculos e agenda de atividades. Uma página local recebe as ações; as classes aplicam as regras e o SQLite conserva os dados entre execuções. O projeto maior, com aplicativo e integrações acadêmicas, está em https://github.com/Eduardohrs/frequencia-ufmg. Aqui, o estudante informa os dados manualmente para que o funcionamento das classes possa ser demonstrado do começo ao fim.",
    )
    section(s, "Funcionalidades")
    s.append(
        table(
            ["ID", "Ação do estudante", "Resultado"],
            [
                (
                    "F01",
                    "Cadastrar disciplina",
                    "Cria a grade com um encontro pendente em cada data.",
                ),
                (
                    "F02",
                    "Registrar frequência",
                    "Resolve uma aula e atualiza as faltas.",
                ),
                (
                    "F03",
                    "Corrigir frequência",
                    "Substitui a situação de uma aula já registrada e recalcula os totais.",
                ),
                (
                    "F04",
                    "Consultar frequência",
                    "Mostra grade, limite, faltas, saldo e percentual quando definido.",
                ),
                (
                    "F05",
                    "Adicionar atividade",
                    "Guarda prova ou trabalho ligado à disciplina.",
                ),
                (
                    "F06",
                    "Consultar agenda",
                    "Lista atividades por data e nome da disciplina.",
                ),
                (
                    "F07",
                    "Renomear disciplina",
                    "Atualiza o nome exibido sem mudar seu código.",
                ),
                (
                    "F08",
                    "Apagar dados da demo",
                    "Reinicia a base após confirmação na página.",
                ),
            ],
            [1.3 * cm, 5.1 * cm, 10.6 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Para executar",
        "Extraia <b>Frequencia_UFMG_Entrega_Final.zip</b>, abra um terminal na pasta <b>demo</b> e execute <b>python web.py</b> com Python 3.11 ou superior. A página abre em http://127.0.0.1:8878. O botão <b>Usar dados de exemplo</b> preenche uma grade para demonstração; <b>Nova disciplina</b> inicia um cadastro próprio.",
    )

    page(s, "Produto final", "Contratos das funcionalidades")
    s.append(
        P(
            "Cada linha indica o que se informa, o resultado da operação e o estado preservado quando a entrada é rejeitada."
        )
    )
    s.append(
        table(
            ["ID", "Condição e entrada", "Sucesso", "Rejeição e estado"],
            [
                (
                    "F01",
                    "Código e nome; 1 ou 2 chamadas; 1, 2 ou 4 aulas de 50 min por encontro; datas distintas. Duas chamadas exigem ao menos 2 aulas.",
                    "Código normalizado; disciplina e um registro pendente por data gravados juntos.",
                    "Código repetido, data ou combinação inválida: nenhuma disciplina ou grade parcial é criada.",
                ),
                (
                    "F02",
                    "Disciplina e data da grade pendente; situação: presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
                    "A situação e as faltas daquela data são gravadas; o resumo é recalculado.",
                    "Data/situação inválida, data já resolvida, versão antiga ou falha de gravação: registro e totais anteriores permanecem.",
                ),
                (
                    "F03",
                    "Data já resolvida; nova situação válida; opção Corrigir.",
                    "Altera o registro da mesma data e recalcula faltas, limite e percentual.",
                    "Data pendente, entrada inválida, versão antiga ou falha de gravação: situação anterior permanece.",
                ),
                (
                    "F04",
                    "Selecionar uma disciplina pelo nome.",
                    "Mostra encontros, faltas usadas, limite, saldo e frequência quando não há pendências.",
                    "Falha de leitura é informada; a consulta não modifica dados.",
                ),
                (
                    "F05",
                    "Disciplina existente; data, tipo prova/trabalho e título.",
                    "Atividade gravada e vinculada à disciplina.",
                    "Disciplina ou dados inválidos, ou falha de escrita: agenda e frequência permanecem iguais.",
                ),
                (
                    "F06",
                    "Abrir Agenda ou o cartão da disciplina.",
                    "Atividades ordenadas por data e, no empate, por inclusão; persistem após reabrir.",
                    "Falha de leitura é informada; a agenda não é alterada.",
                ),
                (
                    "F07",
                    "Disciplina existente; novo nome não vazio.",
                    "Nome salvo e atualizado na lista e na agenda.",
                    "Nome inválido ou falha SQL: nome e demais dados anteriores permanecem.",
                ),
                (
                    "F08",
                    "Em Ajustes, digitar exatamente APAGAR.",
                    "Disciplinas, registros e atividades removidos na mesma transação.",
                    "Outra confirmação ou falha SQL: todos os dados permanecem.",
                ),
            ],
            [1.4 * cm, 5.3 * cm, 5.0 * cm, 5.3 * cm],
            dense="tight",
        )
    )

    page(s, "Produto final", "Regras e exemplo de cálculo")
    section(
        s,
        "Unidade e limite",
        "Uma aula vale 50 minutos. A grade contém datas e quantidade de aulas por encontro; portanto, um encontro de duas aulas vale 100 minutos. A base E soma as aulas dos encontros não cancelados. Pendências entram em E, mas não são presumidas presentes nem ausentes. O limite L é o inteiro inferior de 25% de E: L = E // 4. Faltas usadas A somam apenas registros resolvidos; saldo = máximo(0, L − A). Com todas as aulas resolvidas, frequência = 100 × (E − A) / E. Se E = 0 ou houver pendência, o percentual ainda não é exibido.",
    )
    s.append(
        table(
            ["Situação", "Uma chamada", "Duas chamadas"],
            [
                ("Presente", "0 falta", "0 falta"),
                ("Ausente", "Todas as aulas do encontro", "Todas as aulas do encontro"),
                (
                    "Atrasado ou saiu mais cedo",
                    "0 falta",
                    "Metade das aulas do encontro",
                ),
                ("Sem chamada", "0 falta; conta na base", "0 falta; conta na base"),
                ("Cancelada", "Encontro retirado da base", "Encontro retirado da base"),
            ],
            [5.4 * cm, 5.8 * cm, 5.8 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Exemplo",
        "Quatro encontros de duas aulas formam E = 8 e L = 2. Depois de registrar uma presença e uma ausência, A = 2, restam quatro aulas pendentes e o saldo é zero; ainda não há percentual. Ao marcar os outros dois encontros como presentes, a frequência é 100 × (8 − 2) / 8 = 75%. Corrigir a ausência para presente muda A para zero, o saldo para duas aulas e a frequência para 100%. Marcar um encontro como cancelado retira suas duas aulas da base e recalcula o limite.",
    )
    section(
        s,
        "Correção e datas",
        "Cada data tem um único Registro com a situação atual. A correção valida a nova situação, confirma a escrita no SQLite e então altera esse Registro em memória. A agenda guarda atividades em datas próprias; uma prova não altera a frequência. A grade é definida no cadastro. Uma reposição entra como data dessa grade; para corrigir uma data cadastrada errada, o estudante usa o reinício da demo e cadastra a grade novamente.",
    )

    page(s, "Produto final", "Classes e arquitetura")
    s.append(class_diagram())
    section(
        s,
        "Responsabilidades das classes",
        "ControleAcademico coordena cadastro, busca, agenda e reinício. Disciplina guarda a grade, escolhe uma política de chamada e calcula o resumo. Cada Registro representa a situação atual de uma data; Atividade guarda prova ou trabalho. PoliticaChamada define calcular_faltas(); ChamadaUnica e ChamadaDupla implementam regras diferentes. Uma disciplina tem ao menos um Registro e exatamente uma política; uma atividade referencia uma disciplina por código.",
    )
    section(
        s,
        "Orientação a objetos",
        "A grade fica protegida em Disciplina._registros; a propriedade registros devolve cópias. O setter de nome valida antes da alteração; registrar_presenca controla a mudança que envolve regra de domínio. A classe abstrata e as duas subclasses demonstram herança por especialização. A chamada à mesma operação calcular_faltas(), com resultados distintos conforme a política, demonstra polimorfismo.",
    )
    s.append(
        table(
            ["Camada", "Arquivos", "Responsabilidade"],
            [
                (
                    "Apresentação",
                    "web/index.html, app.css, app.js; web.py",
                    "Receber ações, enviar JSON e mostrar o estado.",
                ),
                (
                    "Negócio",
                    "models.py; exemplo.py",
                    "Validar dados, aplicar regras e preparar a amostra.",
                ),
                (
                    "Dados",
                    "database.py; frequencia.db",
                    "Gravar e recuperar disciplinas, registros e atividades no SQLite.",
                ),
            ],
            [3.2 * cm, 6.1 * cm, 7.7 * cm],
            dense=True,
        )
    )

    page(s, "Produto final", "Como as operações percorrem o sistema")
    section(
        s,
        "Cadastro de disciplina",
        "A página envia a grade a web.py. ControleAcademico constrói Disciplina, que valida código, nome, duração e datas. database.py grava disciplina e registros pendentes numa transação; após o commit, a nova matéria aparece na página.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "preencher"),
                (1, 2, "POST"),
                (2, 3, "criar"),
                (3, 4, "validar"),
                (3, 5, "INSERTs"),
                (5, 3, "commit"),
                (3, 2, "estado"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Controle", "Disciplina", "Dados"],
        )
    )
    section(
        s,
        "Registrar ou corrigir presença",
        "A página envia data, situação e versão vista. Disciplina valida a operação e usa sua política para calcular faltas. O SQLite atualiza a linha daquela data apenas se a versão ainda coincidir; depois do commit, o mesmo Registro é atualizado em memória. Assim, uma aba antiga recebe erro e conserva o valor mais recente.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "situação"),
                (1, 2, "POST + versão"),
                (2, 3, "registrar"),
                (3, 4, "calcular"),
                (3, 5, "UPDATE"),
                (5, 3, "commit"),
                (3, 2, "resumo"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Disciplina", "Política", "Dados"],
        )
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verificacao():
    s = []
    page(s, "Verificação · APPOO 2026/2", "Frequência UFMG")
    s.append(
        P(
            "<b>Integrante:</b> Eduardo Henrique Rodrigues Silva · "
            "<b>Disciplina:</b> APPOO · Prof.ª Luiza Bernardes Real<br/>"
            f"<b>Versão final testada:</b> {VERSION} · "
            "<b>Entrega:</b> Frequencia_UFMG_Entrega_Final.zip"
        )
    )
    section(
        s,
        "Como a verificação foi feita",
        "Os testes unittest exercitam as oito funcionalidades do Produto Final. Cada cenário cria objetos novos ou usa um banco SQLite temporário; o estado observado é comparado ao resultado esperado. As tabelas citam o nome do teste, que pode ser localizado em demo/test_models.py ou demo/test_web.py e na saída da última execução em evidencias/unittest.txt.",
    )
    cenarios(
        s,
        "F01 · Cadastrar disciplina",
        "Estado inicial: controle vazio; C04 injeta falha no banco temporário.",
        [
            (
                "C01",
                "DEMO01, 2 chamadas, 2 aulas, quatro datas.",
                "Disciplina com quatro pendências; E=8.",
                "Quatro registros pendentes; E=8.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C02",
                "Repetir código como demo01.",
                "Rejeitar; primeiro cadastro igual.",
                "ValueError; um cadastro preservado.",
                "Aprovado",
                "test_codigo_duplicado_preserva_cadastro_e_frequencia",
            ),
            (
                "C03",
                "Data repetida ou 2 chamadas em 1 aula.",
                "Rejeitar; controle vazio.",
                "ValueError; nenhuma disciplina criada.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C04",
                "Falha no segundo INSERT da grade.",
                "Desfazer disciplina e registros.",
                "Banco e memória vazios.",
                "Aprovado",
                "test_falha_no_segundo_insert_desfaz_cadastro_e_grade",
            ),
        ],
    )
    page(s, "Verificação", "Registro e correção")
    cenarios(
        s,
        "F02 · Registrar frequência",
        "Estado inicial: DEMO01 com quatro encontros de duas aulas; C07 usa banco temporário.",
        [
            (
                "C05",
                "Presente em 02/11; ausente em 04/11.",
                "A=2; P=4; L=2; percentual pendente.",
                "Resumo A=2, P=4, L=2, F=None.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C06",
                "Situação inválida ou data fora da grade.",
                "Rejeitar; registros e totais iguais.",
                "ValueError; estado preservado.",
                "Aprovado",
                "test_registro_invalido_nao_muda_grade_nem_totais",
            ),
            (
                "C07",
                "Falha SQL ao registrar a primeira data.",
                "Manter a data pendente.",
                "Pendente na memória e no SQLite.",
                "Aprovado",
                "test_falha_na_gravacao_preserva_memoria_e_banco",
            ),
        ],
    )

    cenarios(
        s,
        "F03 · Corrigir frequência",
        "Estado inicial: quatro encontros de duas aulas; C10 usa duas ausências já registradas.",
        [
            (
                "C08",
                "Corrigir uma ausência para presente.",
                "A cai de 4 para 2; mesma data.",
                "A=2; sem linha extra.",
                "Aprovado",
                "test_correcao_atualiza_e_recalcula",
            ),
            (
                "C09",
                "Corrigir data pendente ou usar situação inválida.",
                "Rejeitar; situação e totais iguais.",
                "ValueError; estado anterior igual.",
                "Aprovado",
                "test_correcao_invalida_preserva_registro_e_resumo",
            ),
            (
                "C10",
                "Corrigir com versão antiga de outra aba.",
                "Rejeitar; manter registro recente.",
                "HTTP 400; SQLite preservado.",
                "Aprovado",
                "test_aba_antiga_nao_sobrescreve_correcao_pela_api",
            ),
        ],
    )
    page(s, "Verificação", "Consulta e agenda")
    cenarios(
        s,
        "F04 · Consultar frequência",
        "Estado inicial: disciplina com quatro encontros de duas aulas; a consulta não grava.",
        [
            (
                "C11",
                "Consultar com quatro datas pendentes.",
                "E=8; P=8; L=2; F indefinida.",
                "E=8, P=8, L=2, F=None.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
            (
                "C12",
                "Resolver uma ausência e três presenças.",
                "A=2; frequência 75%.",
                "A=2; P=0; F=75%.",
                "Aprovado",
                "test_percentual_apos_todas_as_datas_resolvidas",
            ),
            (
                "C13",
                "Consultar código inexistente.",
                "Erro; grade anterior igual.",
                "ValueError; nenhum registro alterado.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
        ],
    )
    section(
        s,
        "Limites de cálculo conferidos",
        "Os testes também cobrem o piso de 25%, o encontro cancelado fora da base, o encontro sem chamada com zero faltas e a frequência indefinida enquanto há pendência. A regra de atraso ou saída muda conforme uma ou duas chamadas.",
    )

    cenarios(
        s,
        "F05 · Adicionar atividade",
        "Estado inicial: DEMO01 cadastrada, agenda vazia e grade pendente.",
        [
            (
                "C14",
                "Prova P1 em 03/11, fora da grade.",
                "Atividade vinculada; faltas iguais.",
                "ID salvo; resumo inalterado.",
                "Aprovado",
                "test_atividade_valida_persiste_sem_alterar_frequencia",
            ),
            (
                "C15",
                "Tipo inválido ou título vazio.",
                "Rejeitar; agenda vazia.",
                "ValueError; agenda e grade iguais.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C16",
                "Falha SQL ao inserir P1.",
                "Rejeitar; nenhuma atividade nova.",
                "OSError; banco reaberto vazio.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
        ],
    )
    page(s, "Verificação", "Agenda e nome")
    cenarios(
        s,
        "F06 · Consultar agenda",
        "Estado inicial: banco temporário com atividades cadastradas; C17 usa agenda vazia.",
        [
            (
                "C17",
                "Abrir agenda vazia.",
                "Lista vazia; frequência igual.",
                "Lista vazia, sem gravação.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C18",
                "Inserir P2, T1 e P1; reabrir.",
                "Três atividades em ordem de data/ID.",
                "Tupla recuperada e ordenada.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C19",
                "Falha SQLite ao consultar.",
                "Informar falha; dados preservados.",
                "HTTP 503; estado não alterado.",
                "Aprovado",
                "test_falhas_de_leitura_e_gravacao_sao_visiveis",
            ),
        ],
    )

    cenarios(
        s,
        "F07 · Renomear disciplina",
        "Estado inicial: DEMO01 com uma ausência e uma prova em banco temporário.",
        [
            (
                "C20",
                "Renomear para Nome novo.",
                "Novo nome; código, grade e prova iguais.",
                "Nome salvo; vínculos preservados.",
                "Aprovado",
                "test_renomear_disciplina_valida_e_persiste",
            ),
            (
                "C21",
                "Nome vazio.",
                "Rejeitar; nome antigo igual.",
                "ValueError; Original preservado.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
            (
                "C22",
                "Falha SQL ao salvar nome.",
                "Rejeitar; nome antigo igual.",
                "OSError; memória e banco iguais.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
        ],
    )
    page(s, "Verificação", "Reinício da demo")
    cenarios(
        s,
        "F08 · Apagar dados da demo",
        "Estado inicial: disciplina com presença e atividade em banco temporário.",
        [
            (
                "C23",
                "Confirmar APAGAR.",
                "Três tabelas vazias; novo cadastro possível.",
                "Banco e memória vazios; código recriado.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
            (
                "C24",
                "Informar apagar em minúsculas.",
                "Rejeitar; todos os dados iguais.",
                "HTTP 400; JSON antes/depois igual.",
                "Aprovado",
                "test_entradas_invalidas_preservam_estado",
            ),
            (
                "C25",
                "Falha SQL durante o reset.",
                "Desfazer exclusões; dados iguais.",
                "Disciplina, presença e prova recuperadas.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
        ],
    )

    section(
        s,
        "Como reproduzir",
        "No ZIP, entre em demo/ e execute <b>python -m unittest discover -v</b>. Para conferir pela interface, execute <b>python web.py</b>, use <b>Usar dados de exemplo</b> e abra <b>Ajustes → Executar testes</b>. Os cenários C01–C25 foram aprovados na última execução; as regressões de gravação parcial, correção entre abas e reset constam nas respectivas tabelas.",
    )

    page(s, "Verificação", "Resultado da última execução")
    section(
        s,
        "Última execução",
        "O conjunto automatizado executou 28 testes e terminou com OK. A saída integral está em evidencias/unittest.txt; cada teste citado nas tabelas aparece pelo nome nesse arquivo. Os testes de domínio usam objetos independentes, os de persistência usam bancos temporários e os de HTTP iniciam servidor local em porta temporária.",
    )
    evidencia = (Path(__file__).parent / "package/evidencias/unittest.txt").read_text(
        encoding="utf-8"
    )
    linhas = [
        linha.split(" (", 1)[0] + " ... ok"
        if " (" in linha and linha.endswith(" ... ok")
        else linha
        for linha in evidencia.strip().splitlines()
    ]
    s.append(
        Preformatted(
            "\n".join(linhas),
            ParagraphStyle(
                "SaidaUnittest", fontName="Courier", fontSize=7.8, leading=8.6
            ),
        )
    )
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    produto()
    verificacao()
    print("Relatórios gerados:", Path(__file__).parent)
