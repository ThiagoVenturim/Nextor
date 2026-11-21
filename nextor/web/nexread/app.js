(function () {
  let artigoAtualId = null;

  const elToken = document.getElementById('input-token');
  const elMotor = document.getElementById('select-motor');
  const elLayout = document.getElementById('select-layout');
  const elTitulo = document.getElementById('input-titulo');
  const elUrl = document.getElementById('input-url');
  const elIdioma = document.getElementById('select-idioma');
  const elConteudo = document.getElementById('input-conteudo');
  const elBtnTraduzir = document.getElementById('btn-traduzir');
  const elStatus = document.getElementById('status-leitura');
  const elTituloExibicao = document.getElementById('artigo-titulo-exibicao');
  const elLeitorHtml = document.getElementById('leitor-html');
  const elDisciplina = document.getElementById('input-disciplina');
  const elBtnSalvarEstudos = document.getElementById('btn-salvar-estudos');

  const elTrecho = document.getElementById('input-trecho');
  const elNotaMarcacao = document.getElementById('input-nota-marcacao');
  const elCor = document.getElementById('select-cor');
  const elBtnMarcar = document.getElementById('btn-marcar');
  const elListaMarcacoes = document.getElementById('lista-marcacoes');

  const elTituloGravacao = document.getElementById('input-titulo-gravacao');
  const elTranscricao = document.getElementById('input-transcricao');
  const elBtnDitar = document.getElementById('btn-ditar-voz');
  const elBtnSalvarGravacao = document.getElementById('btn-salvar-gravacao');
  const elListaGravacoes = document.getElementById('lista-gravacoes');

  const elChatHistorico = document.getElementById('chat-historico');
  const elPerguntaIa = document.getElementById('input-pergunta-ia');
  const elCheckArtigos = document.getElementById('check-buscar-artigos');
  const elBtnPerguntarIa = document.getElementById('btn-perguntar-ia');

  try {
    const salvo = sessionStorage.getItem('nextor_nexread_token');
    if (salvo && elToken) elToken.value = salvo;
    if (elToken) {
      elToken.addEventListener('change', () => {
        sessionStorage.setItem('nextor_nexread_token', elToken.value.trim());
      });
    }
  } catch (e) {}

  function obterHeaders() {
    const tk = (elToken && elToken.value.trim()) || '';
    return {
      'Content-Type': 'application/json',
      'X-Nextor-Token': tk
    };
  }

  document.addEventListener('mouseup', () => {
    const sel = window.getSelection ? window.getSelection().toString().trim() : '';
    if (sel && sel.length >= 3 && elLeitorHtml && elLeitorHtml.contains(window.getSelection().anchorNode)) {
      if (elTrecho) elTrecho.value = sel;
    }
  });

  async function traduzirPagina() {
    const conteudo = (elConteudo && elConteudo.value.trim()) || '';
    const url = (elUrl && elUrl.value.trim()) || '';
    if (!conteudo && !url) {
      elStatus.textContent = 'Informe o HTML/texto ou a URL da pagina que voce abriu.';
      return;
    }
    elStatus.textContent = 'Traduzindo pagina ao vivo...';
    try {
      const resp = await fetch('/nexread/traduzir', {
        method: 'POST',
        headers: obterHeaders(),
        body: JSON.stringify({
          conteudo_html: conteudo,
          url: url,
          titulo: (elTitulo && elTitulo.value.trim()) || '',
          idioma_destino: elIdioma ? elIdioma.value : 'pt-BR',
          motor: elMotor ? elMotor.value : 'local',
          modo_layout: elLayout ? elLayout.value : 'bilingue',
          aberta_pelo_usuario: true
        })
      });
      const dados = await resp.json();
      if (!resp.ok || !dados.ok) {
        elStatus.textContent = dados.erro || 'Erro ao traduzir pagina.';
        return;
      }
      artigoAtualId = dados.artigo.id;
      elTituloExibicao.textContent = dados.artigo.titulo_traduzido || dados.artigo.titulo;
      elLeitorHtml.innerHTML = dados.artigo.html_traduzido;
      elStatus.textContent = 'Traduzido com sucesso (' + dados.artigo.blocos.length + ' blocos).';
      elListaMarcacoes.innerHTML = '';
      elListaGravacoes.innerHTML = '';
      elChatHistorico.innerHTML = '';
    } catch (err) {
      elStatus.textContent = 'Falha de comunicacao com o Nextor.';
    }
  }

  async function marcarTrechoAtual() {
    if (!artigoAtualId) {
      elStatus.textContent = 'Traduza ou abra um artigo antes de marcar trechos.';
      return;
    }
    const trecho = (elTrecho && elTrecho.value.trim()) || '';
    if (!trecho) return;
    const resp = await fetch('/nexread/marcacoes', {
      method: 'POST',
      headers: obterHeaders(),
      body: JSON.stringify({
        artigo_id: artigoAtualId,
        trecho: trecho,
        nota: (elNotaMarcacao && elNotaMarcacao.value.trim()) || '',
        cor: elCor ? elCor.value : 'amarelo'
      })
    });
    const dados = await resp.json();
    if (resp.ok && dados.ok) {
      if (dados.html_traduzido) {
        elLeitorHtml.innerHTML = dados.html_traduzido;
      }
      const div = document.createElement('div');
      div.className = 'item-salvo';
      div.textContent = '[' + dados.marcacao.cor + '] "' + dados.marcacao.trecho_original + '" - ' + (dados.marcacao.nota || 'sem nota');
      elListaMarcacoes.appendChild(div);
      elTrecho.value = '';
      elNotaMarcacao.value = '';
    }
  }

  async function salvarGravacaoAtual() {
    if (!artigoAtualId) {
      elStatus.textContent = 'Abra um artigo antes de gravar uma nota.';
      return;
    }
    const transcricao = (elTranscricao && elTranscricao.value.trim()) || '';
    if (!transcricao) return;
    const resp = await fetch('/nexread/gravacoes', {
      method: 'POST',
      headers: obterHeaders(),
      body: JSON.stringify({
        artigo_id: artigoAtualId,
        titulo: (elTituloGravacao && elTituloGravacao.value.trim()) || 'Nota de voz',
        transcricao: transcricao
      })
    });
    const dados = await resp.json();
    if (resp.ok && dados.ok) {
      const div = document.createElement('div');
      div.className = 'item-salvo';
      div.textContent = dados.gravacao.titulo + ': ' + dados.gravacao.transcricao;
      elListaGravacoes.appendChild(div);
      elTranscricao.value = '';
    }
  }

  async function salvarNaBiblioteca() {
    if (!artigoAtualId) {
      elStatus.textContent = 'Traduza um artigo antes de salvar na biblioteca.';
      return;
    }
    const disc = (elDisciplina && elDisciplina.value.trim()) || 'Geral';
    const resp = await fetch('/nexread/salvar-estudos', {
      method: 'POST',
      headers: obterHeaders(),
      body: JSON.stringify({
        artigo_id: artigoAtualId,
        disciplina: disc
      })
    });
    const dados = await resp.json();
    if (resp.ok && dados.ok) {
      elStatus.textContent = dados.aviso || 'Salvo na biblioteca de estudos.';
    } else {
      elStatus.textContent = dados.erro || 'Erro ao salvar na biblioteca.';
    }
  }

  async function conversarComIa(acaoCustom) {
    if (!artigoAtualId) {
      elStatus.textContent = 'Abra um artigo primeiro para conversar com a IA.';
      return;
    }
    const acao = acaoCustom || 'perguntar';
    const pergunta = (elPerguntaIa && elPerguntaIa.value.trim()) || '';
    const resp = await fetch('/nexread/conversar', {
      method: 'POST',
      headers: obterHeaders(),
      body: JSON.stringify({
        artigo_id: artigoAtualId,
        pergunta: pergunta,
        acao: acao,
        buscar_fontes_cientificas: Boolean(elCheckArtigos && elCheckArtigos.checked)
      })
    });
    const dados = await resp.json();
    if (resp.ok && dados.ok) {
      const bUser = document.createElement('div');
      bUser.className = 'msg-bolha msg-usuario';
      bUser.textContent = dados.pergunta;
      elChatHistorico.appendChild(bUser);

      const bAss = document.createElement('div');
      bAss.className = 'msg-bolha msg-assistente';
      bAss.textContent = dados.resposta;
      if (dados.fontes && dados.fontes.length) {
        const f = document.createElement('div');
        f.className = 'msg-fontes';
        f.textContent = 'Fontes: ' + dados.fontes.join(' | ');
        bAss.appendChild(f);
      }
      elChatHistorico.appendChild(bAss);
      elChatHistorico.scrollTop = elChatHistorico.scrollHeight;
      if (elPerguntaIa) elPerguntaIa.value = '';
    }
  }

  if (elBtnTraduzir) elBtnTraduzir.addEventListener('click', traduzirPagina);
  if (elBtnMarcar) elBtnMarcar.addEventListener('click', marcarTrechoAtual);
  if (elBtnSalvarGravacao) elBtnSalvarGravacao.addEventListener('click', salvarGravacaoAtual);
  if (elBtnSalvarEstudos) elBtnSalvarEstudos.addEventListener('click', salvarNaBiblioteca);
  if (elBtnPerguntarIa) elBtnPerguntarIa.addEventListener('click', () => conversarComIa('perguntar'));

  document.querySelectorAll('.btn-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      conversarComIa(btn.getAttribute('data-acao') || 'resumir');
    });
  });

  if (elBtnDitar) {
    elBtnDitar.addEventListener('click', () => {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRecognition) {
        elStatus.textContent = 'Reconhecimento de fala do navegador indisponivel; digite a transcricao.';
        return;
      }
      const rec = new SpeechRecognition();
      rec.lang = 'pt-BR';
      rec.onresult = (ev) => {
        const txt = ev.results[0][0].transcript;
        elTranscricao.value = (elTranscricao.value ? elTranscricao.value + ' ' : '') + txt;
      };
      rec.start();
    });
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/nexread/sw.js').catch(() => {});
  }
})();
