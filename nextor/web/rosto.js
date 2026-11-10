'use strict';

(function () {
  var CHAVE = 'nextor.token';
  var $ = function (id) { return document.getElementById(id); };

  var params = new URLSearchParams(location.search);
  if (params.get('token')) {
    try { localStorage.setItem(CHAVE, params.get('token')); } catch (e) { /* modo privado */ }
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

  function tocarFala(fala) {
    if (!fala || fala.id === ultimaFala) return;
    var primeira = ultimaFala === null;
    ultimaFala = fala.id;
    if (primeira || !$('com-voz').checked) return; // nao repete a ultima fala ao abrir a pagina
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

  function desenhar(estado) {
    estadoAtual = estado;
    var visto = Object.assign({}, estado);
    if (tocando) visto.atividade = 'falando';
    else if (estado.atividade === 'falando') visto.atividade = 'ocioso';
    window.Bichinho.render($('bichinho'), visto);
    if (estado.idioma) $('idioma').value = estado.idioma;
    document.querySelectorAll('[data-modo]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.modo === estado.modo));
    });
    document.querySelectorAll('[data-identidade]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.identidade === (estado.identidade || 'nextor')));
    });
    $('nome').textContent = { nextor: 'Nextor', claude: 'Claude', agy: 'agy' }[estado.identidade || 'nextor'];
    $('humor').textContent = FRASE_HUMOR[estado.emocao_usuario] || '';
    if (estado.ultima_resposta) {
      $('balao').textContent = estado.ultima_resposta;
      $('balao').hidden = false;
    }
  }

  function ouvirEventos() {
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
        $('balao').textContent = d.frase;
        $('balao').hidden = false;
      }).catch(function (err) { $('humor').textContent = err.message; });
    });
  });

  document.querySelectorAll('[data-modo]').forEach(function (b) {
    b.addEventListener('click', function () {
      api('/modo', { modo: b.dataset.modo }).then(function (d) {
        $('balao').textContent = [d.frase].concat(d.avisos || []).join(' ');
        $('balao').hidden = false;
      }).catch(function (err) { $('humor').textContent = err.message; });
    });
  });

  $('conversa').addEventListener('submit', function (e) {
    e.preventDefault();
    var texto = $('texto').value.trim();
    if (!texto) return;
    var botao = document.querySelector('.enviar');
    botao.disabled = true;
    api('/conversa', { texto: texto, falar: $('com-voz').checked }).then(function () {
      $('texto').value = '';
    }).catch(function (err) {
      $('balao').textContent = err.message;
      $('balao').hidden = false;
    }).then(function () { botao.disabled = false; $('texto').focus(); });
  });

  $('idioma').addEventListener('change', function () {
    api('/voz', { idioma: $('idioma').value }).catch(function (err) { $('humor').textContent = err.message; });
  });

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
  }

  if (!token) {
    $('aviso').hidden = false;
    window.Bichinho.render($('bichinho'), { expressao: 'sonolento' });
    return;
  }
  api('/estado').then(desenhar).catch(function (err) { $('humor').textContent = err.message; });
  ouvirEventos();
})();
