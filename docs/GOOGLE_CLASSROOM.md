# Integracao com Google Sala de Aula (Classroom)

Modulo de integracao somente leitura do Nextor com o Google Sala de Aula (Google Classroom).

Permite que o assistente consulte cursos ativos, atividades com prazos de entrega (courseWork) e avisos publicados (announcements), alimentando o painel de pendencias multifonte e respondendo por voz no Google Nest Mini.

---

## 1. Escopos e Permissoes de Leitura

A integracao opera em modo estritamente somente leitura (read-only):

- `https://www.googleapis.com/auth/classroom.courses.readonly`: listar cursos ativos matriculados pelo aluno.
- `https://www.googleapis.com/auth/classroom.coursework.me.readonly`: consultar atividades e prazos do aluno.
- `https://www.googleapis.com/auth/classroom.announcements.readonly`: consultar comunicados e avisos publicados no mural.

O assistente nunca envia, altera ou remove tarefas na instituicao de ensino.

---

## 2. Passo a Passo no Google Cloud Console

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie um novo projeto (ex: `Nextor-Estudos`).
3. No menu lateral, acesse **APIs e Servicos > Biblioteca**.
4. Pesquise por **Google Classroom API** e clique em **Ativar**.
5. Acesse **Tela de permissao OAuth**:
   - Tipo de usuario: **Externo** (ou Interno se sua conta institucional permitir).
   - Preencha o nome do app e e-mail de suporte.
   - Em **Escopos**, adicione os tres escopos somente leitura listados acima.
   - Em **Usuarios de teste**, adicione o seu e-mail institucional do Google Classroom.
6. Acesse **Credenciais > Criar Credenciais > ID do cliente OAuth**:
   - Tipo de aplicativo: **App para computador** (Desktop app).
   - Nome: `Nextor Classroom Client`.
   - Baixe o arquivo JSON e salve-o em local seguro (ex: `dados_estudos/credentials.json`).

---

## 3. Geracao e Armazenamento do Token

O Nextor aceita duas formas de configuracao no arquivo `.env`:

### Opcao A: Caminho para arquivo de token local (Recomendado)
Gere o token OAuth uma unica vez (via script simples ou Google Cloud CLI) e aponte o arquivo:
```env
GOOGLE_CLASSROOM_TOKEN=dados_estudos/classroom_token.json
GOOGLE_CLASSROOM_CREDENTIALS=dados_estudos/credentials.json
```
O arquivo `dados_estudos/classroom_token.json` contem:
```json
{
  "access_token": "ya29.a0...",
  "refresh_token": "1//04...",
  "token_type": "Bearer"
}
```

### Opcao B: Token Bearer em string direta
Caso utilize um token temporario ou gerado externamente:
```env
GOOGLE_CLASSROOM_TOKEN=ya29.a0AfH6SM...
```

> Nota: Arquivos de credenciais e tokens ficam na pasta `dados_estudos/` ou fora do repositorio e estao devidamente incluidos no `.gitignore`. Nunca realize commit de segredos.

---

## 4. Comandos de Voz Suportados

- **Atividades gerais**:
  - "Quais sao minhas atividades do Google Sala de Aula?"
  - "Atividades do Classroom"
  - "O que tenho no Classroom?"
- **Atividades por materia**:
  - "Tarefas do Sala de Aula de Fisica"
  - "Atividades de Calculo no Classroom"
- **Avisos do mural**:
  - "Avisos do Classroom"
  - "Avisos de Historia no Sala de Aula"

---

## 5. Endpoints HTTP da API (Porta 5005)

Todos os endpoints exigem o token mestre em `X-Nextor-Token` ou `Authorization: Bearer <token>`:

- `GET /v1/classroom/cursos`: lista cursos ativos matriculados.
- `GET /v1/classroom/atividades`: lista atividades pendentes (parametros opcionais: `curso_id`, `disciplina`, `apenas_pendentes`).
- `GET /v1/classroom/avisos`: lista comunicados recentes (parametros opcionais: `curso_id`, `disciplina`, `limite`).
- `GET /v1/pendencias?fonte=classroom`: integra tarefas do Classroom ao painel multifonte.
