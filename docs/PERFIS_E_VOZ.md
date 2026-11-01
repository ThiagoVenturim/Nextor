# Perfis (agentes) e a palavra "ei Nextor"

## Perfis: um Nextor para cada contexto

Um perfil e um Nextor com suas proprias configuracoes: personalidade, cerebro, agenda,
assunto das noticias, ate outro dispositivo. Serve para ter, por exemplo, um Nextor de
casa (mais gentil) e um de escritorio (mais profissional).

Cada perfil e um arquivo `.env.<nome>` na raiz (fora do git). Ja vem dois de exemplo:
- `.env.casa` - persona companheiro.
- `.env.escritorio` - persona profissional, noticias de direito e tecnologia juridica.

Escolher o perfil ativo (duas formas):
- Escreva o nome no arquivo `.perfil` (ex.: `casa`), ou
- Defina a variavel de ambiente ao rodar: `NEXTOR_PERFIL=escritorio`.

Exemplos:
```
echo escritorio > .perfil
.venv/Scripts/python.exe -m nextor

# ou, so para esta execucao:
NEXTOR_PERFIL=casa .venv/Scripts/python.exe -m nextor.rotina
```

Criar um perfil novo: copie um `.env.<nome>` e ajuste. Como cada perfil pode ter porta e
dispositivo proprios, da para rodar dois ao mesmo tempo (um por quarto, por exemplo).

## A palavra "ei Nextor" - o que da e o que nao da

Resumo honesto:

- No **Google Nest nao da** para trocar a palavra de ativacao. O Nest so acorda com
  "Ok Google" / "Ei Google"; nao existe forma (nem com Home Assistant) de ele acordar
  com "ei Nextor". O maximo e "Ok Google, ativar Nextor" virar um gatilho, e so com Home
  Assistant + Nabu Casa.
- Para ter **"ei Nextor" de verdade** como palavra de ativacao, use um **satelite de voz**
  proprio, que escuta uma palavra personalizada:
  - Home Assistant Voice Preview Edition (aparelho pronto, ~60 dolares), ou
  - um ESP32 com ESPHome / microWakeWord (~15 dolares), ou
  - o microfone do notebook/celular rodando openWakeWord.
  Esse satelite ouve "ei Nextor", manda o audio para transcricao (Whisper) e chama o
  `/comando` do Nextor. Ai o fluxo e todo seu, sem depender do Google.

Hoje, sem hardware novo, o gatilho pratico e:
- iPhone: atalho "Nextor" por Siri (ver `ATALHO_IPHONE.md`).
- Qualquer aparelho na rede: um POST para `/comando`.
