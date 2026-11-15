"""Produz relatórios acadêmicos diagramados a partir dos contratos da versão."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.graphics.shapes import Drawing, Rect, String, Line

BASE = Path(__file__).parent
NAVY = colors.HexColor("#17345A")
TEAL = colors.HexColor("#287985")
PALE = colors.HexColor("#EBF3F5")
pdfmetrics.registerFont(TTFont("ArialA", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialB", "C:/Windows/Fonts/arialbd.ttf"))
S = getSampleStyleSheet()
for name, size, lead, font, color, before, after in [
    ("TitleA", 22, 27, "ArialB", NAVY, 12, 16),
    ("SubA", 12, 17, "ArialA", TEAL, 0, 18),
    ("H1A", 13, 17, "ArialB", NAVY, 15, 7),
    ("H2A", 10, 14, "ArialB", TEAL, 11, 5),
    ("BodyA", 9.2, 13.5, "ArialA", colors.HexColor("#25303A"), 0, 7),
    ("CellA", 7.6, 10.4, "ArialA", colors.HexColor("#25303A"), 0, 0),
    ("HeadA", 7.6, 10.4, "ArialB", colors.white, 0, 0),
]:
    S.add(ParagraphStyle(name=name, fontName=font, fontSize=size, leading=lead,
        textColor=color, spaceBefore=before, spaceAfter=after))

def p(text, style="BodyA"):
    return Paragraph(text, S[style])

def t(headers, rows, widths):
    data = [[p(escape(v), "HeadA") for v in headers]]
    data += [[p(str(v), "CellA") for v in row] for row in rows]
    obj = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    obj.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, PALE]),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return obj

def header_footer(c, doc):
    c.saveState()
    c.setStrokeColor(TEAL)
    c.line(2*cm, A4[1]-1.5*cm, A4[0]-2*cm, A4[1]-1.5*cm)
    c.setFont("ArialA", 8)
    c.setFillColor(NAVY)
    c.drawString(2*cm, 1.35*cm, "Frequência UFMG  |  APPOO  |  2026/2")
    c.drawRightString(A4[0]-2*cm, 1.35*cm, str(doc.page))
    c.restoreState()

def build(file, story):
    SimpleDocTemplate(str(BASE/file), pagesize=A4, leftMargin=2*cm,
        rightMargin=2*cm, topMargin=2.1*cm, bottomMargin=2.1*cm).build(
        story, onFirstPage=header_footer, onLaterPages=header_footer)

def heading(story, title, body=None, small=False):
    story.append(p(title, "H2A" if small else "H1A"))
    if body:
        story.append(p(body))

def cover(story, subtitle):
    story += [Spacer(1, .5*cm), p("FREQUÊNCIA UFMG", "TitleA"),
        p(subtitle, "SubA"),
        p("Eduardo Henrique Rodrigues Silva  |  Projeto individual  |  Versão PF-01-SQLITE")]

def diagram(nodes):
    """Fluxo vetorial: permanece nítido em qualquer ampliação do PDF."""
    d = Drawing(480, 78)
    width = 90
    gap = (480 - len(nodes)*width) / max(1, len(nodes)-1)
    for i, label in enumerate(nodes):
        x = i*(width+gap)
        d.add(Rect(x, 27, width, 40, rx=5, ry=5, fillColor=PALE,
            strokeColor=TEAL, strokeWidth=1))
        d.add(String(x+width/2, 49, label, textAnchor='middle',
            fontName='ArialB', fontSize=8, fillColor=NAVY))
        if i < len(nodes)-1:
            d.add(Line(x+width+2, 47, x+width+gap-5, 47,
                strokeColor=TEAL, strokeWidth=1.2))
    return d

def product():
    s=[]
    cover(s, "Quarta etapa - Produto final")
    heading(s, "1. Problema e resultado",
        "Estudantes da UFMG precisam acompanhar as faltas antes da consolidação oficial. O sistema registra a situação de cada encontro e mostra o limite, as faltas usadas e o saldo. É um controle pessoal, não uma confirmação institucional de presença.")
    heading(s, "2. Escopo e evolução",
        "O protótipo já cadastrava grade, registrava e corrigia frequência e calculava o resumo, porém perdia os dados ao sair. O produto final integra essas operações com SQLite, preservando o estado após fechar e reabrir. A proposta inicial também mencionava autenticação, Moodle, localização e agenda; o recorte acadêmico foi reduzido ao núcleo manual para apresentar uma aplicação Python independente. O aplicativo completo permanece como extensão prática do mesmo problema.")
    s.append(t(["Função","Resultado para o estudante","Evolução"], [
        ("F01 Cadastro","Disciplina e datas pendentes.","Persistência integrada."),
        ("F02 Registro","Situação e faltas de uma data.","Persistência integrada."),
        ("F03 Correção","Substituição e novo resumo.","Persistência integrada."),
        ("F04 Consulta","Grade, limite, saldo e percentual.","Dados recuperados após reabrir."),
    ], [3.1*cm,7.2*cm,6.7*cm]))
    heading(s, "3. Contratos das funcionalidades")
    contracts=[
        ("F01 - Cadastro da disciplina",
         "Pré-condição: código ainda não cadastrado. Entrada: código, nome, 1 ou 2 chamadas, 1/2/4 aulas de 50 minutos por encontro, uma ou mais datas. Sucesso: normaliza o código, grava disciplina e datas pendentes na mesma transação. Rejeita campo vazio, tipos/valores inválidos, data repetida, código duplicado e 1 aula com 2 chamadas. Em rejeição, o cadastro anterior fica intacto."),
        ("F02 - Registro da situação",
         "Pré-condição: disciplina e data da grade existentes, registro pendente. Entrada: data e situação presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada. Sucesso: a política calcula faltas, o banco confirma a gravação e o objeto troca o registro. Rejeita data inexistente, situação inválida ou segundo registro sem correção. O estado anterior permanece."),
        ("F03 - Correção manual",
         "Pré-condição: disciplina e data da grade existentes. Entrada: nova situação. Sucesso: substitui o registro daquela data, recalcula os totais; não acumula faltas duplicadas. Rejeição preserva registro e resumo. A correção explícita pode desfazer um cancelamento ou uma marcação sem chamada."),
        ("F04 - Consulta",
         "Pré-condição: disciplina cadastrada. Entrada: código. Sucesso: mostra grade, base elegível, pendências, faltas, limite, saldo, excesso e percentual quando determinado. Código inexistente gera mensagem clara. A consulta não modifica dados."),
    ]
    for name, body in contracts: heading(s,name,body,True)
    heading(s, "4. Regras e exemplos numéricos",
        "Uma aula vale 50 minutos. Base E = soma das aulas não canceladas. Limite L = piso(E × 25%). Faltas A = soma das faltas resolvidas. Saldo = máximo(0, L − A); excesso = máximo(0, A − L). Pendências não viram presença nem falta. O percentual só aparece sem pendências e com E maior que zero: 100 × (E − A) / E.")
    s.append(t(["Caso","Cálculo","Interpretação"],[
        ("4 encontros de 2 aulas","E=8; L=2; 1 ausência: A=2","Saldo zero; percentual pendente se outras datas não resolvidas."),
        ("1 encontro cancelado","E=6; L=piso(1,5)=1","O limite cai; se A=2, excesso=1."),
        ("Atraso em 4 aulas","1 chamada: A=0; 2 chamadas: A=2","Mesma operação, políticas concretas diferentes."),
        ("Sem chamada","A=0 e encontro continua em E","Aula mantida sem penalizar o aluno."),
    ],[4.1*cm,4.9*cm,8*cm]))
    heading(s, "5. Modelo de classes atualizado")
    s.append(diagram(['Controle', 'Disciplina', 'Registro', 'Política']))
    s.append(t(["Classe","Estado e responsabilidade","Relação"],[
        ("ControleAcademico","Coleção privada de disciplinas; cadastro e recuperação.","Contém 0..* Disciplina."),
        ("Disciplina","Grade e registros privados; valida, substitui e resume.","Contém 1..* Registro e usa uma política."),
        ("Registro","Data, aulas, situação, faltas; valor imutável.","None indica pendência."),
        ("PoliticaChamada","Classe abstrata: calcular_faltas(situação, aulas).","Contrato para especializações."),
        ("ChamadaUnica / ChamadaDupla","Implementam o mesmo método com resultados diferentes.","Herança e polimorfismo."),
        ("Fachada persistente","Grava no banco antes da troca do estado em memória.","Liga domínio à camada de dados."),
    ],[4.2*cm,8.1*cm,4.7*cm]))
    s.append(p("Atributos são expostos por propriedades somente de leitura. Não há setter para faltas porque a mudança requer validar situação, data e política; registrar_presenca é a operação controlada."))
    heading(s, "6. Sequência principal: registro e correção")
    s.append(diagram(['Menu', 'Domínio', 'Política', 'SQLite']))
    s.append(t(["Ordem","Participante","Ação e retorno"],[
        ("1","Estudante → main.py","Informa código, data e situação."),
        ("2","Controle → Disciplina","Localiza disciplina; valida data e repetição."),
        ("3","Disciplina → Política","Calcula faltas e constrói novo Registro."),
        ("4","Fachada → SQLite","Grava e confirma transação; se falhar, não troca memória."),
        ("5","Disciplina → main.py","Substitui registro e devolve resumo recalculado."),
    ],[1.5*cm,5.0*cm,10.5*cm]))
    heading(s, "7. Camadas, base e execução",
        "main.py apresenta o menu e converte entradas. models.py reúne regras de negócio. database.py cria tabelas e executa SQL parametrizado. O par (código, data) identifica uma aula; o cadastro usa uma transação para disciplina e grade. Totais são derivados dos registros, sem duplicação no banco. O ZIP inclui banco inicial vazio e dados fictícios no roteiro. Python 3.11+, sem pacotes externos: em demo/, executar python main.py; testes: python -m unittest discover -v.")
    heading(s, "7.1 Estrutura persistida e recuperação",
        "A tabela disciplinas tem código como chave, nome, quantidade de chamadas e aulas por encontro. A tabela registros guarda código da disciplina, data ISO, situação e faltas; a chave composta (código, data) impede duplicação de uma data. No início, o controle lê as duas tabelas e reconstrói objetos Disciplina e Registro. Para registrar ou corrigir, a validação e o cálculo criam um novo valor; o SQL confirma a atualização e só depois a grade em memória é substituída. Assim, um erro de escrita não apresenta ao usuário um registro que não existe no banco.")
    heading(s, "7.2 Exemplo de uso completo",
        "No primeiro início, informe DEMO01, nome Disciplina de teste, duas chamadas, duas aulas por encontro e quatro datas: 02, 04, 09 e 11/11/2026. A base é oito aulas e o limite é duas. Marque ausência em 02/11 e presença em 04/11: são duas faltas usadas e ainda há quatro aulas pendentes, então o percentual permanece indeterminado. Corrija 02/11 para presença: as faltas voltam a zero. Feche e reabra o programa; a disciplina e a correção continuam disponíveis. Os dados são fictícios e podem ser reproduzidos no ZIP sem acesso à internet.")
    s.append(PageBreak())
    heading(s, "7.3 Falhas, rejeições e integridade",
        "A conversão de data no menu exige DD/MM/AAAA e rejeita, por exemplo, 31/02/2026. Quantidades de chamadas e aulas exigem inteiros aceitos pelo domínio; texto no lugar de número gera mensagem de erro. O cadastro valida código, nome, configuração e todas as datas antes de escrever. A transação SQL grava a disciplina e os encontros juntos; erro durante a operação desfaz a escrita. Para registrar, a validação ocorre antes do cálculo e da gravação. A memória só recebe o novo Registro depois que a escrita termina. Um teste simula disco indisponível e confirma que memória e SQLite continuam com a aula pendente. Não são gravados totais calculados: isso evita divergência entre o histórico e o resumo.")
    heading(s, "7.4 Correspondência com as etapas anteriores",
        "Na proposta inicial, o objetivo central era antecipar o risco de reprovação por frequência e permitir correção manual. A modelagem da segunda etapa detalhou pings de localização; eles são evidências estimadas, não prova institucional. A terceira etapa escolheu um fluxo manual executável e independente, com duas funções centrais e diagramas específicos. Esta versão conserva esse recorte, adiciona persistência efetiva e documenta a alteração de escopo. A opção de uma ou duas chamadas permanece relevante: com duas, um atraso em encontro de quatro aulas gera duas faltas; com uma, gera zero. Cancelamento, pendência e ausência são estados distintos. A agenda de avaliações da proposta ampla não interfere nos cálculos de frequência desta entrega acadêmica.")
    heading(s, "7.5 Rastreabilidade técnica",
        "F01 é coordenada por ControleAcademico.criar_disciplina e salva por database.salvar_disciplina. F02 e F03 passam por Disciplina.registrar_presenca, pela política concreta e por database.salvar_registro. F04 usa Disciplina.resumo e mostrar no menu. Os testes de domínio verificam os cálculos e a preservação de estado; os de menu percorrem o fluxo desde o cadastro vazio. A matriz completa da quinta etapa associa contratos, entradas, estados esperados, estados observados e nome de cada teste.")
    heading(s, "8. Limitações conhecidas",
        "A grade usa uma sessão por data e aulas fixas por encontro; reposição deve ser inserida como data da grade. Esta versão não consulta sistemas da UFMG e não usa GPS. O aplicativo completo tem integrações adicionais, apresentadas como evolução separada.")
    build("Frequencia_UFMG_Produto_Final.pdf",s)

def verification():
    s=[]
    cover(s, "Quinta etapa - Verificação do produto final")
    heading(s, "1. Método e estado inicial",
        "A versão testada é PF-01-SQLITE. Cada teste constrói seu estado inicial sem depender da ordem. Os testes de menu usam um arquivo SQLite temporário separado do banco de demonstração. A última execução está transcrita em evidencias/unittest.txt no ZIP. Comando: cd demo; python -m unittest discover -v.")
    groups=[
        ("F01 - Cadastro", "Cadastro e banco vazios; datas fictícias 02, 04, 09 e 11/11/2026.", [
            ("C01","Cadastro válido: DEMO01, 2 chamadas, 2 aulas, 4 datas.","Disciplina com 4 pendências e E=8.","Disciplina criada; 4 pendências e E=8.","test_criar_e_registrar_do_zero"),
            ("C02","Cadastrar demo01 novamente.","Rejeição; nome, grade e totais iguais.","ValueError; estado anterior preservado.","test_codigo_duplicado_preserva_cadastro_e_frequencia"),
            ("C03","1 aula e 2 chamadas; data repetida.","Rejeição; zero disciplinas.","ValueError; zero disciplinas.","test_entrada_invalida_nao_cria_disciplina"),
            ("C04","Reabrir banco depois de cadastrar e registrar.","Disciplina e presença recuperadas.","Novo controle recuperou nome e registro.","test_sqlite_preserva_disciplina_entre_aberturas")]),
        ("F02 - Registro", "DEMO01 cadastrada com datas pendentes.", [
            ("C05","Presente e ausente em datas da grade.","0 e 2 faltas; totais atualizados.","0 e 2 faltas; resumo atualizado.","test_criar_e_registrar_do_zero"),
            ("C06","Data fora da grade ou situação inválida.","Rejeita; registros e totais iguais.","ValueError; estado comparado e igual.","test_registro_invalido_nao_muda_grade_nem_totais"),
            ("C07","Registrar novamente sem corrigir.","Rejeita; primeiro registro preservado.","ValueError; primeiro registro preservado.","test_registro_invalido_nao_muda_grade_nem_totais"),
            ("C08","Atraso, 4 aulas, 1 versus 2 chamadas.","0 versus 2 faltas.","0 versus 2 faltas.","test_mesma_operacao_tem_resultado_conforme_chamada"),
            ("C14","Falha simulada ao gravar no SQLite.","Erro; registro pendente na memória e no banco.","OSError; ambos permaneceram pendentes.","test_falha_na_gravacao_preserva_memoria_e_banco")]),
        ("F03 - Correção", "DEMO01 com duas ausências resolvidas.", [
            ("C09","Corrigir uma ausência para presente.","A cai de 4 para 2; sem duplicação.","A=2; registro substituído.","test_correcao_substitui_e_recalcula"),
            ("C10","Marcar sem chamada e cancelar outra data.","E=6; L=1; frequência final 100%.","E=6; L=1; frequência 100%.","test_correcao_substitui_e_recalcula"),
            ("C11","Correção com situação inválida.","Rejeição; registro e totais preservados.","ValueError; estado igual.","test_registro_invalido_nao_muda_grade_nem_totais")]),
        ("F04 - Consulta", "DEMO01 cadastrada; consulta sem mutação.", [
            ("C12","Consultar código existente.","Grade, base, limite e saldo apresentados.","Menu exibiu resumo e percentuais.","test_fluxo_completo_sem_dados_preparados"),
            ("C13","Consultar código inexistente.","Mensagem clara; cadastro preservado.","Rejeição; nenhum cadastro criado.","test_rejeicoes_e_conversoes_sao_tratadas")]),
    ]
    for name, initial, rows in groups:
        heading(s,name,initial)
        s.append(t(["ID","Regra e entrada","Esperado / estado final","Observado / estado final","Situação / evidência"],[
            (id,escape(rule),escape(expect),escape(observe),
             "Aprovado<br/><font size='6'>"+test+"</font>")
            for id,rule,expect,observe,test in rows
        ],[1*cm,3.6*cm,3.8*cm,3.8*cm,4.8*cm]))
    heading(s, "2. Evidências e defeitos corrigidos",
        "A transcrição integral da última execução em evidencias/unittest.txt mostra 12 testes aprovados. O nome na última coluna liga cada cenário à execução. Durante a integração, foram corrigidos o conversor SQLite inválido e o retorno da disciplina recém-criada sem fachada persistente. O fluxo de gravação agora confirma o banco antes de trocar a memória; um teste injeta erro de escrita e compara o estado em memória e no banco. Após as correções, os testes foram repetidos. Nenhum cenário desta matriz ficou pendente.")
    build("Frequencia_UFMG_Verificacao.pdf",s)

if __name__=="__main__":
    product()
    verification()
