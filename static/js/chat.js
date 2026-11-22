/* Mensajes internos (mensajes.py, /mensajes/api). Es el chat.js de
   gestion_adm (22/11/2026), sin cambios de lógica; gestion_adm lo había
   copiado del chat de la financiera, sin el hilo de las solicitudes ni las
   llamadas.
   Dos piezas, cada una se arma si está su elemento en la página:
     [data-chat-contador]  el botón Mensajes de la barra: cada 20 s pide
                           cuántas conversaciones tienen algo sin leer.
     [data-chat-app]       la pantalla Mensajes: lista + conversación.
   Las consultas automáticas se frenan con la pestaña oculta (el contador
   sigue, más espaciado, para que el aviso suene en otra pestaña). Si la
   sesión se cerró, se dejan de hacer.
   Los POST van con el encabezado X-Chat que pide mensajes.py (`sinCartel` y
   X-Sin-Cartel son de gestion_adm, cuyo fetch tapa la pantalla con
   «Procesando…»; acá no hace falta y no molestan). */
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="chat-api"]');
  if (!meta) return;
  var API = meta.content;
  var sinSesion = false;

  // ── Pedidos ──────────────────────────────────────────────────────────
  function pedir(params, post) {
    if (sinSesion) return Promise.reject(new Error('La sesión se cerró. Volvé a ingresar.'));
    var url = API, opt = { credentials: 'same-origin', headers: { 'Accept': 'application/json' }, sinCartel: true };
    if (post) {
      var fd = post instanceof FormData ? post : new FormData();
      if (!(post instanceof FormData)) Object.keys(post).forEach(function (k) {
        var v = post[k];
        if (Array.isArray(v)) v.forEach(function (x) { fd.append(k + '[]', x); }); else fd.append(k, v);
      });
      opt.method = 'POST';
      opt.body = fd;
      opt.headers['X-Chat'] = '1';
      opt.headers['X-Sin-Cartel'] = '1';
    } else {
      url += '?' + new URLSearchParams(params).toString();
    }
    return fetch(url, opt).then(function (r) {
      if (r.status === 413) throw new Error('El archivo supera lo que acepta el servidor.');
      return r.json().catch(function () { throw new Error('El servidor no respondió bien (' + r.status + ').'); })
        .then(function (d) {
          if (r.status === 401) { sinSesion = true; avisarSesion(); }
          if (!d.ok) throw new Error(d.error || 'No se pudo.');
          return d;
        });
    });
  }

  function avisarSesion() {
    document.querySelectorAll('[data-chat-form]').forEach(function (f) {
      var e = f.querySelector('.chat-error');
      if (e) { e.textContent = 'La sesión se cerró. Volvé a ingresar para seguir.'; e.hidden = false; }
    });
  }

  /**
   * Repite fn cada ms mientras la pestaña está visible (y una vez al volver a
   * ella). Con msOculto sigue también con la pestaña oculta, más espaciado.
   */
  function cadaTanto(fn, ms, msOculto) {
    var t = null, activo = true;
    function prog() { clearTimeout(t); if (activo && !sinSesion) t = setTimeout(correr, document.hidden && msOculto ? msOculto : ms); }
    function correr() { if (document.hidden && !msOculto) return; Promise.resolve(fn()).catch(function () {}).then(prog); }
    document.addEventListener('visibilitychange', function () { if (!document.hidden && activo) { clearTimeout(t); correr(); } });
    prog();
    return { parar: function () { activo = false; clearTimeout(t); }, ya: function () { clearTimeout(t); correr(); } };
  }

  function el(tag, clase, texto) {
    var e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto != null) e.textContent = texto;
    return e;
  }

  var MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  function fechaTxt(iso) {
    var hoy = new Date(), ay = new Date(Date.now() - 864e5);
    function iso8(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
    if (iso === iso8(hoy)) return 'Hoy';
    if (iso === iso8(ay)) return 'Ayer';
    var p = iso.split('-');
    return (+p[2]) + ' de ' + MESES[+p[1] - 1] + (+p[0] !== hoy.getFullYear() ? ' de ' + p[0] : '');
  }

  // ── Sonido ───────────────────────────────────────────────────────────
  // Suena cuando llega un mensaje más nuevo que el último que ya sonó. Ese id
  // se guarda en el navegador (compartido entre pestañas): con dos pestañas
  // abiertas suena una vez. Se apaga y prende con 🔔 en la pantalla Mensajes.
  var CLAVE_SONIDO = 'gadm_chat_sonido', CLAVE_SONADO = 'gadm_chat_sonado', CLAVE_SONO_EL = 'gadm_chat_sono_el';
  function leerLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardarLS(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function sonidoActivo() { return leerLS(CLAVE_SONIDO) !== '0'; }

  /** Un «ding» de dos notas, armado acá (WAV en memoria): no hace falta ningún archivo de sonido. */
  function crearDing() {
    var sr = 22050, n = Math.floor(sr * 0.55), datos = new Int16Array(n);
    var notas = [[880, 0], [1318.5, 0.11]];
    for (var i = 0; i < n; i++) {
      var t = i / sr, v = 0;
      for (var k = 0; k < notas.length; k++) {
        var u = t - notas[k][1];
        if (u >= 0) v += Math.sin(2 * Math.PI * notas[k][0] * u) * Math.exp(-u * 8) * Math.min(1, u * 200);
      }
      datos[i] = Math.max(-1, Math.min(1, v * 0.35)) * 32767;
    }
    var buf = new ArrayBuffer(44 + n * 2), dv = new DataView(buf);
    function txt(o, s) { for (var j = 0; j < s.length; j++) dv.setUint8(o + j, s.charCodeAt(j)); }
    txt(0, 'RIFF'); dv.setUint32(4, 36 + n * 2, true); txt(8, 'WAVE'); txt(12, 'fmt ');
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, sr, true);
    dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); txt(36, 'data'); dv.setUint32(40, n * 2, true);
    for (var x = 0; x < n; x++) dv.setInt16(44 + x * 2, datos[x], true);
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }
  var audioDing = null;
  function elDing() {
    if (!audioDing) { audioDing = new Audio(crearDing()); audioDing.volume = 0.7; }
    return audioDing;
  }
  function ding() {
    try {
      var a = elDing();
      a.currentTime = 0;
      var p = a.play();
      if (p && p.catch) p.catch(function () {});     // sin un click previo en la página, el navegador puede no dejar
    } catch (e) {}
  }
  // Safari (iPhone) sólo deja sonar si ya hubo un toque en la página: el primero lo «habilita» en silencio.
  function habilitar() {
    document.removeEventListener('pointerdown', habilitar, true);
    document.removeEventListener('keydown', habilitar, true);
    try {
      var a = elDing();
      a.muted = true;
      var p = a.play();
      var fin = function () { a.pause(); a.currentTime = 0; a.muted = false; };
      if (p && p.then) p.then(fin, fin); else fin();
    } catch (e) {}
  }
  document.addEventListener('pointerdown', habilitar, true);
  document.addEventListener('keydown', habilitar, true);

  /** Anota que ya se vio hasta ese mensaje, sin sonar. */
  function anotarVisto(ultimo) {
    var g = leerLS(CLAVE_SONADO);
    if (g === null || (+ultimo || 0) > +g) guardarLS(CLAVE_SONADO, String(+ultimo || 0));
  }

  /** Suena si «ultimo» es más nuevo que lo último que ya sonó. La primera vez en el navegador sólo anota. */
  function avisarNuevo(ultimo) {
    ultimo = +ultimo || 0;
    var g = leerLS(CLAVE_SONADO);
    if (g === null) { guardarLS(CLAVE_SONADO, String(ultimo)); return; }
    if (ultimo <= +g) return;
    guardarLS(CLAVE_SONADO, String(ultimo));
    if (!sonidoActivo()) return;
    var ahora = Date.now();
    if (ahora - (+(leerLS(CLAVE_SONO_EL) || 0)) < 3000) return;      // dos avisos juntos: suena uno
    guardarLS(CLAVE_SONO_EL, String(ahora));
    ding();
  }

  // ── El botón Mensajes de la barra ────────────────────────────────────────
  var contador = document.querySelector('[data-chat-contador]');
  var tituloBase = document.title;
  function ponerContador(n) {
    document.title = (n ? '(' + n + ') ' : '') + tituloBase;
    if (!contador) return;
    var b = contador.querySelector('.chat-badge');
    var antes = +b.textContent || 0;
    if (n > antes) {                       // llegó algo nuevo: el globito late
      contador.classList.remove('con-nuevos');
      void contador.offsetWidth;
      contador.classList.add('con-nuevos');
    }
    b.textContent = n > 99 ? '99+' : String(n);
    b.hidden = n === 0;
    contador.title = n ? (n === 1 ? 'Una conversación con mensajes nuevos' : n + ' conversaciones con mensajes nuevos') : 'Mensajes';
  }
  if (contador) {
    ponerContador(+contador.getAttribute('data-chat-contador') || 0);
    avisarNuevo(contador.getAttribute('data-chat-ultimo'));
    cadaTanto(function () {
      return pedir({ accion: 'contador' }).then(function (d) { ponerContador(d.no_leidos); avisarNuevo(d.ultimo); });
    }, 20000, 60000);
  }

  // ── Una conversación ─────────────────────────────────────────────────
  /* opciones: { conv, para, cada, alCambiar(conv), alLeer(), alEnviar() } */
  function Hilo(raiz, op) {
    this.raiz = raiz;
    this.op = op || {};
    this.conv = op.conv || null;
    this.ultimo = 0;
    this.primero = 0;
    this.lectores = [];            // [{ nombre, hasta }] de los demás participantes
    this.ultimaFecha = null;
    this.armar();
    this.cargar();
    var self = this;
    this.reloj = cadaTanto(function () { return self.nuevos(); }, op.cada || 4000);
  }

  Hilo.prototype.armar = function () {
    var self = this, r = this.raiz;
    r.innerHTML = '';
    this.lista = el('div', 'chat-msjs');
    this.lista.setAttribute('aria-live', 'polite');
    this.mas = el('button', 'btn btn-ghost btn-sm chat-mas', 'Ver mensajes anteriores');
    this.mas.type = 'button';
    this.mas.hidden = true;
    this.mas.addEventListener('click', function () { self.anteriores(); });
    this.vacio = el('div', 'chat-vacio', 'Todavía no hay mensajes.');
    this.vacio.hidden = true;
    this.lista.appendChild(this.mas);
    this.lista.appendChild(this.vacio);
    this.cuerpo = el('div', 'chat-cuerpo');
    this.lista.appendChild(this.cuerpo);

    var f = el('form', 'chat-form');
    f.setAttribute('data-chat-form', '');
    f.innerHTML =
      '<div class="chat-error" hidden></div>' +
      '<div class="chat-archivo" hidden><span></span><button type="button" class="btn-accion borrar" title="Quitar el archivo" aria-label="Quitar el archivo">×</button></div>' +
      '<div class="chat-fila">' +
      '<label class="btn btn-ghost chat-clip" title="Adjuntar archivo (PDF, imagen, Word, Excel)"><input type="file" hidden accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.doc,.docx,.xls,.xlsx,.csv,.txt,image/*,application/pdf">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.4 11.1l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/></svg></label>' +
      '<button type="button" class="btn btn-ghost chat-emoji-btn" title="Emojis" aria-label="Emojis" aria-expanded="false">😊</button>' +
      '<textarea rows="1" maxlength="4000" placeholder="Escribí un mensaje…" title="Enter envía · Shift+Enter baja de renglón" aria-label="Mensaje"></textarea>' +
      '<button type="button" class="btn btn-ghost chat-mic" title="Grabar un mensaje de voz" aria-label="Grabar un mensaje de voz" hidden>' +
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg></button>' +
      '<button type="submit" class="btn btn-primary chat-enviar" title="Enviar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg><span>Enviar</span></button>' +
      '</div>' +
      '<div class="chat-grabando" hidden>' +
      '<button type="button" class="btn btn-ghost chat-grab-cancelar" title="Descartar (Esc)">Descartar</button>' +
      '<span class="chat-grab-punto" aria-hidden="true"></span><span class="chat-grab-tiempo">0:00</span>' +
      '<span class="chat-grab-txt">Grabando… </span>' +
      '<button type="button" class="btn btn-primary chat-grab-enviar" title="Enviar el mensaje de voz">Enviar</button>' +
      '</div>';
    this.form = f;
    this.txt = f.querySelector('textarea');
    this.file = f.querySelector('input[type=file]');
    this.err = f.querySelector('.chat-error');
    this.chipArchivo = f.querySelector('.chat-archivo');
    this.btnEmoji = f.querySelector('.chat-emoji-btn');
    this.btnMic = f.querySelector('.chat-mic');
    this.barraGrab = f.querySelector('.chat-grabando');
    if (puedeGrabar()) {
      this.btnMic.hidden = false;
      this.btnMic.addEventListener('click', function () { self.grabar(); });
      f.querySelector('.chat-grab-cancelar').addEventListener('click', function () { self.pararGrabacion(false); });
      f.querySelector('.chat-grab-enviar').addEventListener('click', function () { self.pararGrabacion(true); });
      r.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && self.rec) { e.preventDefault(); e.stopPropagation(); self.pararGrabacion(false); }
      });
    }
    this.btnEmoji.addEventListener('click', function () { self.emojis(); });

    this.txt.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); self.enviar(); }
    });
    this.txt.addEventListener('input', function () { self.alto(); });
    this.file.addEventListener('change', function () { self.mostrarArchivo(); });
    this.chipArchivo.querySelector('button').addEventListener('click', function () { self.file.value = ''; self.mostrarArchivo(); });
    f.addEventListener('submit', function (e) { e.preventDefault(); self.enviar(); });
    // Pegar una imagen (captura de pantalla) la adjunta.
    this.txt.addEventListener('paste', function (e) {
      var it = e.clipboardData && e.clipboardData.files;
      if (it && it.length && window.DataTransfer) {
        var dt = new DataTransfer();
        dt.items.add(it[0]);
        self.file.files = dt.files;
        self.mostrarArchivo();
        e.preventDefault();
      }
    });
    // Arrastrar y soltar un archivo sobre la conversación.
    ['dragover', 'drop'].forEach(function (ev) {
      r.addEventListener(ev, function (e) {
        if (!e.dataTransfer || !e.dataTransfer.types || Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') === -1) return;
        e.preventDefault();
        if (ev === 'drop' && e.dataTransfer.files.length) { self.file.files = e.dataTransfer.files; self.mostrarArchivo(); }
      });
    });

    r.appendChild(this.lista);
    r.appendChild(f);
  };

  Hilo.prototype.alto = function () {
    this.txt.style.height = 'auto';
    this.txt.style.height = Math.min(this.txt.scrollHeight, 160) + 'px';
  };

  Hilo.prototype.mostrarArchivo = function () {
    var f = this.file.files[0];
    this.chipArchivo.hidden = !f;
    if (f) this.chipArchivo.querySelector('span').textContent = '📎 ' + f.name + ' (' + (f.size < 1048576 ? Math.max(1, Math.round(f.size / 1024)) + ' KB' : (f.size / 1048576).toFixed(1).replace('.', ',') + ' MB') + ')';
  };

  Hilo.prototype.error = function (m) {
    this.err.textContent = m || '';
    this.err.hidden = !m;
  };

  Hilo.prototype.params = function (extra) {
    var p = { accion: 'mensajes', conv: this.conv };
    Object.keys(extra || {}).forEach(function (k) { p[k] = extra[k]; });
    return p;
  };

  Hilo.prototype.alFondo = function () {
    var l = this.lista;
    return l.scrollHeight - l.scrollTop - l.clientHeight < 60;
  };

  Hilo.prototype.cargar = function () {
    var self = this;
    if (!this.conv) { this.vacio.hidden = false; return Promise.resolve(); }
    this.cargando = true;
    return pedir(this.params({ leer: 1 })).then(function (d) {
      self.cuerpo.innerHTML = '';
      self.ultimaFecha = null;
      self.ultimo = 0;
      self.primero = 0;
      self.info = d.conv;
      if (d.conv) self.conv = d.conv.id;
      self.lectores = d.lectores || [];
      self.presencia = d.presencia || null;
      self.mas.hidden = !(d.conv && d.conv.hay_mas);
      self.agregar(d.mensajes, true);
      self.vacio.hidden = d.mensajes.length > 0;
      self.marcarVistos();
      self.lista.scrollTop = self.lista.scrollHeight;
      if (self.op.alCambiar) self.op.alCambiar(d.conv);
      if (self.op.alLeer) self.op.alLeer();
    }).catch(function (e) { self.error(e.message); })
      .then(function () { self.cargando = false; });
  };

  Hilo.prototype.nuevos = function () {
    if (this.cargando || !this.conv) return;
    var self = this, abajo = this.alFondo();
    return pedir(this.params({ desde: this.ultimo, leer: document.hasFocus() ? 1 : 0 })).then(function (d) {
      var antes = JSON.stringify(self.lectores);
      self.lectores = d.lectores || [];
      if (d.presencia && JSON.stringify(d.presencia) !== JSON.stringify(self.presencia)) {
        self.presencia = d.presencia;
        if (self.op.alPresencia) self.op.alPresencia(d.presencia);
      }
      if (!d.mensajes.length) {
        if (antes !== JSON.stringify(self.lectores)) self.marcarVistos();
        return;
      }
      var ajenos = d.mensajes.filter(function (m) { return !m.propio && !m.sistema; });
      if (ajenos.length) {
        var ult = ajenos[ajenos.length - 1].id;
        if (!document.hasFocus() && !(self.info && self.info.silenciada)) avisarNuevo(ult); else anotarVisto(ult);
      }
      self.vacio.hidden = true;
      self.agregar(d.mensajes, false);
      self.marcarVistos();
      if (abajo) self.lista.scrollTop = self.lista.scrollHeight;
      if (self.op.alLeer) self.op.alLeer();
    });
  };

  Hilo.prototype.anteriores = function () {
    var self = this, alto = this.lista.scrollHeight;
    this.mas.disabled = true;
    pedir(this.params({ antes: this.primero })).then(function (d) {
      var frag = document.createDocumentFragment(), fecha = null, primerViejo = self.cuerpo.firstChild;
      d.mensajes.forEach(function (m) {
        if (m.fecha !== fecha) { frag.appendChild(el('div', 'chat-dia', fechaTxt(m.fecha))); fecha = m.fecha; }
        frag.appendChild(self.burbuja(m));
      });
      // Si la tanda vieja termina el mismo día que empieza lo cargado, sobra un separador.
      if (primerViejo && primerViejo.classList.contains('chat-dia') && primerViejo.textContent === (fecha ? fechaTxt(fecha) : '')) primerViejo.remove();
      self.cuerpo.insertBefore(frag, self.cuerpo.firstChild);
      if (d.mensajes.length) self.primero = d.mensajes[0].id;
      self.mas.hidden = !(d.conv && d.conv.hay_mas);
      self.lista.scrollTop = self.lista.scrollHeight - alto;
    }).catch(function (e) { self.error(e.message); }).then(function () { self.mas.disabled = false; });
  };

  Hilo.prototype.agregar = function (msjs, inicio) {
    var self = this;
    msjs.forEach(function (m) {
      if (m.id <= self.ultimo) return;
      if (m.fecha !== self.ultimaFecha) { self.cuerpo.appendChild(el('div', 'chat-dia', fechaTxt(m.fecha))); self.ultimaFecha = m.fecha; }
      self.cuerpo.appendChild(self.burbuja(m));
      self.ultimo = m.id;
      if (!self.primero) self.primero = m.id;
    });
    if (inicio && msjs.length) this.primero = msjs[0].id;   // para «Ver mensajes anteriores»
  };

  Hilo.prototype.burbuja = function (m) {
    var self = this;
    if (m.sistema) {
      var s = el('div', 'chat-aviso', m.texto);
      s.setAttribute('data-id', m.id);
      return s;
    }
    var b = el('div', 'chat-msj' + (m.propio ? ' propio' : ''));
    b.setAttribute('data-id', m.id);
    var directa = this.info && this.info.tipo === 'DIRECTA';
    if (!m.propio && !directa) b.appendChild(el('div', 'chat-autor', m.autor || '—'));
    if (m.borrado) {
      b.appendChild(el('div', 'chat-texto chat-borrado', 'Mensaje eliminado'));
    } else {
      if (m.adjunto && m.adjunto.audio) {
        b.appendChild(reproductor(m.adjunto));
      } else if (m.adjunto) {
        var a = el('a', 'chat-adjunto' + (m.adjunto.imagen ? ' imagen' : ''));
        a.href = m.adjunto.url;
        a.target = '_blank';
        a.rel = 'noopener';
        if (m.adjunto.imagen) {
          var img = el('img');
          img.src = m.adjunto.url;
          img.alt = m.adjunto.nombre;
          img.loading = 'lazy';
          a.appendChild(img);
        } else {
          a.appendChild(el('span', 'chat-adjunto-ico', '📄'));
          var t = el('span', 'chat-adjunto-txt');
          t.appendChild(el('strong', null, m.adjunto.nombre));
          t.appendChild(el('small', null, m.adjunto.peso));
          a.appendChild(t);
        }
        b.appendChild(a);
      }
      if (m.texto) b.appendChild(el('div', 'chat-texto' + (soloEmojis(m.texto) ? ' solo-emoji' : ''), m.texto));
    }
    var pie = el('div', 'chat-hora', m.hora);
    if (m.propio && !m.borrado) pie.appendChild(el('span', 'chat-visto'));   // las tildes las pone marcarVistos
    if (m.propio && !m.borrado) {
      var x = el('button', 'chat-retirar', 'Eliminar');
      x.type = 'button';
      x.addEventListener('click', function () {
        if (!window.confirm('¿Eliminar este mensaje? Los demás van a ver «Mensaje eliminado».')) return;
        pedir(null, { accion: 'retirar', mensaje: m.id }).then(function () {
          m.borrado = true; m.texto = null; m.adjunto = null;
          b.replaceWith(self.burbuja(m));
          self.marcarVistos();
        }).catch(function (e) { self.error(e.message); });
      });
      pie.appendChild(x);
    }
    b.appendChild(pie);
    return b;
  };

  /**
   * Tildes de los mensajes propios: ✓ gris = enviado, nadie lo leyó todavía;
   * ✓✓ azul = lo leyó (en grupos, al menos uno: al pasar el mouse dice
   * quiénes). En grupos, además, debajo del último mensaje propio: «Visto por …».
   */
  Hilo.prototype.marcarVistos = function () {
    var lect = this.lectores, directa = this.info && this.info.tipo === 'DIRECTA';
    var propios = this.cuerpo.querySelectorAll('.chat-msj.propio');
    var viejo = this.cuerpo.querySelector('.chat-visto-por');
    if (viejo) viejo.remove();
    propios.forEach(function (b) {
      var v = b.querySelector('.chat-visto');
      if (!v) return;
      var id = +b.getAttribute('data-id');
      var leyeron = lect.filter(function (l) { return l.hasta >= id; });
      var todos = lect.length > 0 && leyeron.length === lect.length;
      v.className = 'chat-visto' + (leyeron.length ? ' leido' : '');
      v.textContent = leyeron.length ? '✓✓' : '✓';
      v.title = !leyeron.length ? 'Enviado: todavía no lo leyó nadie'
              : directa ? 'Leído'
              : todos ? 'Leído por todos' : 'Leído por ' + leyeron.map(function (l) { return l.nombre; }).join(', ');
    });
    if (directa || !propios.length) return;
    var ult = propios[propios.length - 1], uid = +ult.getAttribute('data-id');
    var vieron = lect.filter(function (l) { return l.hasta >= uid; });
    if (!vieron.length) return;
    var nombres = vieron.map(function (l) { return l.nombre.split(' ')[0]; });
    var txt = vieron.length === lect.length && lect.length > 1 ? 'Visto por todos'
            : 'Visto por ' + (nombres.length > 3 ? nombres.slice(0, 3).join(', ') + ' y ' + (nombres.length - 3) + ' más'
                                                 : nombres.slice(0, -1).join(', ') + (nombres.length > 1 ? ' y ' : '') + nombres[nombres.length - 1]);
    var vp = el('div', 'chat-visto-por', txt);
    vp.title = vieron.map(function (l) { return l.nombre; }).join(', ');
    ult.after(vp);
  };

  // ── Emojis ───────────────────────────────────────────────────────────
  var EMOJIS = [
    ['😊', 'Caras', '😀 😃 😄 😁 😆 😅 😂 🤣 😊 🙂 😉 😇 🥰 😍 😘 😋 😜 🤪 😎 🤓 🥳 🤩 🤗 🤭 🫡 🤔 🤨 😐 😑 🙄 😏 😬 😮 😲 😳 🥺 😢 😭 😓 😩 😫 😤 😡 🤯 😱 😴 🤒 🤧 😷 🙃'],
    ['👍', 'Gestos', '👍 👎 👌 ✌️ 🤞 🤝 🙏 👏 🙌 💪 👋 ☝️ 👉 👈 👆 👇 ✋ 🤙 🫶 ✍️ 👀 🤷 🤦 🙋 🙅 🙆'],
    ['💼', 'Trabajo', '💰 💵 💲 💳 🏦 📈 📉 📊 📄 📋 📎 📁 🗂️ 📅 📆 ⏰ ⏳ ✉️ 📧 📞 📱 💻 🖨️ ✏️ 📝 🔒 🔑 🏢 🏠 🚗 ☕ 🍕 🎂 🎉 🎁 🏆'],
    ['✅', 'Símbolos', '✅ ❌ ⚠️ ❗ ❓ ‼️ ✔️ ✖️ ➕ ➖ 🔴 🟠 🟡 🟢 🔵 ⭐ 🔥 💯 ❤️ 💙 💚 🆗 🆕 ➡️ ⬅️ ⬆️ ⬇️ 🔄 ⏸️']
  ];
  var EMOJI_FRECUENTES = '👍 🙏 😊 😂 ✅ 👌 🙌 👏 ❤️ 🎉 💪 👀'.split(' ');
  var CLAVE_RECIENTES = 'gadm_chat_emojis';

  function recientes() {
    try { var r = JSON.parse(localStorage.getItem(CLAVE_RECIENTES) || '[]'); if (Array.isArray(r) && r.length) return r; } catch (e) {}
    return EMOJI_FRECUENTES;
  }
  function guardarReciente(em) {
    var r = recientes().filter(function (x) { return x !== em; });
    r.unshift(em);
    try { localStorage.setItem(CLAVE_RECIENTES, JSON.stringify(r.slice(0, 24))); } catch (e) {}
  }

  /** Mensaje de 1 a 3 emojis y nada más: se muestra grande. */
  var RE_SOLO_EMOJI = null;
  try { RE_SOLO_EMOJI = new RegExp('^(?:\\p{Extended_Pictographic}|[\\u{1F3FB}-\\u{1F3FF}\\u{1F1E6}-\\u{1F1FF}]|\\u200d|\\ufe0f|\\s)+$', 'u'); } catch (e) {}
  function soloEmojis(t) {
    if (!RE_SOLO_EMOJI || !RE_SOLO_EMOJI.test(t)) return false;
    var n = 0;
    if (window.Intl && Intl.Segmenter) {
      var it = new Intl.Segmenter('es', { granularity: 'grapheme' }).segment(t.replace(/\s+/g, ''));
      for (var x = it[Symbol.iterator](), r = x.next(); !r.done; r = x.next()) n++;
    } else {
      n = (t.match(/\p{Extended_Pictographic}/gu) || []).length;
    }
    return n > 0 && n <= 3;
  }

  /** Abre o cierra el selector. Elegir uno lo inserta donde está el cursor (y queda abierto para poner otro). */
  Hilo.prototype.emojis = function (cerrar) {
    var self = this;
    if (!this.selector) {
      var sel = el('div', 'chat-emojis');
      sel.hidden = true;
      sel.setAttribute('role', 'dialog');
      sel.setAttribute('aria-label', 'Emojis');
      var tabs = el('div', 'chat-emojis-tabs');
      var grilla = el('div', 'chat-emojis-grilla');
      var grupos = [['🕘', 'Recientes', null]].concat(EMOJIS);
      var mostrar = function (i) {
        tabs.querySelectorAll('button').forEach(function (b, j) { b.classList.toggle('activa', i === j); });
        grilla.innerHTML = '';
        var lista = grupos[i][2] ? grupos[i][2].split(' ') : recientes();
        lista.forEach(function (em) {
          var b = el('button', null, em);
          b.type = 'button';
          b.addEventListener('click', function () { self.insertarEmoji(em); });
          grilla.appendChild(b);
        });
      };
      grupos.forEach(function (g, i) {
        var t = el('button', null, g[0]);
        t.type = 'button';
        t.title = g[1];
        t.addEventListener('click', function () { mostrar(i); });
        tabs.appendChild(t);
      });
      sel.appendChild(tabs);
      sel.appendChild(grilla);
      this.selector = sel;
      this.mostrarGrupo = mostrar;
      this.form.appendChild(sel);
      // Click afuera o Escape: se cierra (Escape no llega a cerrar la conversación).
      this.cerrarAfuera = function (e) {
        if (!sel.hidden && !sel.contains(e.target) && e.target !== self.btnEmoji) self.emojis(true);
      };
      document.addEventListener('mousedown', this.cerrarAfuera);
      this.raiz.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !sel.hidden) { e.preventDefault(); e.stopPropagation(); self.emojis(true); self.txt.focus(); }
      });
    }
    var abrir = cerrar === true ? false : this.selector.hidden;
    if (abrir) this.mostrarGrupo(0);
    this.selector.hidden = !abrir;
    this.btnEmoji.setAttribute('aria-expanded', abrir ? 'true' : 'false');
    this.btnEmoji.classList.toggle('activo', abrir);
  };

  Hilo.prototype.insertarEmoji = function (em) {
    var t = this.txt, ini = t.selectionStart, fin = t.selectionEnd;
    if (ini == null) { ini = fin = t.value.length; }
    t.value = t.value.slice(0, ini) + em + t.value.slice(fin);
    t.selectionStart = t.selectionEnd = ini + em.length;
    t.focus();
    this.alto();
    guardarReciente(em);
  };

  /** voz: { blob, nombre, seg } para un mensaje de voz (no toca lo escrito ni el archivo elegido). */
  Hilo.prototype.enviar = function (voz) {
    var self = this, texto = voz ? '' : this.txt.value.trim(), f = voz ? null : this.file.files[0];
    if (!voz && !texto && !f) return;
    if (this.enviando) return;
    var fd = new FormData();
    fd.append('accion', 'enviar');
    if (this.conv) fd.append('conv', this.conv);
    else if (this.op.para) fd.append('para', this.op.para);
    fd.append('texto', texto);
    if (f) fd.append('archivo', f);
    if (voz) {
      fd.append('archivo', voz.blob, voz.nombre);
      fd.append('voz', '1');
      fd.append('duracion', voz.seg);
    }
    this.enviando = true;
    this.form.classList.add('enviando');
    this.error('');
    pedir(null, fd).then(function (d) {
      if (!voz) {
        if (self.selector) self.emojis(true);
        self.txt.value = '';
        self.file.value = '';
        self.mostrarArchivo();
        self.alto();
      }
      var nueva = !self.conv;
      self.conv = d.conv;
      if (nueva) return self.cargar();
      return self.nuevos();
    }).then(function () {
      self.lista.scrollTop = self.lista.scrollHeight;
      if (self.op.alEnviar) self.op.alEnviar();
    }).catch(function (e) { self.error(e.message); })
      .then(function () { self.enviando = false; self.form.classList.remove('enviando'); self.txt.focus(); });
  };

  Hilo.prototype.cerrar = function () {
    this.pararGrabacion(false);
    this.reloj.parar();
    if (this.cerrarAfuera) document.removeEventListener('mousedown', this.cerrarAfuera);
  };

  // ── Mensajes de voz ──────────────────────────────────────────────────
  var VOZ_MAX = 300;   // segundos (VOZ_MAX_SEG en mensajes.py)

  /** El micrófono sólo se puede usar con https (o en localhost) y con MediaRecorder. */
  function puedeGrabar() {
    return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function minSeg(s) {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  Hilo.prototype.grabar = function () {
    var self = this;
    if (this.rec || this.enviando) return;
    this.error('');
    if (this.selector) this.emojis(true);
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }).then(function (stream) {
      var tipos = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
      var tipo = tipos.filter(function (t) { return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t); })[0] || '';
      var rec;
      try {
        rec = new MediaRecorder(stream, tipo ? { mimeType: tipo, audioBitsPerSecond: 32000 } : undefined);
      } catch (e) {
        rec = new MediaRecorder(stream);
      }
      var partes = [];
      rec.ondataavailable = function (e) { if (e.data && e.data.size) partes.push(e.data); };
      rec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        clearInterval(self.recReloj);
        var seg = Math.max(1, Math.round((Date.now() - self.recIni) / 1000));
        var mandar = self.recEnviar;
        self.rec = null;
        self.form.classList.remove('grabando');
        self.barraGrab.hidden = true;
        if (!mandar || !partes.length) return;
        var mime = (rec.mimeType || tipo || 'audio/webm').split(';')[0];
        var ext = mime.indexOf('mp4') !== -1 ? 'm4a' : (mime.indexOf('ogg') !== -1 ? 'ogg' : 'webm');
        self.enviar({ blob: new Blob(partes, { type: mime }), nombre: 'Mensaje de voz.' + ext, seg: Math.min(seg, VOZ_MAX) });
      };
      self.rec = rec;
      self.recEnviar = false;
      self.recIni = Date.now();
      rec.start(1000);
      self.form.classList.add('grabando');
      self.barraGrab.hidden = false;
      var tiempo = self.barraGrab.querySelector('.chat-grab-tiempo');
      tiempo.textContent = '0:00';
      self.recReloj = setInterval(function () {
        var s = (Date.now() - self.recIni) / 1000;
        tiempo.textContent = minSeg(s);
        if (s >= VOZ_MAX) self.pararGrabacion(true);       // a los 5 minutos se manda solo
      }, 250);
      self.barraGrab.querySelector('.chat-grab-enviar').focus();
    }).catch(function (e) {
      self.error(e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')
        ? 'El navegador no dio permiso para usar el micrófono. Habilitalo en el candado de la barra de direcciones y probá de nuevo.'
        : (e && e.name === 'NotFoundError' ? 'No se encontró un micrófono en este equipo.' : 'No se pudo usar el micrófono' + (e && e.message ? ': ' + e.message : '.')));
    });
  };

  /** Termina la grabación: enviar = true la manda, false la descarta. */
  Hilo.prototype.pararGrabacion = function (enviar) {
    if (!this.rec) return;
    this.recEnviar = !!enviar;
    if (this.rec.state !== 'inactive') this.rec.stop();
  };

  /** El audio de un mensaje: reproductor del navegador y, en los de voz, la duración. Suena uno por vez. */
  function reproductor(adj) {
    var c = el('div', 'chat-audio');
    var au = el('audio');
    au.controls = true;
    au.preload = 'metadata';
    au.src = adj.url;
    au.addEventListener('play', function () {
      document.querySelectorAll('.chat-audio audio').forEach(function (x) { if (x !== au) x.pause(); });
    });
    c.appendChild(au);
    var pie = el('div', 'chat-audio-pie');
    pie.appendChild(el('span', null, adj.duracion ? '🎤 Mensaje de voz · ' + minSeg(adj.duracion) : '🎵 ' + adj.nombre + ' · ' + adj.peso));
    var bajar = el('a', null, 'Descargar');
    bajar.href = adj.url + (adj.url.indexOf('?') === -1 ? '?' : '&') + 'bajar=1';
    pie.appendChild(bajar);
    c.appendChild(pie);
    return c;
  }

  // ── La pantalla Mensajes ─────────────────────────────────────────────
  var app = document.querySelector('[data-chat-app]');
  if (!app) return;

  var ulConvs = app.querySelector('[data-convs]');
  var panel = app.querySelector('[data-panel]');
  var cab = app.querySelector('[data-cabecera]');
  var zona = app.querySelector('[data-zona-hilo]');
  var buscar = app.querySelector('[data-buscar]');
  var base = location.pathname;
  var hilo = null, convs = [], usuarios = null, actual = null;

  function cargarUsuarios() {
    if (usuarios) return Promise.resolve(usuarios);
    return pedir({ accion: 'usuarios' }).then(function (d) { usuarios = d.usuarios; return usuarios; });
  }

  function norm(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }

  function dibujarLista() {
    var f = norm(buscar.value.trim());
    ulConvs.innerHTML = '';
    var vis = convs.filter(function (c) { return !f || norm(c.titulo + ' ' + c.ultimo).indexOf(f) !== -1; });
    if (!vis.length) {
      ulConvs.appendChild(el('li', 'chat-lista-vacia', convs.length ? 'Ninguna conversación coincide.'
        : 'Todavía no tenés conversaciones. Empezá una con «Nuevo».'));
      return;
    }
    vis.forEach(function (c) {
      var li = el('li');
      var a = el('a', 'chat-conv' + (c.id === actual ? ' activa' : '') + (c.no_leidos ? ' sin-leer' : ''));
      a.href = '?c=' + c.id;
      a.setAttribute('data-id', c.id);
      var ico = el('span', 'chat-conv-ico tipo-' + c.tipo.toLowerCase() + (c.en_linea ? ' en-linea' : ''), c.tipo === 'GRUPO' ? '👥' : (c.titulo || '?').trim().charAt(0).toUpperCase());
      if (c.estado) ico.title = c.estado;
      a.appendChild(ico);
      var t = el('span', 'chat-conv-txt');
      var l1 = el('span', 'chat-conv-l1');
      l1.appendChild(el('strong', null, c.titulo + (c.inactivo ? ' (de baja)' : '')));
      l1.appendChild(el('small', null, c.cuando));
      t.appendChild(l1);
      var l2 = el('span', 'chat-conv-l2');
      l2.appendChild(el('span', null, c.ultimo || ' '));
      if (c.silenciada) l2.appendChild(el('span', 'chat-silencio', '🔕'));
      if (c.no_leidos) l2.appendChild(el('span', 'chat-badge', c.no_leidos > 99 ? '99+' : String(c.no_leidos)));
      t.appendChild(l2);
      a.appendChild(t);
      a.addEventListener('click', function (e) { e.preventDefault(); abrir(c.id); });
      li.appendChild(a);
      ulConvs.appendChild(li);
    });
  }

  function cargarLista() {
    return pedir({ accion: 'lista' }).then(function (d) {
      convs = d.conversaciones;
      dibujarLista();
      ponerContador(d.no_leidos);
      avisarNuevo(d.ultimo);
    });
  }

  /** El punto verde de «en línea». */
  function punto() {
    var p = el('span', 'chat-punto');
    p.title = 'En línea';
    p.setAttribute('aria-label', 'En línea');
    return p;
  }

  function boton(texto, clase, fn) {
    var b = el('button', 'btn btn-sm ' + (clase || 'btn-ghost'), texto);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  /** Botón de la cabecera: ícono y texto (en el celular, sólo el ícono). */
  function botonIco(ico, texto, fn, titulo) {
    var b = el('button', 'btn btn-sm btn-ghost chat-cab-btn');
    b.type = 'button';
    b.addEventListener('click', fn);
    b.title = titulo || texto;
    b.setAttribute('aria-label', titulo || texto);
    b.appendChild(el('span', 'chat-cab-ico', ico));
    b.appendChild(el('span', 'chat-cab-btn-txt', texto));
    return b;
  }

  function dibujarCabecera(info) {
    cab.innerHTML = '';
    estadoCab = null;
    var volver = boton('←', 'btn-ghost chat-volver', function () { cerrarPanel(); });
    volver.title = 'Volver a la lista';
    cab.appendChild(volver);
    var t = el('div', 'chat-cab-txt');
    t.appendChild(el('strong', null, info ? info.titulo : ''));
    if (info && info.tipo === 'GRUPO') t.appendChild(el('small', null, info.integrantes.map(function (i) { return i.nombre.split(' ')[0]; }).join(', ')));
    if (info) {
      estadoCab = el('small', 'chat-estado');
      t.appendChild(estadoCab);
      ponerEstado(hilo && hilo.presencia);
    }
    cab.appendChild(t);
    var acc = el('div', 'chat-cab-acc');
    if (info && info.tipo === 'GRUPO') acc.appendChild(botonIco('👥', 'Integrantes', function () { dlgIntegrantes(info); }, 'Integrantes del grupo'));
    if (info && info.participa) {
      acc.appendChild(botonIco(info.silenciada ? '🔔' : '🔕', info.silenciada ? 'Activar avisos' : 'Silenciar', function () {
        pedir(null, { accion: 'silenciar', conv: info.id, si: info.silenciada ? 0 : 1 }).then(function () {
          info.silenciada = !info.silenciada;
          if (hilo) hilo.info = info;
          dibujarCabecera(info);
          cargarLista();
        }).catch(function (e) { alert(e.message); });
      }, info.silenciada ? 'Volver a recibir avisos de esta conversación' : 'Que esta conversación no sume al globito ni suene'));
    }
    if (info && info.tipo === 'GRUPO') acc.appendChild(boton('Salir', 'btn-ghost peligro', function () {
      if (!window.confirm('¿Salir del grupo «' + info.titulo + '»? Para volver te tiene que agregar quien lo administra.')) return;
      pedir(null, { accion: 'salir', conv: info.id }).then(function () { cerrarPanel(); cargarLista(); }).catch(function (e) { alert(e.message); });
    }));
    var x = el('button', 'btn-accion chat-cerrar chat-cerrar-conv');
    x.type = 'button';
    x.title = 'Cerrar la conversación (Esc)';
    x.setAttribute('aria-label', 'Cerrar la conversación');
    x.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    x.addEventListener('click', function () { cerrarPanel(); });
    acc.appendChild(x);
    cab.appendChild(acc);
  }

  /** «En línea» / «Últ. vez …» bajo el nombre (en un grupo, cuántos están en línea). */
  var estadoCab = null;
  function ponerEstado(p) {
    if (!estadoCab) return;
    estadoCab.textContent = p && p.estado ? p.estado : '';
    estadoCab.className = 'chat-estado' + (p && p.en_linea ? ' en-linea' : '');
    estadoCab.hidden = !(p && p.estado);
  }

  /** El panel vacío, con el nombre, mientras se abre una conversación nueva. */
  function prepararPanel(titulo) {
    if (hilo) hilo.cerrar();
    hilo = null;
    zona.innerHTML = '';
    app.classList.add('con-conversacion');
    panel.hidden = false;
    app.querySelector('[data-sin-conv]').hidden = true;
    dibujarCabecera({ titulo: titulo, tipo: 'DIRECTA', integrantes: [] });
  }

  function abrir(id) {
    actual = id;
    if (hilo) hilo.cerrar();
    app.classList.add('con-conversacion');
    panel.hidden = false;
    app.querySelector('[data-sin-conv]').hidden = true;
    dibujarCabecera(null);
    hilo = new Hilo(zona, {
      conv: id, cada: 3000,
      alCambiar: function (info) {
        if (info) {
          actual = info.id;
          dibujarLista();
          dibujarCabecera(info);
          history.replaceState(null, '', base + '?c=' + info.id + volverQS());
        }
      },
      alLeer: function () { cargarLista(); },
      alEnviar: function () { cargarLista(); },
      alPresencia: function (p) { ponerEstado(p); }
    });
    dibujarLista();
    hilo.txt.focus();
  }

  function cerrarPanel() {
    if (hilo) hilo.cerrar();
    hilo = null;
    actual = null;
    app.classList.remove('con-conversacion');
    panel.hidden = true;
    app.querySelector('[data-sin-conv]').hidden = false;
    history.replaceState(null, '', base + (volverQS() ? '?' + volverQS().slice(1) : ''));
    dibujarLista();
  }

  // El ?volver= que puso el botón de la barra: se mantiene en la dirección.
  var volverParam = new URLSearchParams(location.search).get('volver');
  function volverQS() { return volverParam ? '&volver=' + encodeURIComponent(volverParam) : ''; }

  // ── Diálogos ─────────────────────────────────────────────────────────
  function dialogo(titulo, cuerpo, textoOk, alOk) {
    var d = el('dialog', 'chat-dialogo');
    var f = el('form');
    f.method = 'dialog';
    var h = el('div', 'card-head');
    h.appendChild(el('span', 'card-head-titulo', titulo));
    f.appendChild(h);
    var c = el('div', 'bloque');
    c.appendChild(cuerpo);
    f.appendChild(c);
    var err = el('div', 'chat-error');
    err.hidden = true;
    c.appendChild(err);
    var pie = el('div', 'form-acciones');
    pie.appendChild(boton(textoOk ? 'Cancelar' : 'Cerrar', 'btn-secondary', function () { d.close(); }));
    if (textoOk) {
      var ok = el('button', 'btn btn-primary', textoOk);
      ok.type = 'submit';
      pie.appendChild(ok);
    }
    f.appendChild(pie);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      err.hidden = true;
      Promise.resolve(alOk()).then(function (cerrar) { if (cerrar !== false) d.close(); })
        .catch(function (x) { err.textContent = x.message; err.hidden = false; });
    });
    d.appendChild(f);
    d.addEventListener('close', function () { d.remove(); });
    document.body.appendChild(d);
    d.showModal();
    return d;
  }

  /** Lista de usuarios con buscador; multiple = casillas, si no, un click elige. */
  function selectorUsuarios(lista, multiple, alElegir, excluir) {
    var caja = el('div', 'chat-selector');
    var q = el('input');
    q.type = 'search';
    q.placeholder = 'Buscar por nombre o rol…';
    q.autocomplete = 'off';
    caja.appendChild(q);
    var ul = el('ul', 'chat-selector-lista');
    caja.appendChild(ul);
    var elegidos = {};
    function dibujar() {
      var f = norm(q.value.trim());
      ul.innerHTML = '';
      lista.filter(function (u) { return (!excluir || excluir.indexOf(u.id) === -1) && (!f || norm(u.nombre + ' ' + u.roles).indexOf(f) !== -1); })
        .forEach(function (u) {
          var li = el('li');
          var lab = el(multiple ? 'label' : 'button', 'chat-selector-op');
          if (multiple) {
            var cb = el('input');
            cb.type = 'checkbox';
            cb.checked = !!elegidos[u.id];
            cb.addEventListener('change', function () { if (cb.checked) elegidos[u.id] = true; else delete elegidos[u.id]; });
            lab.appendChild(cb);
          } else {
            lab.type = 'button';
            lab.addEventListener('click', function () { alElegir(u); });
          }
          var t = el('span');
          var nom = el('strong', null, u.nombre);
          if (u.en_linea) nom.appendChild(punto());
          t.appendChild(nom);
          var sub = [u.roles, u.estado].filter(Boolean).join(' · ');
          if (sub) t.appendChild(el('small', null, sub));
          lab.appendChild(t);
          li.appendChild(lab);
          ul.appendChild(li);
        });
      if (!ul.children.length) ul.appendChild(el('li', 'chat-lista-vacia', lista.length ? 'Nadie coincide.' : 'No hay otros usuarios con Mensajes.'));
    }
    q.addEventListener('input', dibujar);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
    dibujar();
    setTimeout(function () { q.focus(); }, 30);
    caja.elegidos = function () { return Object.keys(elegidos).map(Number); };
    return caja;
  }

  function dlgNuevo() {
    cargarUsuarios().then(function (us) {
      var d = dialogo('Nuevo mensaje', selectorUsuarios(us, false, function (u) {
        d.close();
        // La conversación anterior se cierra ya: si no, lo que se escribiera
        // mientras llega la nueva iba a parar a la anterior.
        prepararPanel(u.nombre);
        pedir(null, { accion: 'abrir', para: u.id }).then(function (r) { abrir(r.conv); }).catch(function (e) { alert(e.message); });
      }), null, function () {});
    }).catch(function (e) { alert(e.message); });
  }

  function dlgGrupo() {
    cargarUsuarios().then(function (us) {
      var cuerpo = el('div');
      var campo = el('div', 'campo');
      campo.appendChild(el('label', null, 'Nombre del grupo'));
      var nom = el('input');
      nom.maxLength = 80;
      nom.required = true;
      nom.placeholder = 'Por ejemplo: Tesorería y Pagos';
      campo.appendChild(nom);
      cuerpo.appendChild(campo);
      cuerpo.appendChild(el('div', 'dato-lbl chat-sep', 'Integrantes'));
      var sel = selectorUsuarios(us, true);
      cuerpo.appendChild(sel);
      dialogo('Nuevo grupo', cuerpo, 'Crear el grupo', function () {
        return pedir(null, { accion: 'grupo', nombre: nom.value, miembros: sel.elegidos() }).then(function (r) { cargarLista(); abrir(r.conv); });
      });
      setTimeout(function () { nom.focus(); }, 40);
    }).catch(function (e) { alert(e.message); });
  }

  function dlgIntegrantes(info) {
    var cuerpo = el('div');
    var ul = el('ul', 'chat-integrantes');
    var quitar = {};
    info.integrantes.forEach(function (i) {
      var li = el('li');
      var n = el('span', null, i.nombre + (i.admin ? ' · administra' : '') + (i.activo ? '' : ' (de baja)'));
      if (i.en_linea) n.appendChild(punto());
      if (i.estado && !i.en_linea) n.appendChild(el('small', 'chat-estado', ' · ' + i.estado));
      li.appendChild(n);
      if (info.admin && !i.admin) {
        var b = boton('Sacar', 'btn-ghost', function () {
          quitar[i.id] = !quitar[i.id];
          li.classList.toggle('chat-quitado', !!quitar[i.id]);
          b.textContent = quitar[i.id] ? 'Dejar' : 'Sacar';
        });
        li.appendChild(b);
      }
      ul.appendChild(li);
    });
    if (!info.admin) {
      cuerpo.appendChild(ul);
      cuerpo.appendChild(el('p', 'campo-ayuda', 'Sólo quien administra el grupo puede agregar o sacar gente.'));
      dialogo('Integrantes de «' + info.titulo + '»', cuerpo, null, function () {});
      return;
    }
    cargarUsuarios().then(function (us) {
      var campo = el('div', 'campo');
      campo.appendChild(el('label', null, 'Nombre del grupo'));
      var nom = el('input');
      nom.maxLength = 80;
      nom.value = info.titulo;
      campo.appendChild(nom);
      cuerpo.appendChild(campo);
      cuerpo.appendChild(el('div', 'dato-lbl chat-sep', 'Integrantes'));
      cuerpo.appendChild(ul);
      cuerpo.appendChild(el('div', 'dato-lbl chat-sep', 'Agregar'));
      var sel = selectorUsuarios(us, true, null, info.integrantes.map(function (i) { return i.id; }));
      cuerpo.appendChild(sel);
      dialogo('Grupo «' + info.titulo + '»', cuerpo, 'Guardar', function () {
        return pedir(null, { accion: 'editar', conv: info.id, nombre: nom.value, agregar: sel.elegidos(),
                             quitar: Object.keys(quitar).filter(function (k) { return quitar[k]; }) })
          .then(function () { cargarLista(); abrir(info.id); });
      });
    }).catch(function (e) { alert(e.message); });
  }

  // Escape: cierra la conversación abierta; sin conversación, sale de Mensajes.
  // (Con un diálogo abierto, Escape cierra sólo el diálogo.)
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('dialog[open]')) return;
    if (hilo) { if (!hilo.txt.value.trim()) cerrarPanel(); return; }   // con algo escrito no se pierde
    var salir = app.querySelector('[data-chat-salir]');
    if (salir && document.activeElement !== buscar) location.href = salir.getAttribute('href');
  });

  var btnSonido = app.querySelector('[data-chat-sonido]');
  function dibujarSonido() {
    var si = sonidoActivo();
    btnSonido.textContent = si ? '🔔' : '🔕';
    btnSonido.title = si ? 'Sonido de los mensajes nuevos: activado (click para apagarlo)' : 'Sonido de los mensajes nuevos: apagado (click para prenderlo)';
    btnSonido.setAttribute('aria-pressed', si ? 'true' : 'false');
  }
  if (btnSonido) {
    dibujarSonido();
    btnSonido.addEventListener('click', function () {
      guardarLS(CLAVE_SONIDO, sonidoActivo() ? '0' : '1');
      dibujarSonido();
      if (sonidoActivo()) ding();                     // para escuchar cómo suena
    });
  }

  app.querySelector('[data-nuevo]').addEventListener('click', dlgNuevo);
  app.querySelector('[data-nuevo-grupo]').addEventListener('click', dlgGrupo);
  buscar.addEventListener('input', dibujarLista);

  // La lista se actualiza sola (cada 10 s), y el título de la pestaña con ella.
  cargarLista().then(function () {
    var p = new URLSearchParams(location.search);
    var c = +p.get('c'), para = +p.get('para');
    if (c) abrir(c);
    else if (para) pedir(null, { accion: 'abrir', para: para }).then(function (r) { abrir(r.conv); }).catch(function (e) { alert(e.message); });
  }).catch(function (e) { ulConvs.innerHTML = ''; ulConvs.appendChild(el('li', 'chat-lista-vacia', e.message)); });
  cadaTanto(function () { return cargarLista(); }, 10000);
})();
