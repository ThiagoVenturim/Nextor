# Painel GTD no celular

Painel de produtividade pessoal baseado em "A Arte de Fazer Acontecer" (GTD). Ele roda como
PWA instalavel servido pelo proprio Nextor em `/gtd` e tambem pelo bot do Telegram
(`nextor/telegram_bot.py`). Os dados ficam no banco local do GTD (`~/.nextor/gtd.db` por
padrao, ou o banco configurado em `docs/DATABASE.md`).

## Fluxo GTD

| Passo | No painel (`/gtd`) | No Telegram |
|-------|--------------------|-------------|
| Capturar | aba Inbox, campo "Captura Rapida" | `/inbox <texto>` ou qualquer mensagem do chat do dono |
| Esclarecer e organizar | botao "Esclarecer" de cada item do inbox | - |
| Contextos | aba Contextos, com o total de acoes por contexto | `/contextos`, `/proximas @casa` |
| Proximas acoes | aba Visao e aba Contextos, botao "Feito" | `/proximas`, `/feito <codigo>` |
| Agenda e ordem do dia | aba Visao, bloco "Ordem do Dia" | `/hoje`, `/ordem` |
| Revisao semanal | aba Visao, bloco "Revisao Semanal" | `/revisao` |
| Leitura do dia | aba Leitura e meta diaria na aba Visao | `/li <paginas>` |

Contextos aceitos: `@faculdade`, `@casa`, `@trabalho`, `@academia`, `@leitura`, `@estudo` e
`@qualquer`. O codigo usado em `/feito` sao os 6 primeiros caracteres do id, mostrados entre
colchetes em `/proximas` e `/ordem`.

## Ordem sugerida do dia

O planejador (`nextor/gtd/ordem_dia.py`) cruza tres fontes:

1. A rotina do dia: blocos de horario ligados a um contexto.
2. Os compromissos de hoje da agenda (`NEXTOR_AGENDA_ICAL`).
3. As proximas acoes de cada contexto.

Para cada bloco da rotina ele desconta os compromissos que caem dentro dele. Se sobrarem menos
de 15 minutos, o bloco aparece como "ocupado pela agenda". Nos demais, entram ate 3 acoes do
contexto: atrasadas primeiro, depois as que vencem hoje, as que tem prazo e as sem prazo. De
manha as acoes de energia alta vem antes; a noite, as de energia baixa. Acoes de `@qualquer`
completam os blocos com espaco. O que ficou sem bloco e vence hoje (ou atrasou), ou e de um
contexto fora da rotina, aparece em "sem bloco". O bloco `@leitura` mostra quantas paginas
faltam para a meta diaria.

O resultado esta em `GET /gtd/ordem` e tambem na chave `ordem_sugerida` de `GET /gtd/hoje`.
O agente "Planejador do Dia" nos Ajustes liga e desliga a sugestao.

### Configurar a rotina

Formato: `HH:MM-HH:MM @contexto`, um bloco por linha no painel ou separados por ponto e
virgula no `.env`. A rotina vem, nesta ordem, de:

1. Ajustes do painel, campo "Rotina do dia" (gravado no `config.json` local).
2. `NEXTOR_GTD_ROTINA` no `.env`.
3. A rotina generica embutida (faculdade de manha, trabalho a tarde, academia, estudo em casa
   e leitura a noite).

Exemplo com valores ficticios:

```
NEXTOR_GTD_ROTINA=08:00-12:00 @faculdade; 13:00-18:00 @trabalho; 18:30-19:30 @academia; 20:00-21:00 @estudo; 21:00-21:30 @leitura
```

Coloque os seus horarios reais so no `.env` ou nos Ajustes do painel. Eles nao vao para o
repositorio.

## Rotas HTTP

Todas exigem o token mestre no cabecalho `X-Nextor-Token` (ou `Authorization: Bearer`). Token
na URL e recusado.

| Rota | Uso |
|------|-----|
| `POST /gtd/capturar` | captura rapida para o inbox |
| `POST /gtd/processar` | esclarece um item (proxima, projeto, leitura, aguardando, algum dia, feito, lixo) |
| `GET /gtd/itens?estado=&contexto=` | lista itens |
| `GET /gtd/contextos` | numero de proximas acoes por contexto |
| `GET /gtd/hoje` | agenda do dia, proximas acoes, meta de leitura e ordem sugerida |
| `GET /gtd/ordem` | ordem sugerida do dia |
| `GET /gtd/revisao` | revisao semanal |
| `GET/POST /gtd/projetos` | lista e cria projetos |
| `GET/PUT /gtd/config` | ajustes do painel, inclusive `rotina` |
| `GET /gtd/metodos`, `GET /gtd/visao`, `POST /gtd/visao/mover` | metodos intercambiaveis (veja `docs/METODOS_PRODUTIVIDADE.md`) |

## Acesso de fora de casa

O painel (`/gtd` e todas as rotas `/gtd/...`) so responde para a rede local ou para a VPN:
loopback, redes privadas, a faixa do Tailscale e as redes de `NEXTOR_REDES_PERMITIDAS`. De
qualquer outro endereco a resposta e 403. A unica excecao e `POST /gtd/webhook/github`, que
recebe chamadas do GitHub e e protegida pela assinatura HMAC (veja `docs/INTEGRACOES_GTD.md`).
O bot do Telegram continua funcionando de qualquer lugar, porque ele so atende os usuarios de
`TELEGRAM_USUARIOS_AUTORIZADOS`.
