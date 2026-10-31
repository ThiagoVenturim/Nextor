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
cp .env.example .env   # e edite o .env
```

No `.env`, ajuste o nome do dispositivo (como aparece no app Google Home), o token e o
modelo. O `.env` guarda os segredos e nao vai para o git.

## Uso

Falar uma frase no Nest:
```
.venv/Scripts/python.exe nextor.py "bom dia, Thiago"
```

Subir o servico (deixe a janela aberta):
```
.venv/Scripts/python.exe nextor_service.py
```

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

## Seguranca

- So responde na rede local, protegido por um token.
- `.env` (segredos) e `anotacoes.md` (notas) nao vao para o git.
- Licenca MIT (ver arquivo LICENSE).
- Nao abra porta no roteador. Para uso fora de casa, use uma VPN privada (ex.: Tailscale).
- Gravar reunioes (recurso futuro) exige o consentimento dos participantes.

## Estado

Ver o diario de construcao e o plano de estudo em `PLANO.md` e a visao do produto em
`VISAO.md`.
