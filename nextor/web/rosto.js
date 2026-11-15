'use strict';

(function (global) {
  var CHAVE = 'nextor.token';
  var $ = function (id) { return document.getElementById(id); };

  var params = new URLSearchParams(location.search);
  var hashParams = new URLSearchParams((location.hash || '').replace(/^#/, ''));
  var tokenUrl = params.get('token') || hashParams.get('token');
  if (tokenUrl) {
    try { localStorage.setItem(CHAVE, tokenUrl); } catch (e) { /* modo privado */ }
    history.replaceState(null, '', location.pathname);
  }
  var token = '';
  try { token = localStorage.getItem(CHAVE) || ''; } catch (e) { token = ''; }

  var FRASE_HUMOR = {
    feliz: 'Que bom te ver animado.',
    triste: 'Percebi que voce nao esta bem. Estou aqui.',
    ansioso: 'Parece que esta ansioso. Vamos com calma, um passo de cada vez.',
    cansado: 'Voce parece cansado. Uma pausa pode ajudar.',
    irritado: 'Parece um dia dificil. Vamos resolver por partes.',
    neutro: '',
  };

  var ROTULO_ATIVIDADE = {
    ocioso: 'Ocioso',
    ouvindo: 'Ouvindo',
    pensando: 'Pensando',
    falando: 'Falando',
    gravando: 'Gravando',
    erro: 'Erro',
  };

  var ROTULO_TIPO_RESULTADO = {
    tarefas: 'Lista de tarefas',
    quiz: 'Quiz',
    resumo: 'Resumo',
  };

  function api(caminho, corpo) {
    var opcoes = { headers: { 'X-Nextor-Token': token } };
    if (corpo) {
      opcoes.method = 'POST';
      opcoes.headers['Content-Type'] = 'application/json';
      opcoes.body = JSON.stringify(corpo);
    }
    return fetch(caminho, opcoes).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.erro || ('Erro ' + r.status));
        return d;
      });
    });
  }

  var ultimaFala = null;
  var tocando = false;
  var estadoAtual = {};
  var gravacaoAtiva = false;

  function normalizarAtividade(estado) {
    if (global.Bichinho && typeof global.Bichinho.normalizarAtividade === 'function') {
      return global.Bichinho.normalizarAtividade(estado);
    }
    var a = String((estado && estado.atividade) || 'ocioso').toLowerCase();
    if (a.indexOf('gravando') === 0) return 'gravando';
    if (a === 'traduzindo_voz') return 'ouvindo';
    if (a === 'normal' || !Object.prototype.hasOwnProperty.call(ROTULO_ATIVIDADE, a)) return 'ocioso';
    return a;
  }

  function verificarGravacao(estado) {
    if (global.Bichinho && typeof global.Bichinho.emGravacao === 'function') {
      return global.Bichinho.emGravacao(estado);
    }
    if (!estado) return false;
    if (estado.gravando === true) return true;
    return String(estado.atividade || '').toLowerCase().indexOf('gravando') === 0;
  }

  function forcarIndicadorGravacao(ativo, detalhe) {
    gravacaoAtiva = Boolean(ativo);
    if (document.body) {
      document.body.setAttribute('data-gravando', String(gravacaoAtiva));
    }
    var ind = $('indicador-gravacao');
    if (!ind) return;
    if (gravacaoAtiva) {
      ind.hidden = false;
      ind.removeAttribute('hidden');
      ind.style.display = 'flex';
      ind.style.visibility = 'visible';
      ind.style.opacity = '1';
      if ($('detalhe-gravacao')) {
        $('detalhe-gravacao').textContent = detalhe || 'Microfone ou tela em gravacao ativa';
      }
    } else {
      ind.hidden = true;
      ind.style.display = '';
    }
  }

  function protegerIndicadorGravacao() {
    var ind = $('indicador-gravacao');
    if (!ind || typeof MutationObserver === 'undefined') return;
    var obs = new MutationObserver(function () {
      if (gravacaoAtiva && (ind.hidden || ind.style.display === 'none' || ind.style.visibility === 'hidden' || ind.style.opacity === '0')) {
        forcarIndicadorGravacao(true, estadoAtual.detalhe);
      }
    });
    obs.observe(ind, { attributes: true, attributeFilter: ['hidden', 'style', 'class'] });
  }

  function tocarFala(fala) {
    if (!fala || fala.id === ultimaFala) return;
    var primeira = ultimaFala === null;
    ultimaFala = fala.id;
    if (primeira || ($('com-voz') && !$('com-voz').checked)) return;
    fetch('/fala/' + encodeURIComponent(fala.id), { headers: { 'X-Nextor-Token': token } })
      .then(function (r) { if (!r.ok) throw new Error('audio ' + r.status); return r.blob(); })
      .then(function (blob) {
        var audio = new Audio(URL.createObjectURL(blob));
        tocando = true;
        desenhar(estadoAtual);
        audio.onended = audio.onerror = function () { tocando = false; desenhar(estadoAtual); };
        return audio.play();
      })
      .catch(function () { tocando = false; });
  }

  function renderResultado(resultado) {
    var painel = $('painel-resultado');
    if (!painel) return;
    if (!resultado || typeof resultado !== 'object') {
      painel.hidden = true;
      return;
    }

    var tipo = String(resultado.tipo || 'resultado').toLowerCase();
    painel.hidden = false;
    painel.setAttribute('data-tipo', tipo);

    if ($('resultado-tipo')) {
      $('resultado-tipo').textContent = ROTULO_TIPO_RESULTADO[tipo] || resultado.tipo || 'Resultado';
    }
    if ($('resultado-titulo')) {
      $('resultado-titulo').textContent = resultado.titulo || ROTULO_TIPO_RESULTADO[tipo] || 'Resultado';
    }

    var elResumo = $('resultado-resumo');
    if (elResumo) {
      if (resultado.resumo) {
        elResumo.textContent = resultado.resumo;
        elResumo.hidden = false;
      } else {
        elResumo.textContent = '';
        elResumo.hidden = true;
      }
    }

    var elLista = $('resultado-lista');
    if (elLista) {
      elLista.replaceChildren();
      var itens = Array.isArray(resultado.itens) ? resultado.itens : [];
      if (itens.length > 0 && tipo !== 'quiz') {
        itens.forEach(function (item) {
          var li = document.createElement('li');
          var ehObjeto = item && typeof item === 'object';
          var atrasada = ehObjeto && Boolean(item.atrasada);
          li.className = 'resultado-item' + (atrasada ? ' atrasada' : '');

          var spanTexto = document.createElement('span');
          spanTexto.className = 'resultado-item-texto';
          spanTexto.textContent = ehObjeto ? (item.titulo || item.ponto || item.texto || '') : String(item);
          li.appendChild(spanTexto);

          var metaPartes = [];
          if (ehObjeto) {
            if (item.atrasada) metaPartes.push('Atrasada');
            else if (item.para_hoje) metaPartes.push('Hoje');
            if (item.fonte) metaPartes.push(item.fonte);
            if (item.prazo) metaPartes.push(item.prazo);
          }
          if (metaPartes.length > 0) {
            var spanMeta = document.createElement('span');
            spanMeta.className = 'resultado-item-meta';
            spanMeta.textContent = metaPartes.join(' · ');
            li.appendChild(spanMeta);
          }
          elLista.appendChild(li);
        });
        elLista.hidden = false;
      } else {
        elLista.hidden = true;
      }
    }

    var elQuiz = $('resultado-quiz');
    if (elQuiz) {
      if (tipo === 'quiz') {
        elQuiz.hidden = false;
        if ($('quiz-pergunta')) {
          $('quiz-pergunta').textContent = resultado.pergunta || '';
        }
        var boxOpcoes = $('quiz-opcoes');
        if (boxOpcoes) {
          boxOpcoes.replaceChildren();
          var opcoes = Array.isArray(resultado.opcoes) ? resultado.opcoes : [];
          if (opcoes.length === 0 && resultado.modalidade === 'verdadeiro_falso') {
            opcoes = ['Verdadeiro', 'Falso'];
          }
          opcoes.forEach(function (op) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'quiz-opcao';
            btn.textContent = String(op);
            btn.addEventListener('click', function () {
              responderOpcaoQuiz(resultado, String(op));
            });
            boxOpcoes.appendChild(btn);
          });
        }
        var elFeedback = $('quiz-feedback');
        if (elFeedback) {
          var fb = resultado.mensagem || resultado.explicacao || '';
          if (fb) {
            elFeedback.textContent = fb;
            elFeedback.hidden = false;
          } else {
            elFeedback.textContent = '';
            elFeedback.hidden = true;
          }
        }
      } else {
        elQuiz.hidden = true;
      }
    }
  }

  function responderOpcaoQuiz(resultadoQuiz, opcaoTexto) {
    var m = opcaoTexto.match(/^([A-Da-d])[\):\.\s]/);
    var resp = m ? m[1].toUpperCase() : opcaoTexto;
    if (resultadoQuiz && resultadoQuiz.questao_id) {
      api('/estudos/quiz/responder', { questao_id: resultadoQuiz.questao_id, resposta: resp })
        .then(function () { return api('/estado'); })
        .then(desenhar)
        .catch(function (err) { mostrarErro(err.message); });
    } else {
      api('/comando', { texto: resp })
        .then(function () { return api('/estado'); })
        .then(desenhar)
        .catch(function (err) { mostrarErro(err.message); });
    }
  }

  function mostrarErro(mensagem) {
    var msg = mensagem || 'Falha ao comunicar com o assistente.';
    desenhar(Object.assign({}, estadoAtual, {
      atividade: 'erro',
      expressao: 'erro',
      erro: msg,
      legenda: msg,
    }));
  }

  function desenhar(estado) {
    estadoAtual = estado || {};
    var visto = Object.assign({}, estadoAtual);
    var ativ = normalizarAtividade(visto);
    if (tocando) ativ = 'falando';
    if (visto.erro && ativ === 'ocioso') ativ = 'erro';
    visto.atividade = ativ;

    var grav = verificarGravacao(estadoAtual);
    visto.gravando = grav;

    if (document.body) {
      document.body.setAttribute('data-atividade', ativ);
    }

    forcarIndicadorGravacao(grav, estadoAtual.detalhe);

    var badgeEstado = $('estado-assistente');
    if (badgeEstado) {
      badgeEstado.setAttribute('data-atividade', ativ);
    }
    if ($('estado-rotulo')) {
      $('estado-rotulo').textContent = ROTULO_ATIVIDADE[ativ] || 'Ocioso';
    }

    if ($('bichinho') && global.Bichinho) {
      global.Bichinho.render($('bichinho'), visto);
    }

    if (estadoAtual.idioma && $('idioma')) {
      $('idioma').value = estadoAtual.idioma;
    }

    document.querySelectorAll('[data-modo]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.modo === (estadoAtual.modo || 'normal')));
    });
    document.querySelectorAll('[data-identidade]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.identidade === (estadoAtual.identidade || 'nextor')));
    });

    if ($('nome')) {
      $('nome').textContent = { nextor: 'Nextor', claude: 'Claude', agy: 'agy' }[estadoAtual.identidade || 'nextor'] || 'Nextor';
    }
    if ($('humor')) {
      $('humor').textContent = FRASE_HUMOR[estadoAtual.emocao_usuario] || '';
    }

    var alertaErro = $('alerta-erro');
    if (alertaErro) {
      if (ativ === 'erro' || estadoAtual.expressao === 'erro' || estadoAtual.erro) {
        alertaErro.hidden = false;
        if ($('texto-erro')) {
          $('texto-erro').textContent = estadoAtual.erro || estadoAtual.ultima_resposta || 'Falha ao comunicar com o assistente.';
        }
      } else {
        alertaErro.hidden = true;
      }
    }

    if ($('ultima-pergunta')) {
      if (estadoAtual.ultima_mensagem) {
        $('ultima-pergunta').textContent = 'Voce: ' + estadoAtual.ultima_mensagem;
        $('ultima-pergunta').hidden = false;
      } else {
        $('ultima-pergunta').hidden = true;
      }
    }

    if ($('balao')) {
      var legenda = estadoAtual.legenda || estadoAtual.ultima_resposta;
      if (!legenda) {
        if (ativ === 'ouvindo') legenda = 'Ouvindo voce... pode falar.';
        else if (ativ === 'pensando') legenda = 'Pensando na resposta...';
        else if (ativ === 'gravando') legenda = estadoAtual.detalhe || 'Gravacao em andamento.';
        else if (ativ === 'erro') legenda = estadoAtual.erro || 'Ocorreu um erro ao processar o pedido.';
        else legenda = 'Pronto para ouvir. Diga "ei Nextor" ou envie uma mensagem.';
      }
      $('balao').textContent = legenda;
      $('balao').hidden = false;
    }

    renderResultado(estadoAtual.resultado);
  }

  function ouvirEventos() {
    if (typeof EventSource === 'undefined') return;
    var fonte = new EventSource('/eventos?token=' + encodeURIComponent(token));
    fonte.onmessage = function (e) {
      var estado = JSON.parse(e.data);
      desenhar(estado);
      tocarFala(estado.fala);
    };
    fonte.onerror = function () { fonte.close(); setTimeout(ouvirEventos, 3000); };
  }

  document.querySelectorAll('[data-identidade]').forEach(function (b) {
    b.addEventListener('click', function () {
      api('/identidade', { identidade: b.dataset.identidade }).then(function (d) {
        desenhar(Object.assign({}, estadoAtual, d.estado || {}, { ultima_resposta: d.frase, legenda: d.frase }));
      }).catch(function (err) { mostrarErro(err.message); });
    });
  });

  document.querySelectorAll('[data-modo]').forEach(function (b) {
    b.addEventListener('click', function () {
      api('/modo', { modo: b.dataset.modo }).then(function (d) {
        var textoModo = [d.frase].concat(d.avisos || []).join(' ');
        desenhar(Object.assign({}, estadoAtual, d.estado || {}, { ultima_resposta: textoModo, legenda: textoModo }));
      }).catch(function (err) { mostrarErro(err.message); });
    });
  });

  if ($('conversa')) {
    $('conversa').addEventListener('submit', function (e) {
      e.preventDefault();
      var texto = $('texto').value.trim();
      if (!texto) return;
      var botao = document.querySelector('.enviar');
      if (botao) botao.disabled = true;
      desenhar(Object.assign({}, estadoAtual, {
        atividade: 'pensando',
        ultima_mensagem: texto,
        erro: '',
      }));
      api('/conversa', { texto: texto, falar: $('com-voz') ? $('com-voz').checked : false }).then(function (d) {
        $('texto').value = '';
        if (d && d.estado) desenhar(d.estado);
      }).catch(function (err) {
        mostrarErro(err.message);
      }).then(function () {
        if (botao) botao.disabled = false;
        if ($('texto')) $('texto').focus();
      });
    });
  }

  if ($('idioma')) {
    $('idioma').addEventListener('change', function () {
      api('/voz', { idioma: $('idioma').value }).catch(function (err) { mostrarErro(err.message); });
    });
  }

  if ($('tela-cheia')) {
    $('tela-cheia').addEventListener('click', function () {
      var doc = document;
      var el = doc.documentElement;
      if (!doc.fullscreenElement) {
        if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
        $('tela-cheia').setAttribute('aria-pressed', 'true');
      } else {
        if (doc.exitFullscreen) doc.exitFullscreen().catch(function () {});
        $('tela-cheia').setAttribute('aria-pressed', 'false');
      }
    });
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
  }

  protegerIndicadorGravacao();

  global.NextorRosto = {
    desenhar: desenhar,
    renderResultado: renderResultado,
    mostrarErro: mostrarErro,
    estado: function () { return estadoAtual; },
  };

  if (!token) {
    if ($('aviso')) $('aviso').hidden = false;
    if ($('bichinho') && global.Bichinho) {
      global.Bichinho.render($('bichinho'), { expressao: 'sonolento', atividade: 'ocioso' });
    }
    return;
  }
  api('/estado').then(desenhar).catch(function (err) { mostrarErro(err.message); });
  ouvirEventos();
})(typeof window !== 'undefined' ? window : this);
