# Direção visual e contrato do redesign — sessão 42.993

## Resultado e evidência

O estudante precisa reconhecer em segundos o que exige atenção, entrar numa disciplina
e agir sem procurar módulos técnicos. A arquitetura matéria-cêntrica da sessão 42.95,
o uso real relatado e os fluxos já implementados são a evidência disponível. Isso é
evidência de um usuário principal, não validação populacional.

## Direção

**Tese:** uma mesa acadêmica calma: o produto reduz ansiedade ao tornar prazo,
frequência e próxima ação espacialmente previsíveis, enquanto cada disciplina preserva
identidade própria.

- **Emoção:** calma primeiro, confiança durante a ação e satisfação discreta na conclusão.
- **Sistema:** superfícies frias e neutras; verde institucional reservado a ação e
  progresso; cor própria da disciplina em símbolo, trilho e calendário; tipografia do
  sistema com tracking e leading ópticos por papel.
- **Assinatura:** uma linha temporal compacta une aula, entrega e frequência. Não é
  decoração: mostra sequência e reduz troca de contexto.
- **Risco deliberado:** menos cards independentes e mais seções contínuas. Divisores,
  mudança de superfície e espaço continuam deixando propriedade e agrupamento claros.
- **Não fazer:** copiar a aparência literal do iOS, usar vidro sobre vidro, animar por
  espetáculo, esconder status em ícones, usar cor como único significado ou transformar
  todas as ações em pills.

## Princípios observáveis

| Princípio | Decisão verificável |
| --- | --- |
| Propósito | Início responde “o que faço agora?”; hub responde “como está esta matéria?” |
| Agência | Correção manual, cancelar, voltar e desfazer permanecem disponíveis |
| Responsabilidade | UFMG, cache e sincronização não ocultam origem, expiração ou falha |
| Familiaridade | Início/Calendário/Faltas preservam posição e nomes; voltar é simétrico |
| Flexibilidade | Reflow por conteúdo, texto ampliado, teclado, toque e movimento reduzido |
| Simplicidade | Uma ação primária por contexto; detalhe raro um nível abaixo |
| Craft | feedback no press, foco visível, alinhamento, contraste e estados completos |
| Delight | conclusão imediata e discreta; sem confete ou bounce sem gesto físico |

## Arquitetura visual

1. **Chrome:** rail em espaço amplo e barra inferior em espaço estreito, como material
   translúcido único com fallback sólido. Conteúdo mantém o mesmo mapa espacial.
2. **Início:** data/saudação, Agora, próximas datas e disciplinas. A pendência é mais
   importante que resumos; nenhuma integração vira destino principal.
3. **Disciplina:** identidade, ação imediata, frequência, datas, grade e materiais numa
   página contínua. Cor e símbolo vêm do prefixo do código, mas sempre acompanham texto.
4. **Faltas:** snapshot comparativo global preservado; usa a mesma representação de
   frequência do hub, sem segunda fonte de cálculo.
5. **Conta acadêmica:** configuração transversal; só aparece no fluxo quando uma ação
   dependente exige reconexão.

## Fluxo A — Início → disciplina → frequência

| Estado/ação | Contrato |
| --- | --- |
| Entrada | “Agora” mostra disciplina, data e consequência; cartão inteiro é acionável |
| Hub | A pendência se torna a única ação preenchida e mantém o contexto da sessão |
| Registro | Sheet nasce da ação, recebe foco, fecha por cancelar/Escape e preserva escolha |
| Commit | Mostra status pendente até confirmação; sucesso atualiza projeção e oferece desfazer quando real |
| Falha | Preserva escolha, informa que nada mudou e oferece repetir |
| Offline | Permite a correção conforme contrato atual e indica sincronização pendente |
| Reentrada | Retorna à disciplina e sessão, sem exigir lembrar data ou filtro |

## Fluxo B — Disciplina → materiais

| Estado/ação | Contrato |
| --- | --- |
| Entrada | Hub resume quantidade, arquivo recente e estado offline/falha |
| Catálogo | Pertence à disciplina; metaturma é origem secundária, não outro destino |
| Download | Feedback imediato “Preparando”, depois fila/progresso nativo; toque repetido é deduplicado |
| Conclusão | Um único estado “Offline” confirma que baixar já cria cópia local |
| Falha | Item afetado mantém nome/contexto e oferece repetir; demais itens continuam úteis |
| Sessão expirada | Reconectar retorna ao mesmo arquivo; catálogo/cópias locais não desaparecem |
| Privacidade | Bytes continuam Moodle → dispositivo/navegador; nuvem recebe apenas metadados/logs mínimos |

## Movimento, material e feedback

- press responde imediatamente com escala sutil; a ação só é efetivada no release;
- transições comuns são criticamente amortecidas, sem overshoot; bounce só pode surgir
  após gesto com momentum;
- sheet e retorno usam caminhos simétricos, partem da ação que os originou e podem ser
  interrompidos;
- `reduce motion` troca deslocamento por cross-fade; transparência e contraste elevados
  recebem superfícies sólidas e limites explícitos;
- status, conclusão, aviso e erro são textuais e localizados. Haptic só no Android para
  commit significativo, alinhado ao frame visual.

## Tipografia e componentes

- fonte do sistema; display 30–44 com tracking negativo e leading curto;
- títulos de seção 20–24, corpo 15–17 e utilitários 11–13 com tracking positivo;
- alvos mínimos de 44×44; ações com rótulos específicos; ícone isolado somente quando
  universal, com nome acessível e tooltip no pointer;
- cores semânticas são independentes das cores das disciplinas; vermelho significa
  somente ausência/erro/risco.

## Estados e restrições

Loading é localizado; cache aparece antes da rede; falha parcial não apaga outras
seções; offline, desatualizado, sincronizando e expiração têm consequência e recuperação.
Em largura reduzida, colunas empilham mantendo ordem; rótulos essenciais não truncam;
mudança de orientação preserva rota, foco lógico e trabalho. O comportamento completo
de acessibilidade será provado nas sessões de componentes e telas, não reivindicado por
este protótipo.

## Gate para implementação

O protótipo cobre os dois fluxos críticos com dados demonstrativos e não escreve em
produção. Antes da 42.994, o usuário principal deve validar: hierarquia da Início,
compreensão da barra de frequência, encontrabilidade de materiais, clareza do sheet e
sensação geral de calma/confiança. Qualquer mudança de arquitetura volta ao contrato;
ajustes de cor, ritmo e densidade seguem para os tokens.

## Evidência de validação — segunda passada

O usuário principal aprovou a direção e considerou o resultado “mil por cento” melhor,
mas relatou excesso de estímulos simultâneos. A revisão mantém arquitetura e identidade,
reduzindo densidade em três pontos: a Início mostra apenas o próximo prazo por extenso;
faltas aparecem no cartão somente quando pedem atenção; e a pendência abandona o grande
tratamento de alerta em favor de uma superfície neutra. O gate passa quando a tela parecer
mais calma sem esconder a próxima ação, o próximo prazo ou uma situação crítica.
