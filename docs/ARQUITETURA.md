# Arquitetura do Nextor

Comeca simples (falar no Nest) e cresce por habilidades, sem mudar o nucleo.

## Estrutura de pastas

```
nextor/                 pacote principal (o codigo)
  __init__.py
  __main__.py           sobe o servico:  python -m nextor
  config.py             le o .env e centraliza configuracao e caminhos
  personas.py           personalidades selecionaveis do assistente
  voz.py                fala no Nest (gTTS + catt via Google Cast)
  cerebro.py            despacha o cerebro escolhido (local/claude/agy)
  claude_cerebro.py     cerebro na nuvem (API do Claude)
  agy_cerebro.py        cerebro via agente do Maestri
  mcp_server.py         expoe as habilidades como ferramentas MCP
  agenda.py             Google Agenda por endereco privado iCal
  noticias.py           manchetes (Google News RSS) + resumo
  texto.py              skill de texto: traduzir, resumir, escrever (salva em arquivo)
  roteador.py           entende a frase e escolhe a habilidade
  rotina.py             rotina matinal (bom dia + agenda + noticias)
  automacoes.py         agendador proprio (automacoes por horario)
  servico.py            API HTTP local (Flask) + painel web + token
scripts/
  setup.py              configuracao de primeira vez (escreve o .env)
  agendar_rotina.ps1    agenda a rotina diaria no Windows
home_assistant/         ponte opcional (voz pelo Nest via Google)
docs/                   PLANO, VISAO, REFERENCIAS, ATALHO_IPHONE, este arquivo
.env                    segredos e preferencias (fora do git)
```

## Como as partes conversam

```
Entradas            Nucleo (notebook)                 Saida
--------            -----------------                 -----
iPhone/Siri  --->   servico.py (/comando) ---> roteador.py ---> habilidade ---> voz.py ---> Nest
navegador/HTTP                                   |  anotar  -> anotacoes.md
tarefa agendada --> rotina.py                    |  agenda  -> agenda.py (iCal)
                                                 |  noticias-> noticias.py (RSS)
                                                 |  conversar-> cerebro.py (Ollama)
```

- O **roteador** e o ponto de extensao: cada nova habilidade e uma funcao/modulo que ele
  passa a reconhecer. "Comeca pouco, pode ter muito mais."
- O **cerebro** pode ser trocado (Ollama local hoje; Claude via API no futuro) sem mexer no
  resto, porque todos chamam uma interface simples.
- As **personas** mudam so o jeito de falar; a logica e a mesma.

## Como adicionar uma habilidade nova

1. Crie um modulo em `nextor/` (ex.: `traducao.py`) com uma funcao que retorna texto.
2. No `roteador.py`, adicione as palavras-gatilho e a chamada a essa funcao.
3. Se precisar, exponha um endpoint em `servico.py`.
4. Segredos sempre no `.env`; nada pessoal no git.

## Comandos

```
.venv/Scripts/python.exe scripts/setup.py        # configurar (1a vez)
.venv/Scripts/python.exe -m nextor               # subir o servico
.venv/Scripts/python.exe -m nextor.voz "texto"   # falar algo no Nest
.venv/Scripts/python.exe -m nextor.rotina        # rodar a rotina matinal
```
