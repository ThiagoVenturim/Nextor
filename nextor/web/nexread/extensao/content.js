(function () {
  let artigoIdAtivo = null;

  async function traduzirDomAoVivo(cfg) {
    const seletores = 'article h1, article h2, article h3, article p, article blockquote, article li, main h1, main h2, main p, main blockquote';
    let elementos = Array.from(document.querySelectorAll(seletores));
    if (elementos.length === 0) {
      elementos = Array.from(document.querySelectorAll('h1, h2, h3, p, blockquote'));
    }
    const htmlFragmentos = elementos
      .filter((el) => (el.innerText || '').trim().length > 10)
      .map((el) => `<${el.tagName.toLowerCase()}>${el.innerText.trim()}</${el.tagName.toLowerCase()}>`)
      .join('\n');

    const resp = await fetch(cfg.servidor.replace(/\/$/, '') + '/nexread/traduzir', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Nextor-Token': cfg.token
      },
      body: JSON.stringify({
        conteudo_html: htmlFragmentos || document.body.innerHTML,
        url: window.location.href,
        titulo: document.title,
        motor: cfg.motor || 'local',
        modo_layout: 'bilingue',
        aberta_pelo_usuario: true
      })
    });
    const dados = await resp.json();
    if (!resp.ok || !dados.ok) {
      return { ok: false, mensagem: dados.erro || 'Falha ao traduzir pagina.' };
    }
    artigoIdAtivo = dados.artigo.id;
    const blocos = dados.artigo.blocos || [];
    let idx = 0;
    for (const el of elementos) {
      if ((el.innerText || '').trim().length <= 10) continue;
      if (idx >= blocos.length) break;
      const b = blocos[idx++];
      if (b && b.texto_traduzido && !el.querySelector('.nexread-inline-traducao')) {
        const divTrad = document.createElement('div');
        divTrad.className = 'nexread-inline-traducao';
        divTrad.setAttribute('data-nexread-bloco', b.id);
        divTrad.textContent = b.texto_traduzido;
        el.appendChild(divTrad);
      }
    }
    return { ok: true, mensagem: 'Pagina traduzida mantendo o layout (' + blocos.length + ' blocos).' };
  }

  async function marcarSelecaoNaPagina(cfg) {
    const sel = window.getSelection ? window.getSelection().toString().trim() : '';
    if (!sel || !artigoIdAtivo) {
      return { ok: false, mensagem: 'Traduza a pagina e selecione um trecho primeiro.' };
    }
    const nota = window.prompt('Anotacao para o trecho selecionado:', '') || '';
    const resp = await fetch(cfg.servidor.replace(/\/$/, '') + '/nexread/marcacoes', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Nextor-Token': cfg.token
      },
      body: JSON.stringify({
        artigo_id: artigoIdAtivo,
        trecho: sel,
        nota: nota,
        cor: 'amarelo'
      })
    });
    const dados = await resp.json();
    return { ok: Boolean(dados.ok), mensagem: dados.ok ? 'Trecho marcado no NexRead.' : (dados.erro || 'Erro.') };
  }

  async function salvarArtigoNosEstudos(cfg) {
    if (!artigoIdAtivo) {
      return { ok: false, mensagem: 'Traduza a pagina aberta antes de salvar nos estudos.' };
    }
    const resp = await fetch(cfg.servidor.replace(/\/$/, '') + '/nexread/salvar-estudos', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Nextor-Token': cfg.token
      },
      body: JSON.stringify({
        artigo_id: artigoIdAtivo,
        disciplina: cfg.disciplina || 'Geral'
      })
    });
    const dados = await resp.json();
    return { ok: Boolean(dados.ok), mensagem: dados.aviso || dados.erro || 'Salvo.' };
  }

  function abrirPainelLateralIa(cfg) {
    let painel = document.getElementById('nexread-sidebar-ia');
    if (painel) {
      painel.remove();
      return { ok: true, mensagem: 'Painel lateral fechado.' };
    }
    painel = document.createElement('aside');
    painel.id = 'nexread-sidebar-ia';
    painel.className = 'nexread-sidebar-ia';
    painel.innerHTML = `
      <div class="nexread-sb-topo">
        <strong>Conversar com a IA sobre este tema</strong>
      </div>
      <div id="nexread-sb-respostas" class="nexread-sb-respostas"></div>
      <textarea id="nexread-sb-pergunta" rows="3" placeholder="Pergunte, peca resumo ou discuta com base nas fontes deste texto..."></textarea>
      <button id="nexread-sb-enviar">Perguntar com Fontes</button>
    `;
    document.body.appendChild(painel);
    document.getElementById('nexread-sb-enviar')?.addEventListener('click', async () => {
      const inp = document.getElementById('nexread-sb-pergunta');
      const box = document.getElementById('nexread-sb-respostas');
      if (!inp || !box || !artigoIdAtivo) return;
      const pergunta = inp.value.trim();
      const resp = await fetch(cfg.servidor.replace(/\/$/, '') + '/nexread/conversar', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Nextor-Token': cfg.token
        },
        body: JSON.stringify({
          artigo_id: artigoIdAtivo,
          pergunta: pergunta,
          acao: pergunta ? 'perguntar' : 'resumir'
        })
      });
      const dados = await resp.json();
      if (dados.ok) {
        const p = document.createElement('div');
        p.className = 'nexread-sb-msg';
        p.textContent = dados.resposta + (dados.fontes && dados.fontes.length ? ' [Fontes: ' + dados.fontes.join('; ') + ']' : '');
        box.appendChild(p);
        inp.value = '';
      }
    });
    return { ok: true, mensagem: 'Painel de conversa IA aberto na pagina.' };
  }

  if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (!msg || !msg.acao) return false;
      if (msg.acao === 'traduzir') {
        traduzirDomAoVivo(msg).then(sendResponse);
        return true;
      }
      if (msg.acao === 'marcar') {
        marcarSelecaoNaPagina(msg).then(sendResponse);
        return true;
      }
      if (msg.acao === 'salvar_estudos') {
        salvarArtigoNosEstudos(msg).then(sendResponse);
        return true;
      }
      if (msg.acao === 'abrir_ia') {
        sendResponse(abrirPainelLateralIa(msg));
        return false;
      }
      return false;
    });
  }
})();
