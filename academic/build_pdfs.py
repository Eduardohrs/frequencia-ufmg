"""Gera os dois relatórios da mesma versão executável da demo acadêmica."""

# ruff: noqa: E501

from pathlib import Path

from pdf_layout import VERSION, P, build, class_diagram, page, section, sequence_diagram, table
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Preformatted, Spacer


def contrato(story, titulo, entrada, sucesso, rejeicao):
    section(story, titulo)
    story.append(
        table(
            [
                "Condição inicial e entrada",
                "Sucesso: resultado e alteração",
                "Rejeição: motivo e estado",
            ],
            [(entrada, sucesso, rejeicao)],
            [5.6 * cm, 5.7 * cm, 5.7 * cm],
        )
    )
    story.append(Spacer(1, 0.18 * cm))


def cenarios(story, titulo, preparo, linhas):
    section(story, titulo, preparo)
    story.append(
        table(
            ["ID", "Regra e entrada", "Esperado", "Observado", "Situação", "Evidência unittest"],
            linhas,
            [1.6 * cm, 4 * cm, 5.8 * cm, 5.8 * cm, 1.9 * cm, 6.4 * cm],
            dense="tight",
        )
    )
    story.append(Spacer(1, 0.15 * cm))


def produto():
    s = []
    page(s, "Quarta etapa · Produto final", "Frequência UFMG")
    s.append(P("Produto acadêmico executável · interface local e regras em Python", "SubtitleX"))
    s.append(
        table(
            ["Identificação", "Dados"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Disciplina", "APPOO · 2026/2 · Prof.ª Luiza Bernardes Real"),
                ("Versão", VERSION),
                ("Pacote", "Frequencia_UFMG_Entrega_Final.zip"),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    section(
        s,
        "Problema e público",
        "O estudante precisa acompanhar suas faltas antes da consolidação oficial. A aplicação registra o que ocorreu em cada encontro, calcula o saldo permitido e permite corrigir um lançamento. Provas e trabalhos ficam numa agenda curta ligada às disciplinas para ajudar no planejamento pessoal. O resultado não é um comprovante institucional de presença.",
    )
    section(
        s,
        "Funcionalidades entregues",
        "O programa começa com banco vazio e funciona sem conta, internet, Moodle, SIGA ou GPS. O estudante pode usar um botão para inserir dados inteiramente fictícios. A página local é a única interface: as regras e os cálculos permanecem nas classes Python.",
    )
    s.append(
        table(
            ["ID", "Ação", "Resultado visível"],
            [
                ("F01", "Cadastrar disciplina", "Grade inicial de encontros pendentes."),
                ("F02", "Registrar frequência", "Situação e faltas de uma data pendente."),
                (
                    "F03",
                    "Corrigir frequência",
                    "Novo registro da mesma data e totais recalculados.",
                ),
                (
                    "F04",
                    "Consultar frequência",
                    "Grade, limite, faltas, saldo e percentual quando definido.",
                ),
                ("F05", "Adicionar atividade", "Prova ou trabalho associado à disciplina."),
                (
                    "F06",
                    "Consultar agenda",
                    "Atividades em ordem cronológica, inclusive após reabrir.",
                ),
                ("F07", "Renomear disciplina", "Nome corrigido, sem alterar código ou histórico."),
                ("F08", "Apagar dados da demo", "Reinício confirmado pelo próprio aplicativo."),
            ],
            [1.35 * cm, 5.25 * cm, 10.4 * cm],
            dense=True,
        )
    )

    page(s, "01 · Escopo", "Continuidade e recorte")
    section(
        s,
        "Das etapas anteriores ao produto",
        "A proposta inicial prevê um aplicativo ampliado com importação de dados acadêmicos e estimativas de localização. O protótipo funcional demonstrou cadastro e presença manual. O produto acadêmico completa esse núcleo com consulta, correção, SQLite persistente e uma agenda local de provas e trabalhos. A agenda é mantida porque relaciona atividades ao planejamento de frequência e já integra o escopo documentado; não há extração automática de atividades.",
    )
    section(
        s,
        "Ajustes de escopo nesta versão",
        "Remarcação de encontros e menu de terminal eram conveniências da demo, não condições do núcleo. Foram retirados para manter uma só interface e reduzir caminhos de manutenção. A grade é informada no cadastro; se uma data foi cadastrada errada, o caminho desta versão é reiniciar a demo e cadastrar a disciplina novamente. Esse limite é declarado, e o reset fica disponível em Ajustes. O aplicativo real tem escopo maior, mas não é usado como evidência das funções desta versão.",
    )
    section(
        s,
        "O que depende de validação externa",
        "Acesso ao SIGA e ao Moodle depende de sistemas universitários; localização em segundo plano depende das permissões e da economia de energia do aparelho. Nenhuma dessas condições impede cadastrar, registrar, corrigir ou consultar a frequência nesta entrega. A presença manual é uma informação para controle pessoal, sujeita a correção pelo estudante.",
    )
    s.append(
        table(
            ["Parte", "Implementada aqui", "Fora desta versão acadêmica"],
            [
                (
                    "Frequência",
                    "Grade manual, seis situações, cálculo e correção.",
                    "Importação de chamadas e comprovação oficial.",
                ),
                (
                    "Agenda",
                    "Provas e trabalhos informados pelo estudante.",
                    "Sincronização automática com Moodle/SIGA.",
                ),
                (
                    "Dados",
                    "SQLite local, exemplo fictício e reset confirmado.",
                    "Contas, servidor e dados acadêmicos reais.",
                ),
            ],
            [3.1 * cm, 6.9 * cm, 7 * cm],
        )
    )

    page(s, "02 · Contratos", "Cadastro e registro")
    contrato(
        s,
        "F01 · Cadastrar disciplina",
        "Banco vazio ou com outras disciplinas. Informar código e nome não vazios, uma ou duas chamadas, duração inteira de 1, 2 ou 4 aulas de 50 minutos por encontro e ao menos uma data válida sem repetição. Uma aula não aceita duas chamadas.",
        "Normaliza o código em maiúsculas; cria uma disciplina e um Registro pendente por data na mesma transação SQLite. Mostra a matéria pelo nome; código é referência secundária.",
        "Código já existente, data inválida/repetida, duração fora do conjunto ou combinação incompatível mostram erro específico. Nem disciplina nem grade parcial entram no banco ou na memória.",
    )
    contrato(
        s,
        "F02 · Registrar frequência",
        "Disciplina existente e data da grade com situação pendente. Escolher presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
        "Cria um novo Registro para a data. A política de uma ou duas chamadas calcula faltas em aulas de 50 minutos. Depois do commit, a interface mostra situação e totais recalculados.",
        "Disciplina/data inexistente, situação inválida ou data já resolvida sem modo de correção: rejeita e conserva registro, faltas e banco. Erro de escrita também conserva o estado anterior.",
    )
    section(
        s,
        "Unidade da duração",
        "Aulas e faltas são contadas em blocos de 50 minutos. Um encontro com duas aulas corresponde a 100 minutos. Carga horária em horas não é digitada nesta demo: a grade é formada diretamente por datas e aulas por encontro, evitando conversão ambígua de horas acadêmicas.",
    )

    page(s, "03 · Contratos", "Correção e consulta")
    contrato(
        s,
        "F03 · Corrigir frequência",
        "Uma data da grade já tem situação resolvida. Escolher nova situação entre as seis opções e acionar Corrigir. A data e a quantidade de aulas não mudam.",
        "Um novo Registro imutável substitui o valor daquela data; não acrescenta outra linha nem soma faltas duas vezes. O SQLite confirma a troca antes da atualização em memória. Todos os totais são recalculados a partir da grade.",
        "Correção de data ainda pendente, situação inválida, data fora da grade ou falha SQLite: resposta clara e registro anterior intacto. A correção não altera atividades nem nome da matéria.",
    )
    contrato(
        s,
        "F04 · Consultar frequência",
        "Disciplina cadastrada. A página lista nomes; no celular há seletor por nome. Não é preciso memorizar o código. Pode consultar mesmo com encontros pendentes.",
        "Mostra datas, situações e faltas, aulas elegíveis, pendências, limite inteiro, faltas usadas e saldo. O percentual só aparece quando não resta pendência elegível. Ler ou atualizar a página não grava dados.",
        "Código inexistente na camada Python é rejeitado. A interface conserva a seleção válida e pode tentar novamente se o banco não estiver disponível; nenhuma consulta altera registros.",
    )
    section(
        s,
        "Por que Registro é imutável",
        "A classe usa @dataclass(frozen=True). Uma correção não muda o objeto anterior: Disciplina cria outro Registro e substitui, no dicionário interno, o valor associado à mesma data. Isso evita estado parcialmente modificado e torna explícito o instante da troca. O dicionário é protegido; a propriedade registros devolve uma tupla.",
    )

    page(s, "04 · Contratos", "Agenda")
    contrato(
        s,
        "F05 · Adicionar atividade",
        "Disciplina cadastrada. Informar uma data válida, tipo prova ou trabalho e título não vazio. A data pode ser diferente das datas de aula; uma prova não é automaticamente uma chamada.",
        "Salva uma Atividade ligada ao código da disciplina. O SQLite gera identificador; agenda em memória só recebe o objeto depois do commit. Grade, faltas e percentual ficam iguais.",
        "Disciplina inexistente, data/tipo/título inválidos ou falha de escrita: erro específico e agenda intacta. Nenhuma aula é criada e nenhum registro de frequência é alterado.",
    )
    contrato(
        s,
        "F06 · Consultar agenda",
        "Banco vazio ou com atividades de várias disciplinas. Abrir Agenda ou ver o cartão de uma disciplina.",
        "Mostra título, tipo, data com ano e nome da disciplina. Ordena por data e, no empate, pela ordem de inserção. Depois de fechar e reabrir, lê os mesmos itens do SQLite.",
        "Agenda vazia mostra um estado vazio compreensível. Falha de leitura é informada; consultar não grava nem elimina atividade.",
    )
    section(
        s,
        "Contribuição da agenda para o objetivo",
        "Uma avaliação próxima pode influenciar a decisão do estudante de acompanhar uma aula e conferir sua frequência. Nesta entrega, a agenda é curta e manual; ela não altera o cálculo de faltas nem tenta substituir um calendário acadêmico completo.",
    )

    page(s, "05 · Contratos", "Nome e reinício")
    contrato(
        s,
        "F07 · Renomear disciplina",
        "Disciplina existente; informar novo nome não vazio. O código permanece a chave estável do cadastro e das atividades.",
        "Valida e salva o nome no SQLite; só depois o setter atualiza o nome do objeto. Os cartões e as atividades passam a exibir o novo nome, preservando datas, situações e totais.",
        "Nome vazio, disciplina inexistente ou falha SQL: resposta específica e nome anterior preservado no banco e na memória. Código, registros e agenda permanecem iguais.",
    )
    contrato(
        s,
        "F08 · Apagar dados da demo",
        "Abrir Ajustes e digitar exatamente APAGAR. A ação alcança apenas o banco local da demo, não o aplicativo real.",
        "Uma transação remove atividades, registros e disciplinas; após o commit as coleções em memória ficam vazias. O mesmo código pode ser cadastrado novamente.",
        "Cancelar ou digitar outra palavra não apaga nada. Se qualquer DELETE falhar, o SQLite desfaz a transação e as coleções mantêm os valores anteriores.",
    )
    section(
        s,
        "Dados de exemplo",
        "O botão Usar dados de exemplo chama uma função separada em exemplo.py. Ela constrói os objetos com as mesmas regras do cadastro, prepara duas presenças e uma prova fictícia e grava tudo numa transação. Só aceita banco vazio; repetir o pedido não duplica registros. O botão é conveniência de demonstração, não método da classe Disciplina.",
    )

    page(s, "06 · Regras", "Cálculo de frequência")
    section(
        s,
        "Definições explícitas",
        "Base E = soma das aulas dos encontros não cancelados. P = aulas de encontros pendentes dentro de E. A = faltas já resolvidas, em aulas de 50 minutos. Limite L = piso(E × 0,25), isto é, divisão inteira E // 4. Restantes R = máximo(0, L − A). Excesso = máximo(0, A − L). Quando P = 0 e E > 0, frequência = 100 × (E − A) / E. Caso contrário, o percentual fica indefinido; pendência não é presumida presente nem ausente.",
    )
    s.append(
        table(
            ["Situação", "Uma chamada", "Duas chamadas"],
            [
                ("Presente", "0 falta", "0 falta"),
                ("Ausente", "Todas as aulas do encontro", "Todas as aulas do encontro"),
                ("Atrasado / saiu mais cedo", "0 falta", "Metade das aulas do encontro"),
                ("Sem chamada", "0 falta; permanece na base", "0 falta; permanece na base"),
                ("Cancelada", "Sai da base", "Sai da base"),
            ],
            [5.6 * cm, 5.7 * cm, 5.7 * cm],
        )
    )
    section(
        s,
        "Exemplo conferível",
        "Quatro encontros de duas aulas geram E = 8 e L = 2. Depois de uma presença e uma ausência: A = 2, P = 4, R = 0 e percentual ainda indefinido. Ao resolver os dois pendentes como presentes: P = 0 e frequência = 100 × (8 − 2) / 8 = 75%. Corrigir a ausência para presente gera A = 0, R = 2 e frequência = 100%. Cancelar um encontro reduz E em 2 e recalcula L; reposição não é criada automaticamente nesta demo.",
    )
    section(
        s,
        "Regra de um ping ou dois",
        "Localização e pings não integram este executável acadêmico. Os nomes ChamadaUnica e ChamadaDupla designam apenas regras para converter o registro manual de atraso/saída em faltas; não são prova de presença física nem representam uma captura automática de GPS.",
    )

    page(s, "07 · Modelo", "Classes e responsabilidades")
    s.append(class_diagram())
    section(
        s,
        "Leitura do diagrama",
        "ControleAcademico coordena cadastro, busca, gravação, agenda e reset. Disciplina guarda código, nome, política e um dicionário data → Registro. Registro é o retrato imutável de um encontro; Atividade é o retrato imutável de uma prova ou trabalho. PoliticaChamada é abstrata e define calcular_faltas; ChamadaUnica e ChamadaDupla especializam o cálculo. Não existe uma classe de disciplina persistente: o controle liga funções de gravação aos objetos carregados, que chamam database.py antes de publicar cada mudança.",
    )
    section(
        s,
        "Conceitos de POO demonstrados",
        "Encapsulamento: a grade fica em _registros e o getter devolve tupla; o nome tem setter que valida. Herança por especialização: as duas políticas implementam a classe abstrata PoliticaChamada. Polimorfismo: Disciplina chama calcular_faltas sem saber qual implementação foi escolhida. Registro imutável não impede corrigir a frequência: o agregado substitui o valor do dia por outro objeto.",
    )

    page(s, "08 · Interações", "Sequências essenciais")
    section(
        s,
        "Cadastro F01",
        "A página transforma datas digitadas em datas ISO e envia o pedido. ControleAcademico constrói Disciplina, que valida a grade inteira. database.py insere disciplina e encontros pendentes na mesma transação. Só após o commit o controle inclui a matéria em memória. Qualquer erro preserva o banco e a lista anteriores.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "cadastrar"),
                (1, 2, "criar_disciplina"),
                (2, 3, "validar grade"),
                (2, 4, "transação INSERT"),
                (4, 2, "commit"),
                (2, 1, "disciplina criada"),
            ],
            ["Estudante", "Página", "Controle", "Disciplina", "SQLite"],
        )
    )
    section(
        s,
        "Presença e correção F02–F03",
        "A página informa código, data e situação. O controle encontra Disciplina, que valida se a data existe e se o modo é registro inicial ou correção. A política calcula faltas. O SQLite grava o novo valor; somente depois Disciplina substitui o Registro daquela data. Um erro interrompe antes da substituição.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "registrar / corrigir"),
                (1, 2, "registrar_presenca"),
                (2, 3, "validar e calcular"),
                (3, 4, "salvar Registro"),
                (4, 3, "commit"),
                (3, 2, "novo Registro"),
                (2, 1, "totais recalculados"),
            ],
            ["Estudante", "Página", "Controle", "Disciplina", "SQLite"],
        )
    )

    page(s, "09 · Implementação", "Camadas, dados e reprodução")
    section(
        s,
        "Separação de responsabilidades",
        "Apresentação: web/index.html, app.css e app.js recebem ações e mostram o estado; web.py converte JSON/datas e serve a página em 127.0.0.1. Negócio: models.py valida e calcula com classes de domínio; exemplo.py cria apenas a amostra fictícia. Dados: database.py cria tabelas, grava e recupera SQLite. A interface não calcula faltas e a camada de dados não escolhe política de chamada.",
    )
    section(
        s,
        "Persistência e integridade",
        "disciplinas usa código normalizado como chave; registros usa código + data; atividades usa ID do SQLite e referência ao código. Cada mudança que envolve várias linhas usa transação. Totais não são gravados: são recalculados da grade, evitando divergência após correções. O arquivo frequencia.db entregue está vazio e pronto para uso; o botão de exemplo o preenche com dados fictícios.",
    )
    section(
        s,
        "Como executar",
        "Requer Python 3.11 ou superior, sem dependências externas. Extraia Frequencia_UFMG_Entrega_Final.zip, entre na pasta demo e execute <b>python web.py</b>. Abra http://127.0.0.1:8878 se o navegador não abrir automaticamente. Clique Usar dados de exemplo ou cadastre manualmente uma disciplina. Em Ajustes, Executar testes roda unittest em bancos temporários; alternativamente, dentro de demo execute <b>python -m unittest discover -v</b>. Para sair, pressione Ctrl+C no terminal.",
    )
    section(
        s,
        "Limitações conhecidas e pacote",
        "Não há remarcação, edição/exclusão individual de atividades, importação universitária, autenticação ou comprovação de presença. Essas ações não são apresentadas como prontas. O ZIP inclui código, banco vazio, testes, README, evidência da última execução e os dois PDFs. A versão testada no relatório de verificação é a mesma indicada na capa.",
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verificacao():
    s = []
    page(s, "Quinta etapa · Verificação", "Frequência UFMG · Verificação")
    s.append(P("Contratos, cenários e resultado observado da mesma versão do produto", "SubtitleX"))
    s.append(
        table(
            ["Identificação", "Dados"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Versão testada", VERSION),
                ("Pacote", "Frequencia_UFMG_Entrega_Final.zip"),
                ("Execução", "python -m unittest discover -v, dentro de demo/"),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    section(
        s,
        "Método",
        "Cada teste constrói seus próprios objetos ou usa um arquivo SQLite temporário. Os dados da demo e do aplicativo real não entram nos testes. Para cada função F01–F08, as tabelas seguintes registram condição inicial, entrada, resultado previsto, resultado observado, situação e nome do teste. A evidência integral da última execução está em evidencias/unittest.txt no ZIP. A interface web possui testes HTTP com banco isolado; o botão Executar testes chama o mesmo conjunto.",
    )
    section(
        s,
        "Interpretação dos resultados",
        "Aprovado significa que a execução obteve o resultado esperado e conferiu o estado final; falhou significa divergência; não executado significa ausência de evidência. Um erro esperado em cenário de rejeição conta como aprovado quando o estado anterior permanece intacto. Os IDs C01–C24 identificam os cenários deste PDF, não a ordem em que unittest os executa.",
    )
    section(
        s,
        "Cobertura",
        "F01–F04: cadastro e frequência. F05–F06: agenda. F07–F08: nome e reinício. Cada grupo inclui sucesso e rejeição ou limite relevante.",
    )

    page(s, "Matriz · F01–F02", "Cadastro e registro")
    cenarios(
        s,
        "F01 · Cadastrar disciplina",
        "Estado inicial de cada cenário: controle vazio e banco temporário vazio; datas de novembro de 2026. C04 simula falha durante a transação.",
        [
            (
                "C01",
                "DEMO01, duas chamadas, duas aulas, quatro datas únicas.",
                "Uma disciplina e quatro registros pendentes; E=8.",
                "Objeto e linhas criados; E=8 e P=8.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C02",
                "Repetir código demo01 com caixa diferente.",
                "Rejeitar; cadastro e frequência iniciais iguais.",
                "ValueError; um único cadastro preservado.",
                "Aprovado",
                "test_codigo_duplicado_preserva_cadastro_e_frequencia",
            ),
            (
                "C03",
                "Data repetida, duração fora de 1/2/4 ou duas chamadas em uma aula.",
                "Rejeitar; nenhuma disciplina/grade nova.",
                "ValueError em cada entrada; estado vazio.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C04",
                "Falha SQL no segundo INSERT da grade.",
                "Rollback de disciplina e registros.",
                "Tabelas e memória sem cadastro parcial.",
                "Aprovado",
                "test_falha_no_segundo_insert_desfaz_cadastro_e_grade",
            ),
        ],
    )
    cenarios(
        s,
        "F02 · Registrar frequência",
        "Estado inicial: DEMO01 com quatro datas pendentes, duas aulas por encontro; banco próprio quando há persistência.",
        [
            (
                "C05",
                "Registrar ausência em 02/11.",
                "Registro ausente, A=2, P=6, L=2.",
                "A=2; grade mantém seis aulas pendentes.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C06",
                "Situação desconhecida ou data fora da grade.",
                "Rejeitar; registros e totais iguais.",
                "ValueError; objetos anteriores preservados.",
                "Aprovado",
                "test_registro_invalido_nao_muda_grade_nem_totais",
            ),
            (
                "C07",
                "Falha de gravação antes de resolver 02/11.",
                "Pendente em memória e SQLite.",
                "OSError; ambos continuam pendentes.",
                "Aprovado",
                "test_falha_na_gravacao_preserva_memoria_e_banco",
            ),
        ],
    )

    page(s, "Matriz · F03–F04", "Correção e consulta")
    cenarios(
        s,
        "F03 · Corrigir frequência",
        "Cada teste começa com disciplina nova; C08 tem duas ausências, C09 uma ausência e C10 resolve as demais datas como indicado.",
        [
            (
                "C08",
                "Após duas ausências, corrigir 02/11 para presente.",
                "Trocar Registro; A de 4 para 2, sem linha extra.",
                "Registro novo; faltas recalculadas para duas.",
                "Aprovado",
                "test_correcao_substitui_e_recalcula",
            ),
            (
                "C09",
                "Corrigir frequência de encontro pendente ou situação inválida.",
                "Rejeitar; Registro e resumo anteriores iguais.",
                "ValueError; estado comparado e preservado.",
                "Aprovado",
                "test_correcao_invalida_preserva_registro_e_resumo",
            ),
            (
                "C10",
                "Corrigir para sem chamada ou cancelada.",
                "Sem chamada: zero falta na base; cancelada: sai da base.",
                "Base, limite e percentual recalculados.",
                "Aprovado",
                "test_correcao_substitui_e_recalcula",
            ),
        ],
    )
    cenarios(
        s,
        "F04 · Consultar frequência",
        "Estado inicial: disciplina com quatro encontros de duas aulas; consultas não devem gravar.",
        [
            (
                "C11",
                "Consultar com pelo menos uma data pendente.",
                "Mostrar E, A, P, L, R; percentual indefinido.",
                "Resumo tem P>0 e frequência None.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
            (
                "C12",
                "Resolver todas: uma ausência, três presenças.",
                "E=8, A=2, L=2, frequência 75%.",
                "Totais recalculados a partir dos registros.",
                "Aprovado",
                "test_percentual_apos_todas_as_datas_resolvidas",
            ),
            (
                "C13",
                "Consultar código inexistente.",
                "Erro; nenhuma alteração na grade.",
                "ValueError e grade anterior igual.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
        ],
    )

    page(s, "Matriz · F05–F06", "Agenda")
    cenarios(
        s,
        "F05 · Adicionar atividade",
        "Estado inicial: DEMO01 cadastrada e agenda vazia; grade com quatro registros pendentes.",
        [
            (
                "C14",
                "Prova P1 em 03/11, fora da grade.",
                "Atividade vinculada; frequência inalterada.",
                "ID persistido; grade e resumo iguais.",
                "Aprovado",
                "test_atividade_valida_persiste_sem_alterar_frequencia",
            ),
            (
                "C15",
                "Tipo inválido, título vazio ou data inválida.",
                "Rejeitar; agenda vazia e grade igual.",
                "ValueError; estado anterior preservado.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C16",
                "Falha SQL ao inserir P1.",
                "Nada acrescentado à agenda.",
                "OSError; agenda vazia no banco reaberto.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
        ],
    )
    cenarios(
        s,
        "F06 · Consultar agenda",
        "Estado inicial: disciplinas com atividades fictícias; cada teste prepara seu banco.",
        [
            (
                "C17",
                "Abrir agenda vazia.",
                "Lista vazia; nenhum dado criado.",
                "Lista vazia retornada sem gravação.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C18",
                "Criar prova P1 e reabrir o controle.",
                "Mesmo título, data, tipo e vínculo.",
                "Atividade recuperada do SQLite.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C19",
                "Atividades em datas diferentes.",
                "Ordem por data e ID no empate.",
                "Consulta ordenada sem mudar frequência.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
        ],
    )

    page(s, "Matriz · F07–F08", "Nome e reset")
    cenarios(
        s,
        "F07 · Renomear disciplina",
        "Estado inicial: DEMO01, uma ausência e prova P1 em banco temporário.",
        [
            (
                "C20",
                "Renomear para Circuitos 2.",
                "Novo nome após reabrir; código, grade e P1 preservados.",
                "Nome novo no SQLite; dados associados iguais.",
                "Aprovado",
                "test_renomear_disciplina_valida_e_persiste",
            ),
            (
                "C21",
                "Nome vazio ou falha no UPDATE.",
                "Rejeitar; nome antigo em memória e SQLite.",
                "ValueError/OSError; nome antigo preservado.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
        ],
    )
    cenarios(
        s,
        "F08 · Apagar dados da demo",
        "Estado inicial: uma disciplina com presença e atividade; banco temporário.",
        [
            (
                "C22",
                "Confirmar APAGAR em Ajustes.",
                "As três tabelas vazias; pode recriar código.",
                "Banco e memória vazios; novo cadastro aceito.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
            (
                "C23",
                "Digitar apagar em minúsculas.",
                "Rejeitar; todos os dados anteriores iguais.",
                "HTTP 400; estado antes/depois igual.",
                "Aprovado",
                "test_entradas_invalidas_preservam_estado",
            ),
            (
                "C24",
                "Falha SQL durante o reset.",
                "Rollback integral; nada apagado.",
                "Disciplina, registro e atividade recuperados.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
        ],
    )

    page(s, "Integração", "Caminho HTTP e estado persistente")
    section(
        s,
        "Fluxo completo pela API local",
        "O teste HTTP começa com banco temporário vazio, cria disciplina, registra ausência, corrige para presença, adiciona prova, renomeia, consulta de novo e apaga com APAGAR. O resultado observado após cada POST é comparado com a resposta esperada; uma nova requisição GET reconstrói os objetos do SQLite. Este teste chama a API diretamente e não executa o JavaScript da página.",
    )
    s.append(
        table(
            ["Condição", "Esperado", "Observado / evidência"],
            [
                (
                    "Cadastro e correção",
                    "Uma linha por data; totais após correção.",
                    "Resposta HTTP e GET reaberto iguais · test_fluxo_completo_e_reabertura",
                ),
                (
                    "Entrada inválida",
                    "Resposta compreensível e estado anterior igual.",
                    "HTTP 400 e comparação do JSON · test_entradas_invalidas_preservam_estado",
                ),
                (
                    "Falha de leitura/gravação",
                    "HTTP 503 e mensagem que identifica a falha.",
                    "HTTP 503 com mensagem 'disco' · test_falhas_de_leitura_e_gravacao_sao_visiveis; rollback: test_falha_na_gravacao_preserva_memoria_e_banco",
                ),
                (
                    "Exemplo fictício",
                    "Aceita só banco vazio; transação completa.",
                    "Segunda tentativa 400 · test_exemplo_persiste_ou_faz_rollback_completo",
                ),
                (
                    "Testes pelo botão",
                    "API devolve quantidade e OK da execução recebida.",
                    "Execução simulada na API · test_botoes_exemplo_e_testes_nao_exigem_preparo; execução real: página de evidência deste PDF",
                ),
            ],
            [4.1 * cm, 5.7 * cm, 15.3 * cm],
        )
    )
    section(
        s,
        "Limites calculados",
        "Os cenários de unidade e porcentagem verificam quatro encontros de duas aulas, piso de 25%, cancelamento fora da base e pendência sem frequência presumida. Atraso e saída usam políticas diferentes sem duplicar o algoritmo no controle. Uma falha de SQLite é testada com injeção temporária de erro; o banco da demonstração não é alterado.",
    )

    page(s, "Evidências", "Rastreabilidade dos testes")
    section(
        s,
        "Onde estão as provas",
        "O ZIP contém demo/test_models.py e demo/test_web.py. Cada linha de unittest inclui o nome do teste, seguido de ok. O arquivo evidencias/unittest.txt guarda a saída integral da última execução. A tabela resume os pontos de decisão mais sensíveis; as matrizes anteriores citam o teste de cada cenário pelo nome completo, sem depender da ordem de execução.",
    )
    s.append(
        table(
            ["Contrato", "Teste principal", "Estado conferido"],
            [
                (
                    "F01",
                    "test_entrada_invalida_nao_cria_disciplina",
                    "Cadastro e grade vazios após rejeição",
                ),
                (
                    "F02",
                    "test_falha_na_gravacao_preserva_memoria_e_banco",
                    "Registro pendente nos dois lados",
                ),
                (
                    "F03",
                    "test_correcao_substitui_e_recalcula",
                    "A e L recalculados, sem duplicação",
                ),
                ("F04", "test_consulta_nao_altera_registros", "Consultas sem mutação"),
                (
                    "F05",
                    "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
                    "Agenda e frequência intactas",
                ),
                (
                    "F06",
                    "test_atividade_valida_persiste_sem_alterar_frequencia",
                    "Agenda recuperada após reabertura",
                ),
                (
                    "F07",
                    "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
                    "Nome anterior preservado",
                ),
                (
                    "F08",
                    "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
                    "Transação e rollback",
                ),
            ],
            [3 * cm, 11 * cm, 10 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Independência",
        "Os testes de domínio puro criam classes novas; os de persistência usam TemporaryDirectory; os de HTTP iniciam servidor local em porta temporária. Nenhum cenário precisa de conta, rede, localização ou ordem especial. A verificação do pacote extrai o ZIP e repete unittest sobre os arquivos realmente enviados.",
    )

    page(s, "Defeitos e regressão", "O que foi corrigido")
    section(
        s,
        "Registro de ajustes verificáveis",
        "Na revisão do produto, a remarcação de data e o menu alternativo foram retirados para reduzir o escopo e manter um caminho único de uso. A criação do exemplo foi movida para exemplo.py, separada da classe de domínio. A fachada _DisciplinaPersistente foi eliminada; o controle liga a gravação a cada disciplina para que lista, busca e cadastro tenham o mesmo comportamento persistente. Esses itens eram caminhos adicionais que confundiam o recorte acadêmico e sua explicação oral.",
    )
    s.append(
        table(
            ["Risco observado", "Mudança", "Regressão executada"],
            [
                (
                    "Exemplo podia deixar dados parciais numa falha",
                    "Validação antes da gravação e uma única transação SQLite.",
                    "test_exemplo_persiste_ou_faz_rollback_completo",
                ),
                (
                    "Correção podia divergir do banco se a escrita falhasse",
                    "Salvar antes de substituir o Registro do dia.",
                    "test_falha_na_gravacao_preserva_memoria_e_banco",
                ),
                (
                    "Reset com exclusão parcial",
                    "DELETEs na mesma transação; memória limpa após commit.",
                    "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
                ),
            ],
            [4.5 * cm, 6 * cm, 6.5 * cm],
        )
    )
    section(
        s,
        "Resultado e pendências",
        "A última execução de unittest foi aprovada; o número exato de testes e a saída completa constam em evidencias/unittest.txt. Não há falha conhecida nos contratos F01–F08 desta versão. Importação universitária, localização automática e remarcação de grade estão fora do recorte e não foram marcadas como verificadas neste relatório.",
    )

    page(s, "Reprodução", "Como conferir esta versão")
    section(
        s,
        "Preparação em poucos passos",
        "1. Extraia Frequencia_UFMG_Entrega_Final.zip. 2. Entre na pasta demo/. 3. Execute python web.py. 4. Abra http://127.0.0.1:8878 se necessário. 5. Clique Usar dados de exemplo e consulte a disciplina e a agenda. 6. Em Ajustes, clique Executar testes; o resultado aparece na página. O mesmo conjunto pode ser executado com python -m unittest discover -v, dentro de demo/. Não existe outro front nem script de configuração prévia.",
    )
    section(
        s,
        "Conferência manual a partir do zero",
        "Em Ajustes, apague os dados da demo com APAGAR. Cadastre DEMO01, duas chamadas e dois blocos de 50 minutos por encontro nas datas 02, 04, 09 e 11/11/2026. Marque 02/11 como ausente: faltas usadas 2, limite 2 e frequência ainda indefinida. Corrija 02/11 para presente: faltas usadas 0. Cadastre uma prova em 10/11/2026 e reabra a página: prova e frequência devem permanecer. Uma data fora da grade deve ser rejeitada sem mudar esses dados.",
    )
    section(
        s,
        "Como conferir a última execução",
        "Abra evidencias/unittest.txt no ZIP. O final do arquivo informa o total de testes e OK; as linhas anteriores listam cada nome usado nas matrizes. O verificador do pacote também extrai os arquivos e executa o conjunto sobre uma base temporária. O arquivo demo/frequencia.db fornecido é uma base inicial vazia, sem dados reais; o botão de exemplo monta dados fictícios quando solicitado.",
    )
    section(
        s,
        "Estado final",
        "Produto e verificação exibem o identificador de versão "
        + VERSION
        + ". Os resultados observados nas tabelas correspondem ao código e aos testes incluídos no mesmo ZIP. Se a universidade ou o navegador estiverem indisponíveis, o executável local continua demonstrável porque não consulta serviços externos.",
    )

    page(s, "Última execução", "Saída integral de unittest")
    section(
        s,
        "Evidência no próprio relatório",
        "Esta é a saída da execução realizada ao montar o ZIP desta versão. As linhas identificam os mesmos testes citados nas tabelas, e o final registra a quantidade e o resultado. A cópia em texto está em evidencias/unittest.txt para repetição e busca.",
    )
    evidencia = (Path(__file__).parent / "package/evidencias/unittest.txt").read_text(
        encoding="utf-8"
    )
    s.append(
        Preformatted(
            evidencia.strip(),
            ParagraphStyle("SaidaUnittest", fontName="Courier", fontSize=7.8, leading=10.7),
        )
    )
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    produto()
    verificacao()
    print("Relatórios gerados:", VERSION, Path(__file__).parent)
