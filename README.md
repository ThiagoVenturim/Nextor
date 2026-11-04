# Nextor

Assistente pessoal que usa um Google Nest Mini como voz, com o cerebro e a memoria
rodando no proprio computador. Pensado para o dia a dia de advogado e de programador:
anotacoes por voz, lembretes, agenda, status de tarefas e conversa com IA local.

O nome e um trocadilho: Next + Nestor.

## Como funciona

- O Nest Mini e a boca (fala via Google Cast) e um dos gatilhos.
- O cerebro e a memoria ficam no computador: um servico que guarda anotacoes e conversa
  com um modelo de IA local (Ollama).
- As entradas vem do iPhone (app Atalhos / Siri), do navegador ou de outros aparelhos na
  mesma rede de casa.

Nada e instalado no Nest. Nenhum firmware e modificado. Tudo usa as interfaces oficiais
(Google Cast) e a rede local.

## Requisitos

- Python 3.11 ou mais novo.
- Um Google Nest Mini (ou outro dispositivo Google Cast) na mesma rede Wi-Fi.
- Ollama instalado, com um modelo baixado (ex.: `ollama pull qwen2.5:3b`).

## Instalacao

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/setup.py   # configura o .env (nome, persona, token, etc.)
```

O `setup.py` pergunta o essencial e escreve o `.env` (segredos e preferencias), que nao vai
para o git. Tambem da para copiar `.env.example` para `.env` e editar na mao.

> Seguranca do token: o servico exige que `NEXTOR_TOKEN` tenha no minimo 24 caracteres
> e recusa o valor padrao `troque-este-token`. O `scripts/setup.py` gera um token seguro
> automaticamente se deixado em branco, ou voce pode gerar um via terminal:
> `python -c "import secrets; print(secrets.token_urlsafe(24))"`

## Estrutura

O codigo e um pacote em `nextor/` (um modulo por habilidade). Veja `docs/ARQUITETURA.md`.

## Uso

Falar uma frase no Nest:
```
.venv/Scripts/python.exe -m nextor.voz "bom dia, Thiago"
```

Subir o servico (deixe a janela aberta):
```
.venv/Scripts/python.exe -m nextor
```

Rotina matinal (bom dia + agenda + noticias):
```
.venv/Scripts/python.exe -m nextor.rotina
```

## Personas

A pessoa escolhe o jeito do assistente em `NEXTOR_PERSONA` no `.env`: `assistente`,
`companheiro`, `profissional`, `amigo` ou `coach`. Adicionar novas e facil em
`nextor/personas.py`.

## Cerebro (qualquer IA)

O cerebro e escolhido em `NEXTOR_CEREBRO` no `.env`:
- `local` - Ollama na propria maquina (gratis). Modelo em `NEXTOR_MODELO`.
- `claude` - API do Claude (melhor, pago). Modelo em `NEXTOR_CLAUDE_MODELO` (padrao
  `claude-haiku-5-5`, o mais barato) e chave em `ANTHROPIC_API_KEY`.
- `agy` - encaminha para um agente do Maestri em `NEXTOR_AGY_AGENTE`.

Se o cerebro escolhido falhar (sem chave, offline), cai para o local automaticamente.

## Automacoes e painel (o nosso Home Assistant, sem apps de terceiros)

O servico ja traz um agendador proprio: automacoes em horarios fixos, sem Docker, sem
Home Assistant, sem Agendador do Windows. Acoes: `rotina` (bom dia), `agenda`, `noticias`,
`falar` e `comando`. Ficam em `automacoes.json` (fora do git); vem com a rotina das 7h.

Painel web (navegador/celular na rede de casa):
```
http://localhost:5005/painel?token=SEU_TOKEN
```
De la da para falar, anotar, ouvir agenda/noticias e criar ou remover automacoes.
API: `GET/POST/DELETE /automacoes` (POST com `hora`, `acao`, `texto`).

## MCP (conectar o Claude ou outro assistente ao Nextor)

O Nextor tambem e um servidor MCP: expoe as habilidades (anotar, ler notas, agenda,
noticias, falar) para um assistente compativel com MCP se conectar e usar.

```
.venv/Scripts/python.exe -m nextor.mcp_server
```

Num cliente MCP (ex.: Claude Desktop), aponte para esse comando (transporte stdio),
com `cwd` na pasta do projeto.

Endpoints (POST, com `?token=...`):
- `/comando`  entrada unica: entende a frase e roteia (anotar/agenda/noticias/conversar)
- `/anotar`   salva a nota e confirma em voz
- `/falar`    fala o texto
- `/conversar` pensa com a IA local e responde em voz (conhece notas e agenda)
- `/agenda`   fala os compromissos (`?quando=hoje` ou `?quando=proximos`)
- `/noticias` resume e fala as noticias (`?assunto=...`)
- `/notas`    (GET) lista as notas

Comando unico (recomendado para o atalho do iPhone): mande a fala para `/comando` e o
Nextor decide o que fazer. Ex.: "ei Nextor, anota comprar pao", "o que tenho amanha",
"me traz as noticias sobre IA".

Primeira configuracao: `.venv/Scripts/python.exe nextor_setup.py` (define nome, token, etc.).

O atalho do iPhone esta descrito em `ATALHO_IPHONE.md`.

## Google Agenda

O Nextor le a agenda por um endereco privado iCal, sem projeto no Google Cloud:

1. Google Agenda no navegador > Configuracoes da sua agenda > "Integrar agenda".
2. Copie o "Endereco secreto no formato iCal".
3. Cole no `.env` em `NEXTOR_AGENDA_ICAL`. Esse endereco e um segredo, nao compartilhe.

Depois, `/agenda` fala os compromissos e o `/conversar` passa a responder "o que tenho
amanha". Sem o endereco, o resto do Nextor funciona normalmente.

## Rosto e modos

O Nextor tem um rosto: um bichinho que reage ao que voce escreve e muda de visual com o modo.

- Abra `http://localhost:5005/rosto?token=SEU_TOKEN` ou rode `scripts
osto.ps1`, que abre o rosto numa janela propria.
- No NexDeck, o botao de carinha no topo abre o mesmo bichinho no celular.
- Converse pela tela; marque "no Nest" se quiser ouvir a resposta no alto-falante.

| Modo | Visual | Ambiente |
|---|---|---|
| Estudo | Mochila | Luzes brancas fortes |
| Trabalho | Gravata | Luzes neutras |
| Tranquilidade | Olhos relaxados | Tela a 40%, luzes quentes e baixas |
| Leitura | Oculos | Tela a 30%, luz quente |
| Normal | Sem acessorio | Devolve o brilho de antes |

Por voz ou texto: "modo estudo", "ativa o modo leitura", "quero relaxar".

### Como chamar

O Nextor entende o jeito natural de chamar, com erros de digitacao ou de reconhecimento de voz:
"ei Nextor", "ola Nextor", "fala Nextor", "meu bom Nextor", "meu amigo Nextor", "bom Nextor", "e ai Nestor",
"fala enxtor". O comando pode vir junto ("meu amigo Nextor, modo leitura") ou depois ("ei Nextor" e ele responde
"Oi, pode falar"). Quando chamado, o rosto acorda em modo ouvindo e, no Windows, abre numa janela se nenhuma tela
estiver mostrando (desligue com `NEXTOR_ROSTO_AUTO=nao`).

### Voz no computador

O Nextor fala pelas caixas de som do PC com uma voz natural, gerada localmente pelo [Piper](https://github.com/rhasspy/piper)
(codigo aberto, sem nuvem), em portugues, ingles, espanhol ou frances. Com o rosto aberto, a boca acompanha a fala.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-voz.txt
.venv/Scripts/python.exe scripts/baixar_vozes.py
```

| Variavel | Padrao | Para que serve |
|---|---|---|
| `NEXTOR_IDIOMA` | `pt-BR` | Idioma da voz e das respostas: `pt-BR`, `en-US`, `es-ES`, `fr-FR` (tambem no seletor do rosto) |
| `NEXTOR_VOZ_SAIDA` | `pc` | Onde falar: `pc`, `nest` ou `ambos` |
| `NEXTOR_VOZ_MOTOR` | `auto` | `piper` (natural, local), `sapi` (vozes do Windows) ou `gtts` (internet); `auto` tenta nessa ordem |
| `NEXTOR_VOZ_PT_BR` etc. | uma voz por idioma | Troque por outra voz do Piper, ex.: `pt_BR-edresson-low` |

### Falar "ei Nextor" no microfone

```powershell
.venv/Scripts/python.exe -m nextor            # servico (um terminal)
.venv/Scripts/python.exe -m nextor.ouvinte    # ouvinte do microfone (outro terminal)
```

O ouvinte usa o Vosk, offline (modelo em `models/vosk-pt`, configuravel em `NEXTOR_VOSK_MODELO`). Ao ouvir uma frase de
chamada, o rosto abre e o comando e executado; se voce so chamar, ele espera o comando por `NEXTOR_JANELA_ESCUTA`
segundos (padrao 8).

### Quem responde: Nextor, Claude ou agy

Quem nao quiser a persona do Nextor pode falar direto com o Claude ou com o agy. O rosto troca para o simbolo de cada um
(desenhos proprios em pixels) e o cerebro muda junto:

- "ei Claude, ...", "usar o Claude", "quero falar com o Claude" -> Claude (precisa de `ANTHROPIC_API_KEY`);
- "oi agy, ...", "troca para o agy" -> agy (pelo Maestri);
- "volta pro Nextor" -> persona do Nextor com o cerebro padrao do `.env`.

Tambem da para trocar pelos botoes Nextor / Claude / agy no rosto e no NexDeck. Se o cerebro escolhido estiver fora do
ar, a resposta vem do modelo local.

O humor e um palpite pelas palavras da mensagem (feliz, triste, ansioso, cansado, irritado). O bichinho reage e o
cerebro recebe uma dica para responder no tom certo. Nada de camera ou analise de voz.

Luzes inteligentes passam pelo Home Assistant (qualquer marca que ele suporte): configure `NEXTOR_HA_URL`,
`NEXTOR_HA_TOKEN` e `NEXTOR_HA_LUZES`, ou uma cena por modo em `NEXTOR_HA_CENA_<MODO>`. Sem isso, so o brilho da tela muda.

## NexDeck (stream deck no celular)

O [NexDeck](https://github.com/ThiagoVenturim/NexDeck) transforma o celular em um
stream deck do PC e conversa com o Nextor nos dois sentidos:

- Do deck para o Nextor: botoes e a barra "Fale com o Nextor" mandam texto para
  `/comando`, `/falar`, `/anotar` ou `/conversar`.
- Do Nextor para o deck: diga "no computador, bloquear" ou "deck play" e o Nextor
  aperta o botao com esse nome. Acoes que pedem confirmacao (desligar, suspender)
  nao rodam por voz.

Configure `NEXTOR_DECK_URL` e `NEXTOR_DECK_TOKEN` no `.env` (o token esta em
`data/secret.json` do NexDeck).

## Seguranca

- So responde na rede local, protegido por um token.
- `.env` (segredos) e `anotacoes.md` (notas) nao vao para o git.
- Licenca MIT (ver arquivo LICENSE).
- Nao abra porta no roteador. Para uso fora de casa, use uma VPN privada (ex.: Tailscale).
- Gravar reunioes (recurso futuro) exige o consentimento dos participantes.

## Estado

Ver o diario de construcao e o plano de estudo em `PLANO.md` e a visao do produto em
`VISAO.md`.
