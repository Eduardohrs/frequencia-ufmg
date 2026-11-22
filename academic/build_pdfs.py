"""Conteúdo dos relatórios; rode ``py academic/build_pdfs.py`` na raiz.

Cada bloco principal começa em página própria. A matriz da verificação usa A4
horizontal para preservar as seis colunas exigidas pelo enunciado.
"""

# Os parágrafos do relatório ficam em frases inteiras para revisão editorial.
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
from reportlab.lib.units import cm
from reportlab.platypus import Spacer, TableStyle


def contract(story, title, initial, success, rejection):
    section(story, title)
    story.append(
        table(
            [
                "Condição inicial e entrada",
                "Sucesso e estado final",
                "Rejeição e estado preservado",
            ],
            [(initial, success, rejection)],
            [5.5 * cm, 5.7 * cm, 5.8 * cm],
        )
    )
    story.append(Spacer(1, 0.19 * cm))


def product():
    s = []
    page(s, "Quarta etapa · Produto final", "Frequência UFMG")
    s.append(P("Relatório do produto acadêmico", "SubtitleX"))
    s.append(
        table(
            ["Identificação", "Informação"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Disciplina e período", "APPOO · 2026/2"),
                ("Versão entregue", VERSION),
                (
                    "Executável",
                    "<b>Frequencia_UFMG_Entrega_Final.zip</b> — interface local, Python, SQLite, dados fictícios e testes",
                ),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    s.append(Spacer(1, 0.25 * cm))
    section(
        s,
        "Problema e público",
        "O estudante da UFMG precisa saber quantas faltas ainda pode ter antes da consolidação oficial. O produto registra cada encontro, calcula o saldo em aulas de 50 minutos e permite corrigir um lançamento. Uma agenda pequena de provas e trabalhos ajuda a planejar a presença em semanas importantes. O resultado é pessoal; não substitui o diário da universidade.",
    )
    section(
        s,
        "O que está pronto",
        "A interface local abre no navegador com um banco vazio: cadastra disciplinas e datas, registra e corrige frequência, consulta os cálculos e adiciona atividades. O estudante escolhe pelo nome, sem decorar códigos, corrige uma data errada sem perder presença e pode recomeçar em Ajustes. O menu de terminal oferece o fluxo principal como alternativa; a correção de data é visual. O SQLite conserva tudo entre aberturas; não há conta, internet nem dados reais obrigatórios.",
    )
    s.append(
        table(
            ["ID e função", "Resultado que o estudante obtém"],
            [
                (
                    "F01 · Cadastrar disciplina",
                    "Cria disciplina e grade de encontros pendentes; no navegador, permite corrigir a data de um encontro.",
                ),
                (
                    "F02 · Registrar frequência",
                    "Resolve uma data com situação e faltas.",
                ),
                (
                    "F03 · Corrigir frequência",
                    "Substitui um registro e recalcula os totais.",
                ),
                (
                    "F04 · Consultar frequência",
                    "Mostra grade, faltas, limite, saldo e percentual definido.",
                ),
                (
                    "F05 · Agendar atividade",
                    "Guarda prova ou trabalho vinculado à disciplina.",
                ),
                (
                    "F06 · Consultar agenda",
                    "Lista as atividades por data, inclusive depois de reiniciar.",
                ),
                (
                    "F07 · Renomear disciplina",
                    "Corrige o nome sem alterar código, grade ou frequência.",
                ),
                (
                    "F08 · Recomeçar do zero",
                    "Apaga disciplinas, presenças e atividades só após confirmação.",
                ),
            ],
            [5.3 * cm, 11.7 * cm],
        )
    )

    page(s, "01 · Escopo", "Continuidade do projeto e recorte")
    section(
        s,
        "Das entregas anteriores ao produto",
        "A proposta inicial combinou controle de frequência, dados acadêmicos e estimativa de presença por localização. O protótipo funcional mostrou cadastro e registro manuais. A versão final acadêmica conserva esse núcleo e integra persistência SQLite, consulta e correção completas e uma agenda local de avaliações. O percurso é executável desde o banco vazio: criar, registrar, corrigir, consultar, fechar e recuperar.",
    )
    section(
        s,
        "Ajuste de escopo explícito",
        "Autenticação, importação da UFMG e localização não integram este executável. Exigem serviços, credenciais e permissões externas; falhar neles não pode impedir o controle pessoal. Essas capacidades pertencem ao aplicativo ampliado e não são descritas como prontas na entrega acadêmica. Esta redução torna verificáveis as regras centrais sem depender de infraestrutura da universidade.",
    )
    s.append(
        table(
            ["Necessidade", "Nesta entrega", "Consequência e alternativa"],
            [
                (
                    "Frequência pessoal",
                    "Cadastro, registro, correção e consulta manuais.",
                    "Funciona sem internet; conferir o diário oficial separadamente.",
                ),
                (
                    "Planejar avaliações",
                    "Prova e trabalho locais, ligados à disciplina.",
                    "A agenda não altera as faltas; preenchimento manual.",
                ),
                (
                    "Dados oficiais/GPS",
                    "Não presentes no executável acadêmico.",
                    "Sem integração, o estudante ainda cadastra e corrige; GPS seria estimativa, nunca prova institucional.",
                ),
            ],
            [3.8 * cm, 6.1 * cm, 7.1 * cm],
        )
    )
    section(
        s,
        "Premissas visíveis ao usuário",
        "Cada data informada representa um encontro. A duração, em aulas de 50 minutos, é igual para todos os encontros da disciplina. A configuração de uma ou duas chamadas também é fixa por disciplina. A base vem dessas datas, não de carga oficial importada; o estudante deve comparar a grade com o plano de ensino. Uma prova pode ocorrer em data diferente das aulas cadastradas.",
    )
    section(
        s,
        "Regra de localização da proposta ampliada",
        "Na modelagem original, localização no campus é apenas uma estimativa. Uma chamada aceitaria um dos dois checkpoints positivo; duas chamadas distinguiriam dois positivos, somente o primeiro, somente o segundo ou nenhum. Falha de permissão ou GPS deixaria a aula pendente, nunca automaticamente ausente. O executável acadêmico não captura checkpoints: o próprio estudante informa a situação e pode corrigi-la.",
    )
    section(
        s,
        "Por que a agenda está no produto",
        "Ver uma prova ou trabalho na mesma disciplina contextualiza o saldo de faltas e ajuda a planejar presença. A função tem somente título, tipo e data. Ela não calcula notas, não dispara lembretes e não modifica presenças; apoia o objetivo central sem virar um gerenciador geral de tarefas.",
    )

    page(s, "02 · Contratos", "Cadastro e registro de frequência")
    contract(
        s,
        "F01 · Cadastrar disciplina",
        "Banco iniciado; código ainda ausente. Entradas: código e nome não vazios; 1 ou 2 chamadas; 1, 2 ou 4 aulas de <b>50 min</b> por encontro; ao menos uma data real DD/MM/AAAA, sem repetição.",
        "Normaliza código para maiúsculas; cria disciplina e datas pendentes em uma transação. Retorna a disciplina com resumo inicial. A memória só recebe o cadastro após o commit.",
        "Código duplicado, vazio, data inválida/repetida, número fora do conjunto ou duas chamadas em uma aula: informa motivo. Não cria disciplina nem parte da grade; falha de SQLite também não publica cadastro parcial.",
    )
    contract(
        s,
        "F02 · Registrar frequência",
        "Disciplina existente e data da grade ainda pendente. A interface lista matérias pelo nome; no menu alternativo, elas são numeradas. O usuário escolhe data e situação: presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
        "Política da disciplina calcula faltas em unidades de 50 min. Confirma a escrita no SQLite, substitui o pendente e recalcula base, faltas, pendências, limite, saldo, excesso e percentual.",
        "Data fora da grade, situação desconhecida ou repetição sem usar Corrigir: rejeita. Registro, banco e totais anteriores permanecem; falha de escrita também preserva a memória.",
    )
    section(
        s,
        "Sentido de cada situação",
        "<b>Presente:</b> zero faltas. <b>Ausente:</b> todas as aulas do encontro são faltas. <b>Atrasado</b> e <b>saiu mais cedo:</b> com duas chamadas perdem metade das aulas; com uma chamada não perdem. <b>Sem chamada:</b> encontro conta na base com zero faltas. <b>Cancelada:</b> encontro sai da base. <b>Pendente:</b> estado inicial, sem presença ou falta presumida.",
    )

    page(s, "03 · Contratos", "Correção, consultas e agenda")
    contract(
        s,
        "F03 · Corrigir frequência",
        "Disciplina e data da grade já resolvida. O usuário escolhe a disciplina pelo número, depois Corrigir e uma das seis situações, inclusive para substituir cancelada ou sem chamada.",
        "Substitui apenas o registro daquela data; não acumula uma segunda falta. Recalcula os mesmos totais de F02 depois do commit.",
        "Data pendente, situação ou data inválida: rejeita e preserva registro e totais. Para a pendente, use Registrar presença. Não altera outras datas.",
    )
    contract(
        s,
        "F04 · Consultar frequência",
        "Disciplina cadastrada; a interface lista seus nomes em ordem alfabética, com o código apenas como referência. No menu alternativo, o usuário escolhe o número ou 0 para voltar.",
        "A consulta exibe nome, grade, situação e faltas por data, base E, pendências, faltas A, limite L, saldo, excesso e frequência quando definida. Não grava dados.",
        "Número fora da lista ou não numérico: pede uma escolha válida. Falha de leitura no navegador mostra erro persistente e Tentar novamente, sem apresentar um cadastro vazio fictício. Voltar não altera registros nem totais.",
    )
    section(
        s,
        "Correção da data de um encontro já cadastrado (F01)",
        "No navegador, Corrigir data recebe uma data da grade e outra data válida que ainda não esteja nessa disciplina. A operação muda apenas a chave do encontro em uma transação SQLite: situação, número de aulas e faltas permanecem, assim como os totais. A lista volta ordenada por data. Data antiga inexistente, nova data inválida ou já usada rejeita a mudança; falha de escrita preserva memória e banco. Provas e trabalhos são registros independentes e não mudam de data. O menu de terminal não oferece esta correção.",
    )
    contract(
        s,
        "F05 · Agendar atividade",
        "Disciplina existente, escolhida pelo nome numerado; data real DD/MM/AAAA, tipo prova ou trabalho e título não vazio. A data não precisa coincidir com aula.",
        "Grava atividade com identificador local e vínculo com disciplina. F06 a mostra mesmo após reabrir; não muda encontros ou faltas.",
        "Código inexistente, data inválida, tipo desconhecido, título vazio ou falha de escrita: agenda e frequência anteriores intactas.",
    )
    page(s, "03 · Contratos", "Agenda, nome e reinício")
    contract(
        s,
        "F06 · Consultar agenda",
        "Basta abrir o programa; não recebe filtro. Pode estar vazia.",
        "Lista atividades por data e ordem de inserção, com nome da disciplina e código secundário; se não houver itens, mostra Agenda vazia. Não grava dados.",
        "Como não há entrada a validar, não existe rejeição prevista nesta consulta.",
    )
    contract(
        s,
        "F07 · Renomear disciplina",
        "Disciplina existente, escolhida pelo nome numerado. Entrada: novo nome com ao menos um caractere não branco.",
        "O setter valida o nome; o controle grava primeiro no SQLite e depois atualiza o objeto. Código, grade, atividades, presenças e totais ficam iguais.",
        "Código inexistente, nome vazio ou erro de escrita: rejeita; nome anterior permanece na memória e no banco.",
    )
    contract(
        s,
        "F08 · Recomeçar do zero",
        "Banco iniciado, vazio ou preenchido. O usuário escolhe Apagar dados em Ajustes ou 8 no menu e digita exatamente APAGAR; qualquer outra resposta cancela.",
        "Uma transação apaga atividades, registros e disciplinas; após o commit, limpa a memória. A interface volta vazia e permite cadastrar de novo o mesmo código.",
        "Resposta diferente de APAGAR cancela sem alterar nada. Se o SQLite falhar, a transação faz rollback e memória, registros e atividades continuam iguais.",
    )

    page(s, "04 · Regras", "Cálculo com unidades e exemplos")
    section(
        s,
        "Definições que o código aplica",
        "Uma aula equivale a <b>50 minutos</b>. E é a soma das aulas dos encontros cadastrados, exceto os cancelados. L = piso(0,25 × E), no código E // 4. A é a soma das faltas de registros resolvidos. Saldo R = máximo(0, L − A) e excesso X = máximo(0, A − L). F = 100 × (E − A) / E só aparece se E &gt; 0 e não há aulas pendentes. Antes disso, o programa informa frequência pendente; pendência não vira presença nem ausência.",
    )
    s.append(
        table(
            ["Caso", "Conta feita", "O que se vê"],
            [
                (
                    "4 encontros de 2 aulas",
                    "E=8; L=2. Uma ausência de 2 aulas: A=2.",
                    "R=0; F segue pendente se outras datas ainda não foram resolvidas.",
                ),
                (
                    "1 encontro cancelado",
                    "E cai de 8 para 6; L=piso(1,5)=1. Se A=2, X=1.",
                    "O limite cai; cancelamento não adiciona falta.",
                ),
                (
                    "4 aulas com atraso",
                    "1 chamada: 0 faltas. 2 chamadas: 4 // 2 = 2.",
                    "A mesma operação usa políticas concretas diferentes.",
                ),
                (
                    "Sem chamada",
                    "O encontro permanece em E e contribui 0 para A.",
                    "Não é confundido com cancelamento ou pendência.",
                ),
                (
                    "Base hipotética E=61",
                    "L=piso(15,25)=15; A=16 produz X=1.",
                    "Mostra o arredondamento; a demo calcula E pela grade.",
                ),
                (
                    "Base hipotética E=60",
                    "L=15; com A=8, R=7 e F final=86,67%.",
                    "F depende de todas as aulas estarem resolvidas.",
                ),
            ],
            [4.0 * cm, 7.0 * cm, 6.0 * cm],
        )
    )
    section(
        s,
        "Reposições e carga horária",
        "Uma reposição conhecida no cadastro pode entrar como data adicional e aumenta E. Não existe comando de adicionar datas depois. Também não há campo de carga horária oficial para converter: o usuário informa diretamente o número de aulas de 50 min por encontro. Essa limitação precisa estar clara porque evita tratar um valor acadêmico não conferido como autoritativo.",
    )

    page(s, "05 · Modelo", "Classes e suas relações")
    s.append(
        P(
            "Figura 1 · Diagrama vetorial. Ligações superiores: associação; triângulo inferior: especialização.",
            "SmallX",
        )
    )
    s.append(class_diagram())
    s.append(
        table(
            ["Elemento", "Responsabilidade e estado", "Relação"],
            [
                (
                    "ControleAcademico",
                    "Coordena cadastro, agenda, recuperação e reset. Guarda coleções privadas.",
                    "Contém disciplinas e atividades.",
                ),
                (
                    "Disciplina",
                    "Valida grade e registro; mantém política e calcula resumo.",
                    "Contém registros; usa política.",
                ),
                (
                    "Registro",
                    "Valor imutável: data, aulas, situação e faltas. None indica pendência.",
                    "Um por data da grade.",
                ),
                (
                    "Atividade",
                    "Valor imutável: disciplina, data, tipo, título e ID local.",
                    "Vinculada à disciplina.",
                ),
                (
                    "PoliticaChamada",
                    "Classe abstrata com calcular_faltas(situação, aulas).",
                    "Contrato comum.",
                ),
                (
                    "ChamadaUnica e ChamadaDupla",
                    "Especializações que implementam regras diferentes para atraso/saída.",
                    "Herança e polimorfismo.",
                ),
            ],
            [4.1 * cm, 8.8 * cm, 4.1 * cm],
        )
    )
    section(
        s,
        "Encapsulamento e alteração controlada",
        "Código, chamadas e registros são expostos por propriedades de leitura. A coleção sai como tupla; Registro e Atividade são imutáveis. Em modo SQLite, cadastro, busca e lista devolvem a mesma fachada persistente: registrar presença ou mudar o nome por qualquer desses caminhos grava antes de alterar a memória. <b>Nome</b> é validado; não há setter para faltas, data, código ou título, pois uma alteração direta contornaria as regras ou a chave no banco. Presenças e atividades passam por operações próprias que validam e persistem antes de publicar a mudança.",
    )

    page(s, "06 · Interações", "Sequências do fluxo central")
    section(
        s,
        "F01 · Cadastro desde um banco vazio",
        "O menu converte as datas. ControleAcademico constrói Disciplina, que valida todos os campos antes da gravação. O banco insere disciplina e registros pendentes na mesma transação. O controle só inclui o objeto na memória após o commit. Por isso uma falha não deixa uma grade pela metade.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "dados da disciplina"),
                (1, 2, "criar_disciplina"),
                (2, 3, "validar + montar grade"),
                (2, 4, "INSERT + COMMIT"),
                (2, 1, "disciplina criada"),
                (1, 0, "resumo inicial"),
            ]
        )
    )
    section(
        s,
        "F02/F03 · Registrar ou corrigir",
        "O controle localiza a disciplina; ela valida data e situação. F02 exige pendência; F03 usa corrigir=True para substituir um valor resolvido. A política calcula faltas; o novo Registro é salvo antes de trocar o valor em memória. O resumo é derivado dos registros vigentes. Se o SQLite falhar, grade e resumo ficam iguais.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "data + situação"),
                (1, 2, "obter_disciplina"),
                (2, 1, "fachada persistente"),
                (1, 3, "registrar_presenca"),
                (3, 4, "calcular_faltas"),
                (3, 5, "UPSERT + COMMIT"),
                (3, 1, "novo registro"),
                (1, 0, "resumo"),
            ],
            ["Estudante", "Menu", "Controle", "Disciplina", "Política", "SQLite"],
        )
    )

    page(s, "07 · Implementação", "Camadas, banco e reprodução")
    section(
        s,
        "F05 · Salvar atividade sem mexer na frequência",
        "O menu converte a data; o controle verifica a disciplina e constrói uma Atividade válida. A escrita no SQLite termina antes de adicionar o objeto à agenda em memória. F06 ordena o que foi salvo. Um erro em qualquer validação ou na escrita não altera a agenda nem a grade de frequência.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "data + tipo + título"),
                (1, 2, "adicionar_atividade"),
                (2, 3, "validar objeto"),
                (2, 4, "INSERT + COMMIT"),
                (2, 1, "atividade salva"),
                (1, 0, "confirmação"),
            ],
            ["Estudante", "Menu", "Controle", "Atividade", "SQLite"],
        )
    )
    s.append(
        table(
            ["Camada", "Arquivo", "Papel"],
            [
                (
                    "Apresentação",
                    "demo/web/ e web.py",
                    "HTML/CSS/JS mostram os dados; web.py converte pedidos locais em operações de domínio e devolve resultados.",
                ),
                (
                    "Apresentação alternativa",
                    "demo/main.py",
                    "Menu de terminal que usa o mesmo controle e o mesmo banco.",
                ),
                (
                    "Negócio",
                    "demo/models.py",
                    "Valida regras, mantém objetos e calcula faltas pela política de chamada.",
                ),
                (
                    "Dados",
                    "demo/database.py",
                    "Cria tabelas e executa gravações e limpeza em transações.",
                ),
            ],
            [3.1 * cm, 4.3 * cm, 9.6 * cm],
        )
    )
    section(
        s,
        "Estrutura persistida",
        "<b>disciplinas:</b> código como chave, nome, chamadas e aulas por encontro. <b>registros:</b> chave composta código/data ISO, situação e faltas; chave estrangeira aponta para disciplina. <b>atividades:</b> ID gerado pelo banco, código, data ISO, tipo e título. A transação salva disciplina e grade juntas; o reset apaga as três tabelas na mesma transação. Um registro ou atividade só chega à memória após o commit. Totais não são gravados: vêm da grade atual, evitando divergências.",
    )

    page(s, "08 · Interações", "Escolha de disciplina e reinício")
    section(
        s,
        "Escolha pela lista, sem memorizar código",
        "As ações Registrar, Consultar, Corrigir, Adicionar atividade e Renomear chamam a mesma seleção em main.py. O menu ordena nomes, mostra um número para cada disciplina e deixa o código entre parênteses. Número inválido informa o erro; 0 volta ao menu. Nenhum desses caminhos escreve no banco antes da escolha e da operação válida.",
    )
    section(
        s,
        "F08 · Apagar dados confirmados",
        "A opção 8 pede a palavra exata APAGAR. Outra resposta cancela sem chamar o controle. Com a confirmação, ControleAcademico pede ao SQLite que apague atividades, registros e disciplinas na mesma transação. Somente depois do commit limpa as coleções em memória. Se o segundo DELETE falhar, o rollback recupera a atividade apagada no primeiro e a memória não muda.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "8 + APAGAR"),
                (1, 2, "apagar_tudo"),
                (2, 3, "DELETEs + COMMIT"),
                (3, 2, "confirmado"),
                (2, 1, "coleções vazias"),
                (1, 0, "dados apagados"),
            ],
            ["Estudante", "Menu", "Controle", "SQLite"],
        )
    )
    s.append(
        table(
            ["Entrada", "Efeito no banco", "Efeito na memória e no menu"],
            [
                (
                    "APAGAR",
                    "Três tabelas limpas em uma transação.",
                    "Coleções vazias; novo cadastro permitido.",
                ),
                (
                    "Enter ou outra palavra",
                    "Nenhum comando DELETE.",
                    "Tudo permanece; volta ao menu.",
                ),
                (
                    "Falha SQL após o primeiro DELETE",
                    "Rollback restaura todas as linhas.",
                    "Tudo permanece; mostra erro sem fingir sucesso.",
                ),
            ],
            [4.1 * cm, 6.3 * cm, 6.6 * cm],
        )
    )

    page(s, "09 · Interface", "Navegador local, lógica em Python")
    section(
        s,
        "O que o navegador faz",
        "A página HTML oferece três áreas: Disciplinas, Agenda e Ajustes. Em Disciplinas, a lista mostra nomes e a seleção abre os encontros, a barra de frequência e as atividades daquela matéria. O botão Registrar resolve uma data pendente; depois se torna Corrigir. Agenda lista provas e trabalhos por data. Ajustes permite zerar esta demo após a confirmação APAGAR. A página não calcula faltas, não escreve SQL e não guarda uma segunda cópia dos dados.",
    )
    section(
        s,
        "Caminho de uma ação",
        "O navegador envia JSON ao servidor HTTP de web.py, restrito a 127.0.0.1. O servidor converte a data em date e chama ControleAcademico; Disciplina valida e calcula, e database.py persiste em SQLite. A resposta contém o estado reconstruído pelo domínio. Se a validação rejeitar a entrada, a interface mostra o motivo e o banco permanece igual. Atualizar ou reabrir a página consulta o mesmo arquivo. Nenhum serviço externo é necessário.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "escolhe data e situação"),
                (1, 2, "POST /api/registros"),
                (2, 3, "registrar_presenca"),
                (3, 4, "validar + salvar"),
                (4, 3, "commit"),
                (3, 2, "resumo recalculado"),
                (2, 1, "JSON atualizado"),
                (1, 0, "linha e saldo visíveis"),
            ],
            ["Estudante", "HTML/JS", "web.py", "Domínio", "SQLite"],
        )
    )
    s.append(
        table(
            ["Ação visível", "Funções", "Comportamento verificável"],
            [
                (
                    "Criar / corrigir data",
                    "F01",
                    "Datas entram pendentes; correção conserva presença e faltas.",
                ),
                (
                    "Registrar / Corrigir",
                    "F02–F04",
                    "Linha muda; saldo vem do resumo em Python.",
                ),
                (
                    "Atividades e Agenda",
                    "F05–F06",
                    "Prova/trabalho vinculado aparece por data.",
                ),
                (
                    "Renomear / Apagar",
                    "F07–F08",
                    "Nome muda sem perder registros; reset exige APAGAR.",
                ),
            ],
            [4.5 * cm, 2.1 * cm, 10.4 * cm],
        )
    )

    page(s, "10 · Execução", "Demonstração, testes e limites")
    section(
        s,
        "Como reproduzir",
        "Requer Python 3.11+; só biblioteca padrão. Extraia o ZIP, entre em demo/, rode <b>python web.py</b> e abra http://127.0.0.1:8878. Crie DEMO01 com duas chamadas, duas aulas por encontro e datas 02, 04, 09 e 11/11/2026. Escolha a matéria pelo nome. Marque 02/11 ausente, 04/11 presente, consulte e corrija 02/11. Em 02/11, use Corrigir data para 03/11: a presença permanece. Atualize a página para conferir. Em Ajustes, APAGAR reinicia os dados. O menu alternativo inicia com <b>python main.py</b>.",
    )
    s.append(
        table(
            ["Passo", "Ação na página", "Resultado esperado"],
            [
                (
                    "1",
                    "Criar DEMO01 e quatro datas, duas aulas cada.",
                    "E=8; quatro datas pendentes; L=2.",
                ),
                (
                    "2",
                    "Registrar ausência em 02/11 e presença em 04/11.",
                    "A=2; R=0; ainda há quatro aulas pendentes.",
                ),
                ("3", "Consultar DEMO01.", "Mostra as duas situações e F pendente."),
                ("4", "Corrigir 02/11 para presente.", "A=0; R=2; não duplica a data."),
                (
                    "5",
                    "Adicionar prova P1 em 10/11 e ver agenda.",
                    "P1 aparece; faltas continuam iguais.",
                ),
                (
                    "6",
                    "Renomear para Disciplina de exemplo.",
                    "Só o nome muda; código, grade e faltas seguem iguais.",
                ),
                (
                    "7",
                    "Sair e iniciar novamente.",
                    "Nome, correção e prova recuperados do SQLite.",
                ),
            ],
            [1.6 * cm, 7.0 * cm, 8.4 * cm],
        )
    )
    section(
        s,
        "Teste e limitações",
        "Em demo/, execute <b>python -m unittest discover -v</b>. Cada teste constrói objetos próprios ou SQLite temporário; o banco de demonstração não é alterado. A grade tem um encontro por data, duração fixa e nenhuma inclusão posterior de datas. Não há edição de atividades nem conexão oficial. Este pacote é independente do aplicativo ampliado e não precisa de conta ou internet.",
    )
    section(
        s,
        "Mapa entre funções e código",
        "F01, F04, F05, F07 e F08 passam por ControleAcademico em models.py; F02 e F03 passam por Disciplina.registrar_presenca e pela política de chamada; F06 lê ControleAcademico.atividades. A página em web/ e web.py apenas apresenta e encaminha ações; main.py é a alternativa de terminal. Gravação, limpeza e recuperação usam database.py. O PDF de verificação relaciona funções, cenários e testes.",
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verification():
    s = []
    page(s, "Quinta etapa · Verificação", "Frequência UFMG · Verificação")
    s.append(
        P(
            "Eduardo Henrique Rodrigues Silva  |  APPOO 2026/2  |  " + VERSION,
            "SubtitleX",
        )
    )
    section(
        s,
        "Método",
        "As tabelas verificam F01–F08 do relatório do produto. Cada linha fixa uma entrada concreta, estado esperado, estado observado e evidência. Os testes são independentes: criam objetos novos ou um SQLite temporário, sem tocar no banco da demonstração. Rode <b>cd demo</b> e <b>python -m unittest discover -v</b>. A transcrição integral da última execução fica em <b>evidencias/unittest.txt</b> no ZIP.",
    )
    s.append(
        table(
            ["Critério", "Como foi verificado"],
            [
                (
                    "Rastreabilidade",
                    "O mesmo identificador de versão aparece nos dois PDFs, no README e no ZIP.",
                ),
                (
                    "Rejeições",
                    "Testes comparam cadastro, grade, agenda ou resumo antes e depois.",
                ),
                (
                    "Persistência",
                    "Um novo ControleAcademico reabre o mesmo banco temporário.",
                ),
                (
                    "Falha de escrita",
                    "Mock produz OSError antes de publicar em memória; o banco é reaberto.",
                ),
                ("Menu", "Entradas simuladas percorrem o sistema desde o banco vazio."),
            ],
            [5 * cm, 21.1 * cm],
        )
    )
    section(
        s,
        "Convenções",
        "E = aulas elegíveis; A = faltas usadas; L = limite; R = saldo. Pendente é um encontro não resolvido. Aprovado significa que o teste citado passou na última execução e confirmou o estado da linha. A seção Evidências liga T01–T22 aos nomes dos testes; a seção Interface verifica o caminho pelo navegador.",
    )

    def matrix(title, initial, rows, *, new_page=True):
        if new_page:
            page(s, "Matriz de cenários", title, initial)
        else:
            s.append(Spacer(1, 0.15 * cm))
            section(s, title, initial)
        s.append(
            table(
                [
                    "ID",
                    "Regra e entrada",
                    "Resultado e estado esperados",
                    "Resultado e estado observados",
                    "Situação",
                    "Evidência",
                ],
                rows,
                [1.4 * cm, 6.1 * cm, 6.1 * cm, 6.1 * cm, 2 * cm, 4.4 * cm],
                dense="tight",
            )
        )

    matrix(
        "F01 · Cadastrar disciplina",
        "Estado inicial: controle vazio e, quando usado, SQLite temporário vazio. Datas fictícias 02, 04, 09 e 11/11/2026; cada cenário recria esse estado, salvo preparação indicada na linha.",
        [
            (
                "C01",
                "DEMO01, duas chamadas, duas aulas de 50 min e quatro datas válidas.",
                "Cria uma disciplina; quatro pendências; E=8, A=0, L=2.",
                "Código normalizado para DEMO01; quatro pendências; E=8, A=0, L=2.",
                "Aprovado",
                "T01",
            ),
            (
                "C02",
                "Após C01, tenta cadastrar demo01 de novo com outro nome.",
                "Rejeita duplicado; nome, grade, presenças e totais intactos.",
                "ValueError; disciplina, registros e resumo iguais ao anterior.",
                "Aprovado",
                "T02",
            ),
            (
                "C03a",
                "Código vazio; demais dados válidos.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03b",
                "Nome vazio; demais dados válidos.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03c",
                "Três chamadas; demais dados válidos.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03d",
                "Três aulas por encontro; demais dados válidos.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03e",
                "Duas chamadas em encontro de uma aula.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03f",
                "Grade sem nenhuma data.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03g",
                "Repete 02/11 na grade.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03h",
                "Envia data em texto diretamente ao domínio.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C03i",
                "No menu, tenta informar 31/02/2026.",
                "Informa data inválida; cadastro vazio.",
                "Menu informou rejeição e não criou disciplina.",
                "Aprovado",
                "T16",
            ),
            (
                "C03j",
                "Envia grade None diretamente ao domínio.",
                "Rejeita; cadastro e grade vazios.",
                "ValueError; controle vazio.",
                "Aprovado",
                "T03",
            ),
            (
                "C04",
                "Cria disciplina e presença em SQLite temporário; fecha e reabre.",
                "Nome, grade e presença recuperados sem duplicação.",
                "Novo controle recuperou nome e registro presente na data.",
                "Aprovado",
                "T04",
            ),
            (
                "C04A",
                "Gatilho SQL falha no segundo INSERT da grade, após inserir disciplina.",
                "Rollback de cadastro e datas; controle e SQLite vazios.",
                "IntegrityError; memória e banco reaberto sem disciplina.",
                "Aprovado",
                "T15",
            ),
        ],
    )

    matrix(
        "F02 · Registrar frequência",
        "Estado inicial: C05 usa DEMO01 com quatro datas pendentes, duas aulas e duas chamadas; C06–C07 usam D com a mesma grade. C08 recria D com uma data de quatro aulas; C09 usa bancos temporários próprios.",
        [
            (
                "C05",
                "Marca 02/11 presente e 04/11 ausente.",
                "Faltas 0 e 2; A=2, E=8, L=2, R=0; quatro aulas pendentes.",
                "Registros 0 e 2; resumo confirmou A=2, E=8, L=2, R=0, pendências=4.",
                "Aprovado",
                "T01",
            ),
            (
                "C06a",
                "Registra 01/12, fora da grade de D.",
                "Rejeita; grade e resumo iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T05",
            ),
            (
                "C06b",
                "Envia 02/11 como texto diretamente ao domínio.",
                "Rejeita; grade e resumo iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T05",
            ),
            (
                "C06c",
                "Em 02/11, informa situação errada.",
                "Rejeita; grade e resumo iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T05",
            ),
            (
                "C07",
                "Após registrar ausência, tenta registrar presença na mesma data sem Corrigir.",
                "Rejeita; ausência original e resumo permanecem.",
                "ValueError; registro original e resumo iguais ao antes.",
                "Aprovado",
                "T05",
            ),
            (
                "C08a",
                "D, quatro aulas, uma chamada; atrasado.",
                "Resolve com 0 faltas.",
                "Registro mostrou 0 faltas.",
                "Aprovado",
                "T06",
            ),
            (
                "C08b",
                "D, quatro aulas, uma chamada; saiu mais cedo.",
                "Resolve com 0 faltas.",
                "Registro mostrou 0 faltas.",
                "Aprovado",
                "T06",
            ),
            (
                "C08c",
                "D, quatro aulas, duas chamadas; atrasado.",
                "Resolve com 2 faltas.",
                "Registro mostrou 2 faltas.",
                "Aprovado",
                "T06",
            ),
            (
                "C08d",
                "D, quatro aulas, duas chamadas; saiu mais cedo.",
                "Resolve com 2 faltas.",
                "Registro mostrou 2 faltas.",
                "Aprovado",
                "T06",
            ),
            (
                "C09a",
                "DB02: OSError ao salvar ausência no SQLite.",
                "Registro pendente na memória e no banco; A=0.",
                "OSError; reabertura preservou pendente; resumo igual.",
                "Aprovado",
                "T07",
            ),
            (
                "C09b",
                "DEMO01: falha de escrita durante o registro pelo menu.",
                "Informa erro; registro pendente no banco.",
                "Menu informou falha e reabertura mostrou pendente.",
                "Aprovado",
                "T19",
            ),
        ],
    )

    matrix(
        "F03 · Corrigir frequência",
        "Estado inicial: C10–C11 usam D com quatro encontros de duas aulas e duas ausências nas primeiras datas; C12 cria D pendente e prepara uma ausência somente onde indicado.",
        [
            (
                "C10",
                "Corrige 02/11 de ausente para presente.",
                "Só esse registro muda; A cai de 4 para 2; excesso cai de 2 para 0.",
                "A caiu para 2; primeiro registro foi substituído sem duplicação.",
                "Aprovado",
                "T08",
            ),
            (
                "C11",
                "Corrige segunda ausência; marca 09/11 sem chamada e 11/11 cancelada.",
                "E=6, A=0, L=1, R=1, pendências=0, F=100%.",
                "Resumo confirmou E=6, A=0, L=1, R=1 e F=100%.",
                "Aprovado",
                "T08",
            ),
            (
                "C12a",
                "D pendente: tenta Corrigir 02/11 para presente.",
                "Rejeita; grade e resumo pendentes iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T09",
            ),
            (
                "C12b",
                "Registra ausência em 02/11; tenta corrigir para situação desconhecida.",
                "Rejeita; ausência, grade e resumo iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T09",
            ),
            (
                "C12c",
                "Com ausência em 02/11, tenta Corrigir 01/12 fora da grade.",
                "Rejeita; ausência, grade e resumo iguais.",
                "ValueError; registros e resumo iguais.",
                "Aprovado",
                "T09",
            ),
        ],
    )

    matrix(
        "F04 · Consultar frequência",
        "Estado inicial: C13–C15 usam D com quatro datas; OUTRA não existe. C15a–c usam CIR01 e FIS01 no menu. Consultas não gravam dados.",
        [
            (
                "C13",
                "Consulta código existente em minúsculas.",
                "Mesma disciplina, grade e resumo; nenhum registro muda.",
                "Resumo, registros e cadastro iguais ao anterior.",
                "Aprovado",
                "T10",
            ),
            (
                "C14",
                "Consulta OUTRA, não cadastrada.",
                "Informa não encontrada; estado igual.",
                "ValueError; cadastro e totais iguais.",
                "Aprovado",
                "T10",
            ),
            (
                "C14b",
                "Consulta com código None no domínio.",
                "Pede código; estado igual.",
                "ValueError; cadastro e totais iguais.",
                "Aprovado",
                "T10",
            ),
            (
                "C14c",
                "Consulta com código vazio no domínio.",
                "Pede código; estado igual.",
                "ValueError; cadastro e totais iguais.",
                "Aprovado",
                "T10",
            ),
            (
                "C15",
                "No menu, cadastra, registra, consulta e corrige desde banco vazio.",
                "Mostra limite e saldo em aulas, excesso e percentual por etapa.",
                "Saída identificou aulas, excesso, F pendente, 50% e depois 100%.",
                "Aprovado",
                "T11",
            ),
            (
                "C15a",
                "Com duas disciplinas, escolhe número 2 na lista por nome.",
                "Consulta Fisica; cadastro e totais iguais.",
                "Menu mostrou Fisica; cadastro manteve dois itens.",
                "Aprovado",
                "T20",
            ),
            (
                "C15b",
                "Na lista, informa abc em vez de número.",
                "Pede número válido; estado igual.",
                "Menu rejeitou; cadastro manteve dois itens.",
                "Aprovado",
                "T20",
            ),
            (
                "C15c",
                "Na lista, escolhe 0 para voltar ao menu.",
                "Não consulta nem altera dados.",
                "Voltou ao menu; cadastro manteve dois itens.",
                "Aprovado",
                "T20",
            ),
        ],
    )

    matrix(
        "F05 · Agendar atividade",
        "Estado inicial: C16, C17 e C18 usam DEMO01 com quatro registros pendentes; C16b usa o menu com uma data pendente. A agenda começa vazia e a atividade pode cair fora de uma data de aula.",
        [
            (
                "C16",
                "Adiciona prova P1 em 03/11, fora das datas de aula, e reabre SQLite temporário.",
                "Atividade ligada a DEMO01 persiste; grade e resumo iguais.",
                "Novo controle recuperou atividade; registros e resumo iguais ao antes.",
                "Aprovado",
                "T12",
            ),
            (
                "C16b",
                "No menu, adiciona trabalho Relatório em 05/11 e reabre.",
                "Trabalho fica vinculado a DEMO01 e persiste na agenda.",
                "Menu salvou o trabalho; após reabrir, agenda ainda o lista.",
                "Aprovado",
                "T14",
            ),
            (
                "C17a",
                "Associa prova ao código OUTRA, não cadastrado.",
                "Rejeita; agenda, grade e resumo iguais.",
                "ValueError; agenda vazia; resumo igual.",
                "Aprovado",
                "T13",
            ),
            (
                "C17b",
                "Informa data 02/11 como texto ao domínio.",
                "Rejeita; agenda, grade e resumo iguais.",
                "ValueError; agenda vazia; resumo igual.",
                "Aprovado",
                "T13",
            ),
            (
                "C17c",
                "Escolhe tipo seminário em vez de prova/trabalho.",
                "Rejeita; agenda, grade e resumo iguais.",
                "ValueError; agenda vazia; resumo igual.",
                "Aprovado",
                "T13",
            ),
            (
                "C17d",
                "Informa título só com espaços.",
                "Rejeita; agenda, grade e resumo iguais.",
                "ValueError; agenda vazia; resumo igual.",
                "Aprovado",
                "T13",
            ),
            (
                "C18",
                "Simula OSError ao salvar prova válida.",
                "Agenda vazia na memória e banco reaberto; frequência intocada.",
                "OSError; agenda vazia na memória e no banco, registros e resumo iguais.",
                "Aprovado",
                "T13",
            ),
        ],
    )

    matrix(
        "F06 · Consultar agenda",
        "Estado inicial: C19 começa com agenda vazia; C20 cria DEMO01 e três atividades fictícias. O teste de menu usa banco temporário próprio.",
        [
            (
                "C19",
                "Escolhe Ver agenda sem criar atividade.",
                "Informa Agenda vazia; não cria item.",
                "Saída do menu contém Agenda vazia; cadastro prosseguiu.",
                "Aprovado",
                "T14",
            ),
            (
                "C20a",
                "Insere trabalho de 05/11; depois prova e trabalho de 03/11; consulta.",
                "Ordena por data; no empate, mantém ordem de inserção.",
                "Linhas com nome da disciplina: 03/11 prova, 03/11 trabalho, 05/11 trabalho nessa ordem.",
                "Aprovado",
                "T14",
            ),
            (
                "C20b",
                "Fecha, reabre e consulta a mesma agenda.",
                "As três atividades reaparecem na mesma ordem.",
                "Menu reaberto listou as três linhas na mesma ordem.",
                "Aprovado",
                "T14",
            ),
        ],
        new_page=False,
    )

    matrix(
        "F07 · Renomear disciplina",
        "Estado inicial: DEMO01 com quatro encontros. C21 prepara uma ausência e uma prova antes de renomear; C22–C23 começam com nome Original. Cada teste usa SQLite temporário próprio.",
        [
            (
                "C21",
                "Após ausência e prova, muda o nome pela fachada e pelo controle; reabre.",
                "Novo nome persiste; código, grade, faltas e prova não mudam.",
                "Nome novo após reabrir; registros, resumo e atividade iguais aos anteriores.",
                "Aprovado",
                "T17",
            ),
            (
                "C22a",
                "Tenta renomear código OUTRA, não cadastrado.",
                "Rejeita; DEMO01 fica Original na memória e no banco.",
                "ValueError; reabertura mostrou Original.",
                "Aprovado",
                "T18",
            ),
            (
                "C22b",
                "Informa novo nome vazio.",
                "Rejeita; Original na memória e no banco.",
                "ValueError no controle e setter; reabertura mostrou Original.",
                "Aprovado",
                "T18",
            ),
            (
                "C22c",
                "Informa novo nome só com espaços.",
                "Rejeita; Original na memória e no banco.",
                "ValueError no controle e setter; reabertura mostrou Original.",
                "Aprovado",
                "T18",
            ),
            (
                "C22d",
                "Informa novo nome None.",
                "Rejeita; Original na memória e no banco.",
                "ValueError no controle e setter; reabertura mostrou Original.",
                "Aprovado",
                "T18",
            ),
            (
                "C23a",
                "OSError ao renomear pelo controle.",
                "Original na memória e no banco reaberto.",
                "OSError; memória e SQLite conservaram Original.",
                "Aprovado",
                "T18",
            ),
            (
                "C23b",
                "OSError ao renomear pelo setter da fachada.",
                "Original na memória e no banco reaberto.",
                "OSError; memória e SQLite conservaram Original.",
                "Aprovado",
                "T18",
            ),
        ],
    )
    section(
        s,
        "Por que o nome muda sem afetar frequência",
        "O menu mostra nomes numerados para escolher a disciplina e lê o novo nome. O controle valida ambos antes de escrever; entrada inválida encerra com o nome antigo. O SQLite confirma o UPDATE antes de o setter da Disciplina receber o novo nome. Se a escrita falhar, a memória permanece igual. Código, grade, atividades e faltas não entram na operação. T17 e T18 verificam essa ordem.",
    )

    matrix(
        "F08 · Recomeçar do zero",
        "Estado inicial: D tem uma ausência e a prova P1 em SQLite temporário. C24–C26 percorrem o menu; C27 usa uma falha SQL no segundo DELETE. Cada teste tem banco próprio.",
        [
            (
                "C24",
                "Escolhe 8 e deixa a confirmação vazia.",
                "Cancela; disciplina, ausência e P1 continuam.",
                "Menu informou cancelamento; consulta ainda mostrou duas faltas.",
                "Aprovado",
                "T21",
            ),
            (
                "C25",
                "Escolhe 8 e responde NÃO em vez de APAGAR.",
                "Cancela; disciplina, ausência e P1 continuam.",
                "Menu informou cancelamento; consulta ainda mostrou duas faltas.",
                "Aprovado",
                "T21",
            ),
            (
                "C26",
                "Escolhe 8, digita APAGAR e reabre o SQLite.",
                "Cadastro, registros e agenda vazios; pode reutilizar D.",
                "Memória e banco reaberto vazios; D foi cadastrado de novo.",
                "Aprovado",
                "T21, T22",
            ),
            (
                "C27",
                "O segundo DELETE falha após apagar atividades.",
                "Rollback; memória, banco, falta e P1 intactos.",
                "IntegrityError; reabertura mostrou falta e P1 originais.",
                "Aprovado",
                "T22",
            ),
        ],
    )

    page(s, "Interface", "Verificação do navegador local")
    section(
        s,
        "O mesmo domínio nas duas apresentações",
        "T23 inicia o servidor local com SQLite temporário, carrega HTML/CSS/JS, cria disciplina, registra ausência, corrige para presença, corrige a data do encontro, adiciona prova, renomeia, reabre e apaga com APAGAR. T24 envia data fora da grade, data inválida e confirmação errada; cada pedido é rejeitado e a leitura seguinte preserva o estado. T25 cobre falhas de leitura e gravação; T26 verifica a inicialização e o encerramento. T27–T28 isolam a correção da data no domínio e no SQLite.",
    )
    s.append(
        table(
            ["ID", "Caminho percorrido", "Esperado e observado", "Evidência"],
            [
                (
                    "W01",
                    "Criar DEMO01 com quatro encontros, registrar ausência e corrigir para presença.",
                    "Cadastro disponível; faltas 2 e depois 0; correção substitui o registro.",
                    "T23 · aprovado",
                ),
                (
                    "W02",
                    "Adicionar P1, renomear e consultar em novo pedido.",
                    "P1 segue vinculada ao novo nome; registro e agenda persistem no SQLite.",
                    "T23 · aprovado",
                ),
                (
                    "W03",
                    "Digitar APAGAR e consultar novamente.",
                    "Disciplinas e atividades vazias no banco reaberto.",
                    "T23 · aprovado",
                ),
                (
                    "W04",
                    "Enviar entradas inválidas e uma confirmação diferente de APAGAR.",
                    "Erro específico; registros, totais e atividades inalterados.",
                    "T24 · aprovado",
                ),
                (
                    "W05",
                    "Simular falha de SQLite na leitura/gravação, restaurar acesso e encerrar.",
                    "Erro persistente, Tentar novamente recupera a página; encerramento controlado.",
                    "T25–T26 e Chrome · aprovado",
                ),
                (
                    "W06",
                    "Registrar uma ausência, corrigir só a data, reabrir; tentar data inválida e colisão.",
                    "Situação e faltas preservadas; rejeições não alteram o estado.",
                    "T23–T24, T27–T28 · aprovado",
                ),
            ],
            [1.5 * cm, 9.0 * cm, 11.3 * cm, 4.5 * cm],
            dense="tight",
        )
    )
    section(
        s,
        "Limite desta evidência",
        "T23–T25 percorrem pedidos HTTP reais com banco isolado; T26 verifica a entrada do programa; T27–T28 cobrem troca de data, colisão e falha de disco. Uma conferência adicional em Chrome verificou larguras de 390 e 320 px, criação sem botão intermediário para a data, registro, correções, agenda, navegação após recarregar, títulos longos e recuperação de falha inicial de leitura. A aparência não altera os cálculos: o servidor devolve números das classes Python. Serviços externos do aplicativo completo não fazem parte deste recorte.",
    )

    page(s, "Evidências", "Testes e defeitos corrigidos")
    section(
        s,
        "Evidências · IDs da matriz e nomes dos testes",
        "T01–T22 apontam para domínio e terminal; T23–T26 verificam a interface local; T27–T28 aprofundam a correção de data. Todos constam em evidencias/unittest.txt no ZIP. A situação da matriz descreve a última execução, não apenas uma intenção de teste.",
    )
    tests = [
        ("T01", "test_criar_e_registrar_do_zero"),
        ("T02", "test_codigo_duplicado_preserva_cadastro_e_frequencia"),
        ("T03", "test_entrada_invalida_nao_cria_disciplina"),
        ("T04", "test_sqlite_preserva_disciplina_entre_aberturas"),
        ("T05", "test_registro_invalido_nao_muda_grade_nem_totais"),
        ("T06", "test_mesma_operacao_tem_resultado_conforme_chamada"),
        ("T07", "test_falha_na_gravacao_preserva_memoria_e_banco"),
        ("T08", "test_correcao_substitui_e_recalcula"),
        ("T09", "test_correcao_invalida_preserva_registro_e_resumo"),
        ("T10", "test_consulta_nao_altera_registros"),
        ("T11", "test_fluxo_completo_sem_dados_preparados"),
        ("T12", "test_atividade_valida_persiste_sem_alterar_frequencia"),
        ("T13", "test_atividade_invalida_e_falha_de_escrita_preservam_agenda"),
        ("T14", "test_agenda_pelo_menu_vazia_e_atividades_ordenadas"),
        ("T15", "test_falha_no_segundo_insert_desfaz_cadastro_e_grade"),
        ("T16", "test_rejeicoes_e_conversoes_sao_tratadas"),
        ("T17", "test_renomear_disciplina_valida_e_persiste"),
        ("T18", "test_renomear_invalido_ou_falha_de_banco_preserva_nome"),
        ("T19", "test_falha_de_gravacao_mostra_erro_e_mantem_aula_pendente"),
        ("T20", "test_escolha_numerada_por_nome_e_volta_sem_alterar"),
        ("T21", "test_reset_cancelado_e_confirmado_pelo_menu"),
        ("T22", "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar"),
        ("T23", "test_fluxo_completo_e_reabertura"),
        ("T24", "test_entradas_invalidas_preservam_estado"),
        ("T25", "test_falhas_de_leitura_e_gravacao_sao_visiveis"),
        ("T26", "test_ponto_de_entrada_pode_ser_encerrado"),
        ("T27", "test_remarcar_encontro_preserva_presenca_e_rejeita_colisao"),
        ("T28", "test_remarcar_persistente_e_falha_na_gravacao"),
    ]
    middle = (len(tests) + 1) // 2
    s.append(
        table(
            ["ID", "Método unittest", "ID", "Método unittest"],
            [
                (
                    tests[i][0],
                    tests[i][1],
                    tests[i + middle][0] if i + middle < len(tests) else "",
                    tests[i + middle][1] if i + middle < len(tests) else "",
                )
                for i in range(middle)
            ],
            [1.2 * cm, 11.85 * cm, 1.2 * cm, 11.85 * cm],
            dense="tight",
        )
    )
    section(
        s,
        "Defeitos identificados e corrigidos",
        "Uma versão sem fachada persistente perdia presença após reabertura e podia alterar só o nome em memória. Cadastro, busca e lista agora usam a fachada; o setter grava antes de mudar o objeto (T04, T11, T17 e T18). Também havia risco de publicar ausência antes do commit: uma falha de escrita deixaria a tela e o banco divergentes. O registro agora é trocado apenas após a gravação (T07 e T19). T20 confirma a escolha por nome no menu, sem memorizar código. Cada correção foi seguida pela repetição dos cenários relacionados.",
    )
    page(s, "Última execução", "Evidência integral dos testes")
    section(
        s,
        "Como repetir sem dados reais",
        "O ZIP inclui demo/test_models.py, demo/test_main.py, demo/test_web.py, demo/README.md e evidencias/unittest.txt. Extraia, entre em demo/ e rode <b>python -m unittest discover -v</b>. Os testes não exigem conta, internet, Moodle ou GPS. Para operar, rode <b>python web.py</b> e abra http://127.0.0.1:8878; o menu alternativo é <b>python main.py</b>.",
    )
    evidence_path = Path(__file__).parent / "package" / "evidencias" / "unittest.txt"
    evidence = evidence_path.read_text(encoding="utf-8-sig")
    lines = [line for line in evidence.splitlines() if line.startswith("test_")]
    if not lines or "OK" not in evidence:
        raise RuntimeError("A evidência de unittest precisa existir e terminar em OK.")
    observed = []
    for line in lines:
        name = line.split(" (")[0]
        status = line.rsplit("...", 1)[-1].strip()
        if status != "ok":
            raise RuntimeError("Há teste sem resultado aprovado: " + line)
        observed.append((name, status))
    paired = []
    middle = (len(observed) + 1) // 2
    for i in range(middle):
        other = observed[i + middle] if i + middle < len(observed) else ("", "")
        paired.append((observed[i][0], observed[i][1], other[0], other[1]))
    summary = next(
        (line for line in evidence.splitlines() if line.startswith("Ran ")), ""
    )
    section(
        s,
        "Resultado final",
        f"{summary}. O processo terminou com <b>OK</b>. A saída textual completa, "
        "incluindo a classe de cada teste, está em evidencias/unittest.txt no ZIP. "
        "Todos os cenários da matriz ficaram aprovados nesta rodada.",
    )
    evidence_table = table(
        ["Método executado", "Obs.", "Método executado", "Obs."],
        paired,
        [11.1 * cm, 1.95 * cm, 11.1 * cm, 1.95 * cm],
        dense="tight",
    )
    evidence_table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
            ]
        )
    )
    s.append(evidence_table)
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    product()
    verification()
