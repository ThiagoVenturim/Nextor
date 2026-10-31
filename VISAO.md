# Visao do assistente pessoal (projeto do Nest Mini)

O que comecou como "fazer o Nest falar" virou um assistente pessoal proprio do Thiago,
pensado para o dia a dia de advogado e de programador. O Nest Mini e uma das bocas/ouvidos;
o cerebro e a memoria ficam no notebook (depois num mini PC 24h).

## Principio

- Um nucleo (o servico no notebook) com memoria, cerebro de IA e uma lista de "habilidades".
- Varias entradas e saidas: Nest Mini (voz), iPhone, tablet, e no futuro outros aparelhos.
- Tudo que puder ser local fica local; o que precisar de nuvem usa conta/API do proprio Thiago.

## Casos de uso por perfil

### Advogado
- Agenda: ler os compromissos do dia, avisar audiencias e prazos, criar eventos por voz.
- Lembretes de prazos (com antecedencia configuravel).
- Anotacoes rapidas ditadas (viram notas no Obsidian).
- Gravar reunioes e gerar transcricao + resumo. IMPORTANTE: gravar reuniao exige o
  consentimento dos participantes; o assistente deve avisar e so gravar com permissao.
- Buscar numa base de notas/documentos pessoais (sem mandar nada para fora sem autorizacao).

### Programador
- Status do que roda no Maestri: pipelines, agentes e tarefas (lendo a CLI do maestri).
- Avisar quando um build/deploy termina ou falha (o Nest fala "o deploy passou").
- Lembretes de PRs, TODOs do dia.
- Perguntas rapidas tecnicas via IA.

## Habilidades (o que o assistente sabe fazer)

Cada habilidade e um modulo pequeno. Mapa do simples ao avancado:

| Habilidade | O que faz | Viabilidade |
|---|---|---|
| Falar / Anotar | pronto (V0/V1) | feito |
| Conversar (IA) | pronto, aguardando modelo (V2) | feito |
| Agenda Google | ler compromissos, criar eventos | facil (API oficial) |
| Notas no Obsidian | anotar direto no cofre, sincronizar no celular | facil |
| Status do Maestri | ler a CLI e falar o que esta rodando/terminou | facil (CLI local) |
| Lembretes/timers | lembrar em horario, repetir | facil |
| Gravar reuniao | gravar audio + transcrever (Whisper) + resumir | medio; exige consentimento |
| Cerebro na nuvem (Claude/API) | respostas melhores que o modelo local | facil (API paga do Thiago) |
| Tablet / segundo aparelho | mesmas rotas HTTP; app Atalhos ou navegador | facil em casa |
| Fora de casa | acesso remoto seguro | medio (VPN privada tipo Tailscale) |

## Pontos a decidir com realismo

- Alexa: nao e so "conectar". A Alexa nao aceita Cast como o Nest. Para o assistente falar
  numa Alexa, o caminho realista e uma skill propria ou o servico "Notify Me"; da mais
  trabalho e fica num ecossistema separado. Deixar para depois; o Nest cobre a parte de voz
  agora. (O Home Assistant pode servir de ponte unica para Google e Alexa mais tarde.)
- Claude: entra como "cerebro na nuvem" opcional, via API da conta do Thiago, quando quiser
  respostas melhores que o modelo local. Da para escolher por tarefa (local para coisas
  simples, nuvem para as dificeis).
- Gravar reunioes: tecnicamente simples (gravar no celular/notebook + Whisper). O ponto
  sensivel e juridico: so gravar com consentimento dos presentes. O proprio assistente deve
  lembrar disso.
- Seguranca: nada de abrir porta no roteador. Em casa, rede local + token. Fora de casa, VPN
  privada. Segredos (tokens, chaves de API) nunca vao para o git.

## Nomes em estudo

Ideias que unem "Nest" + "IA" e a ideia de assistente geral:
- Nestia (Nest + IA)
- Jarbas (versao brasileira e bem-humorada de "Jarvis"; combina com programador)
- Zelador (quem cuida de tudo na casa)
- Nestor (atual)
- Nestlar (Nest + lar)
- Mininho (mini + ninho)

Decisao do nome pendente com o Thiago.

## Adendos de 31/10/2026 (branch develop)

### Feito nesta rodada
- Nome do usuario na config (.env NEXTOR_NOME) e setup de primeira vez (nextor_setup.py):
  a primeira acao e a pessoa configurar nome, dispositivo, token e agenda.
- Noticias diarias: nextor_noticias.py busca manchetes (Google News RSS, sem chave) sobre um
  assunto (padrao: IA generativa) e resume com a IA local; endpoint /noticias fala no Nest.

### Reconhecer apenas a sua voz (pesquisa, nao pronto)
Objetivo: o assistente so obedecer a voz do Thiago. Pontos honestos:
- O microfone do Nest NAO e acessivel a terceiros. A captacao de voz tem de ser no celular
  ou no notebook (microfone proprio), nao no Nest.
- Series temporais + DTW: DTW alinha duas series no tempo e serve para comparar formatos de
  onda ou padroes curtos, mas NAO e a tecnica certa para identificar quem fala. Reconhecimento
  de locutor moderno usa "embeddings" de voz (ex.: resemblyzer, SpeechBrain, pyannote): a voz
  vira um vetor e compara-se por similaridade. DTW pode aparecer so em deteccao de uma palavra
  de ativacao fixa dita pela mesma pessoa, com acerto limitado e sensivel a ruido.
- Proposta realista, em fases: (1) ditar comandos pelo celular (ja temos, confiavel);
  (2) STT local no notebook com Whisper para comandos falados; (3) verificacao de locutor por
  embedding: a pessoa grava algumas amostras (cadastro), e so comandos com voz parecida passam,
  com um limiar ajustavel. Mineracao de dados / serie temporal entram na analise de uso (quando
  a pessoa costuma pedir o que), nao na identificacao da voz.

### Comandos por fala (intencoes)
- Depois do STT, mapear a frase para uma intencao (anotar, agenda, noticias, conversar) por
  regras simples e, no futuro, pela propria IA decidindo qual habilidade chamar.

### Conectar com Claude, agy e outros (via MCP)
- Cerebro na nuvem: usar a API do Claude como cerebro opcional para respostas melhores que o
  modelo local (escolha por tarefa). Chave de API no .env.
- MCPs: criar pequenos servidores MCP (ou clientes) para cada fonte (agenda, noticias,
  Maestri, documentos). Assim Claude, os agentes do Maestri (agy) e o proprio Nextor usam as
  mesmas habilidades. E um passo de arquitetura; fazer um MCP de cada vez, comecando pelo de
  noticias ou agenda, que ja existem como modulos.
- Agendamento: rodar as noticias e o resumo da agenda todo dia em horario fixo (tarefa agendada
  no Windows ou rotina do Maestri) e o Nest fala sozinho de manha.

### Escopo (importante)
A lista cresceu bastante. Sugestao de ordem: STT local -> comandos por intencao -> cerebro
Claude via API -> um MCP -> verificacao de voz por embedding (o mais dificil, por ultimo).
