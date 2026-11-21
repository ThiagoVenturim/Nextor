# Concorrentes e diferencial do Nextor

Projetos parecidos (open source e privados), o diferencial do Nextor e o que melhorar com base neles. Pesquisa de 2026-11-08; verifique cada projeto antes de usar.

## Parecidos

### Open source
- **Khoj**: "segundo cerebro" self-hostavel, chat, busca semantica, agentes e automacoes, com LLM local ou nuvem.
- **Leon**: assistente pessoal open source que roda no seu servidor, com skills modulares.
- **Eclaire**: roda no seu hardware com modelos locais, cobre tarefas, notas e documentos.
- **Atom**: assistente open source para agenda e tarefas, self-host.
- **Odysseus**: workspace self-hosted com chat, agentes, email, calendario e memoria (Ollama/llama.cpp, CalDAV).
- **OwnPilot**: suporta Ollama, LM Studio e endpoints OpenAI-compativeis.
- **Home Assistant** (automacao) e **Rhasspy/Mycroft/OVOS** (voz offline) cobrem partes.

### Privados / fechados
- **Google Assistant/Gemini**, **Alexa**, **Siri**: assistentes de voz fechados (o Nextor usa o Nest como voz, mas o cerebro e nosso).
- **Notion AI**, **Motion**, **Reclaim**, **Akiflow**: produtividade/agenda com IA, fechados.

## Nosso diferencial
- **Cerebro e dados locais**, o Nest Mini e so a voz (Google Cast); sem firmware no Nest, so interfaces oficiais e rede local; acesso externo so por VPN.
- **Multimetodo de produtividade** (GTD, PARA, Eisenhower, Kanban, Pomodoro) trocavel sobre os mesmos itens, no celular (PWA) e no Telegram.
- **Notificacoes multicanal** (Telegram, Discord, WhatsApp, web push, voz) escolhiveis por evento.
- **Modo estudante** integrado (biblioteca, quiz, flashcards, artigos, Canvas/Classroom) e um **coach de estudos** (#57) que vira cronograma + pontuacao.
- **Privacidade por padrao**: nada pessoal no repo, consentimento para gravacao de reuniao, preferir processamento local.
- **Liga no nosso ecossistema**: NexHub, NexDeck, e os modulos NexRead/NexVoice (#55/#56), carreira (#58).

## O que melhorar aprendendo com eles
- **Memoria/second brain** forte (Khoj): busca semantica sobre as proprias notas e historico.
- **Skills modulares com catalogo** (Leon): facilitar a pessoa instalar/criar habilidades.
- **Agendamento inteligente** (Motion/Reclaim): encaixar tarefas nos espacos livres automaticamente (o calendario #51 ja comeca isso).
- **CalDAV/Google Calendar de duas vias** (Odysseus): hoje lemos iCal; evoluir para escrita/duas vias com cuidado.
- **Voz offline de ida e volta** (Rhasspy/OVOS): reduzir dependencia do Cast e do Home Assistant para o gatilho de voz.

## Sources
- https://github.com/khoj-ai/khoj (Khoj)
- https://openalternative.co/collections/self-hosted/categories/ai-personal-assistants
- https://awesome.ecosyste.ms/projects/github.com%2Feclaire-labs%2Feclaire (Eclaire)
- https://awesome.ecosyste.ms/projects/github.com%2Frush86999%2Fatom (Atom)
