
'use strict';

/* ---------- фон: котики в невесомости и столбчатые диаграммы ---------- */
(function background(){
  var cv = document.getElementById('bg');
  var cx = cv.getContext('2d');
  var W = 0, H = 0, DPR = 1;
  var cats = [], charts = [];

  function rnd(a, b){ return a + Math.random() * (b - a); }

  function roundRect(x, y, w, h, r){
    cx.beginPath();
    cx.moveTo(x + r, y);
    cx.arcTo(x + w, y, x + w, y + h, r);
    cx.arcTo(x + w, y + h, x, y + h, r);
    cx.arcTo(x, y + h, x, y, r);
    cx.arcTo(x, y, x + w, y, r);
    cx.closePath();
  }

  function build(){
    cats = [];
    var nc = Math.max(6, Math.min(20, Math.round(W * H / 155000)));
    var hues = [28, 300, 190, 340, 52, 265];
    for (var i = 0; i < nc; i++){
      cats.push({
        x: rnd(0, W), y: rnd(0, H),
        vx: rnd(-14, 14), vy: rnd(-10, 10),
        s: rnd(0.55, 1.15),
        rot: rnd(-0.4, 0.4), rv: rnd(-0.22, 0.22),
        hue: hues[Math.floor(rnd(0, hues.length - 0.001))],
        ph: rnd(0, 6.283), amp: rnd(6, 17),
        blink: rnd(0, 6.283), alpha: rnd(0.34, 0.68)
      });
    }

    charts = [];
    var nch = Math.max(3, Math.min(12, Math.round(W * H / 400000)));
    for (var k = 0; k < nch; k++){
      var bars = [];
      var nb = Math.floor(rnd(3, 6.99));
      for (var j = 0; j < nb; j++){
        bars.push({ h: rnd(0.25, 1), red: Math.random() < 0.5, ph: rnd(0, 6.283) });
      }
      charts.push({
        x: rnd(0, W), y: rnd(0, H),
        vx: rnd(-9, 9), vy: rnd(-7, 7),
        s: rnd(0.72, 1.28),
        rot: rnd(-0.2, 0.2), rv: rnd(-0.1, 0.1),
        bars: bars, ph: rnd(0, 6.283), amp: rnd(8, 18),
        alpha: rnd(0.17, 0.38)
      });
    }
  }

  function drawCat(c, t){
    var bob = Math.sin(t * 0.8 + c.ph) * c.amp;
    cx.save();
    cx.translate(c.x, c.y + bob);
    cx.rotate(c.rot + Math.sin(t * 0.5 + c.ph) * 0.11);
    cx.scale(c.s, c.s);
    cx.globalAlpha = c.alpha;

    var base = 'hsl(' + c.hue + ', 72%, 66%)';
    var dark = 'hsl(' + c.hue + ', 62%, 47%)';
    var light = 'hsl(' + c.hue + ', 86%, 83%)';

    cx.strokeStyle = dark;
    cx.lineWidth = 6;
    cx.lineCap = 'round';
    cx.beginPath();
    cx.moveTo(18, 14);
    cx.bezierCurveTo(40, 10, 46, -14, 30, -26);
    cx.stroke();

    cx.fillStyle = base;
    cx.beginPath();
    cx.ellipse(0, 16, 26, 20, 0, 0, 6.283);
    cx.fill();

    cx.beginPath();
    cx.arc(-22, -6, 20, 0, 6.283);
    cx.fill();

    cx.beginPath();
    cx.moveTo(-36, -20); cx.lineTo(-40, -41); cx.lineTo(-23, -30);
    cx.closePath(); cx.fill();
    cx.beginPath();
    cx.moveTo(-10, -22); cx.lineTo(-6, -42); cx.lineTo(-22, -31);
    cx.closePath(); cx.fill();

    cx.fillStyle = light;
    cx.beginPath();
    cx.moveTo(-33, -22); cx.lineTo(-35, -35); cx.lineTo(-26, -28);
    cx.closePath(); cx.fill();
    cx.beginPath();
    cx.moveTo(-13, -24); cx.lineTo(-10, -37); cx.lineTo(-20, -29);
    cx.closePath(); cx.fill();

    var blink = Math.sin(t * 1.3 + c.blink) > 0.97 ? 0.15 : 1;
    cx.fillStyle = '#12172a';
    cx.beginPath(); cx.ellipse(-29, -8, 3.2, 3.9 * blink, 0, 0, 6.283); cx.fill();
    cx.beginPath(); cx.ellipse(-15, -8, 3.2, 3.9 * blink, 0, 0, 6.283); cx.fill();

    if (blink > 0.5){
      cx.fillStyle = 'rgba(255,255,255,.9)';
      cx.beginPath(); cx.arc(-30, -9.4, 1.1, 0, 6.283); cx.fill();
      cx.beginPath(); cx.arc(-16, -9.4, 1.1, 0, 6.283); cx.fill();
    }

    cx.fillStyle = 'rgba(255,140,165,.95)';
    cx.beginPath();
    cx.moveTo(-22, -1); cx.lineTo(-24.4, 1.6); cx.lineTo(-19.6, 1.6);
    cx.closePath(); cx.fill();

    cx.strokeStyle = 'rgba(255,255,255,.5)';
    cx.lineWidth = 1.15;
    cx.beginPath();
    cx.moveTo(-32, 2); cx.lineTo(-46, 0.2);
    cx.moveTo(-32, 4.6); cx.lineTo(-46, 6.6);
    cx.moveTo(-12, 2); cx.lineTo(2, 0.2);
    cx.moveTo(-12, 4.6); cx.lineTo(2, 6.6);
    cx.stroke();

    cx.restore();
  }

  function drawChart(c, t){
    var w = 120, h = 86;
    var bob = Math.sin(t * 0.7 + c.ph) * c.amp;

    cx.save();
    cx.translate(c.x, c.y + bob);
    cx.rotate(c.rot + Math.sin(t * 0.6 + c.ph) * 0.08);
    cx.scale(c.s, c.s);
    cx.globalAlpha = c.alpha;

    cx.fillStyle = 'rgba(16,22,40,.8)';
    cx.strokeStyle = 'rgba(140,170,255,.26)';
    cx.lineWidth = 1.2;
    roundRect(-w / 2, -h / 2, w, h, 12);
    cx.fill();
    cx.stroke();

    cx.strokeStyle = 'rgba(255,255,255,.08)';
    cx.lineWidth = 1;
    for (var g = 1; g <= 3; g++){
      var gy = -h / 2 + 12 + g * ((h - 26) / 4);
      cx.beginPath();
      cx.moveTo(-w / 2 + 10, gy);
      cx.lineTo(w / 2 - 10, gy);
      cx.stroke();
    }

    var n = c.bars.length;
    var pad = 13, gap = 6;
    var bw = (w - pad * 2 - gap * (n - 1)) / n;
    var baseY = h / 2 - 12;
    var maxH = h - 30;

    for (var i = 0; i < n; i++){
      var b = c.bars[i];
      var grow = 0.86 + Math.sin(t * 1.5 + b.ph) * 0.14;
      var bh = Math.max(4, maxH * b.h * grow);
      var x = -w / 2 + pad + i * (bw + gap);
      var y = baseY - bh;
      cx.fillStyle = b.red ? 'rgba(255,84,112,.88)' : 'rgba(255,200,87,.88)';
      roundRect(x, y, bw, bh, 3);
      cx.fill();
    }

    cx.strokeStyle = 'rgba(255,255,255,.24)';
    cx.lineWidth = 1.2;
    cx.beginPath();
    cx.moveTo(-w / 2 + 9, baseY + 0.5);
    cx.lineTo(w / 2 - 9, baseY + 0.5);
    cx.stroke();

    cx.restore();
  }

  function wrap(o, mx, my){
    if (o.x < -mx) o.x = W + mx;
    if (o.x > W + mx) o.x = -mx;
    if (o.y < -my) o.y = H + my;
    if (o.y > H + my) o.y = -my;
  }

  var last = performance.now();
  function frame(now){
    var dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    var t = now / 1000;

    cx.clearRect(0, 0, W, H);

    for (var i = 0; i < charts.length; i++){
      var c = charts[i];
      c.x += c.vx * dt; c.y += c.vy * dt; c.rot += c.rv * dt;
      wrap(c, 90, 70);
      drawChart(c, t);
    }

    for (var j = 0; j < cats.length; j++){
      var k = cats[j];
      k.x += k.vx * dt; k.y += k.vy * dt; k.rot += k.rv * dt;
      wrap(k, 70, 60);
      drawCat(k, t);
    }

    requestAnimationFrame(frame);
  }

  function resize(){
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = window.innerWidth;
    H = window.innerHeight;
    cv.width = Math.floor(W * DPR);
    cv.height = Math.floor(H * DPR);
    cv.style.width = W + 'px';
    cv.style.height = H + 'px';
    cx.setTransform(DPR, 0, 0, DPR, 0, 0);
    build();
  }

  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(frame);
})();

/* ---------- утилиты ---------- */
function $(id){ return document.getElementById(id); }
function esc(s){
  var A = String.fromCharCode(38);
  var Q = String.fromCharCode(39);
  var str = String(s == null ? '' : s);
  var out = '';
  for (var i = 0; i < str.length; i++){
    var c = str.charAt(i);
    if (c === A) out += A + 'amp;';
    else if (c === '<') out += A + 'lt;';
    else if (c === '>') out += A + 'gt;';
    else if (c === '"') out += A + 'quot;';
    else if (c === Q) out += A + '#39;';
    else out += c;
  }
  return out;
}

var state = {
  file: null, jobId: null, timer: null,
  result: null, issues: {}, filter: 'all', busy: false
};

var el = {
  statusChip: $('statusChip'), statusText: $('statusText'),
  dropzone: $('dropzone'), fileInput: $('fileInput'), fileChip: $('fileChip'),
  fileName: $('fileName'), fileClear: $('fileClear'),
  modelSel: $('modelSel'), localOnly: $('localOnly'),
  checkBtn: $('checkBtn'), textIn: $('textIn'), textBtn: $('textBtn'),
  progressWrap: $('progressWrap'), progFill: $('progFill'), progStage: $('progStage'),
  docScroll: $('docScroll'), emptyState: $('emptyState'), docHead: $('docHead'),
  ring: $('ring'), scoreVal: $('scoreVal'), scoreMeta: $('scoreMeta'),
  cntErr: $('cntErr'), cntWarn: $('cntWarn'),
  chartWrap: $('chartWrap'), filters: $('filters'), issuesList: $('issuesList'),
  notesWrap: $('notesWrap'), tip: $('tip')
};

/* ---------- здоровье сервера ---------- */
function loadHealth(){
  fetch('/api/health', { cache: 'no-store' }).then(function(r){ return r.json(); }).then(function(j){
    if (j.has_key){
      el.statusChip.className = 'chip ok';
      el.statusText.textContent = 'Groq подключён' + (j.key_hint ? ' · ' + j.key_hint : '');
    } else {
      el.statusChip.className = 'chip';
      el.statusText.textContent = 'Groq без ключа · локальный режим';
    }

    el.modelSel.innerHTML = '';
    var models = j.models || [];
    models.forEach(function(m){
      var o = document.createElement('option');
      o.value = m.id;
      o.textContent = m.label;
      if (m.id === j.default_model) o.selected = true;
      el.modelSel.appendChild(o);
    });
    if (!models.length){
      var o2 = document.createElement('option');
      o2.value = 'llama-3.3-70b-versatile';
      o2.textContent = 'llama-3.3-70b-versatile';
      el.modelSel.appendChild(o2);
    }

    if (!j.has_key){
      el.localOnly.checked = true;
      addNote('Ключ Groq не задан, работает локальный нормоконтроль. Чтобы включить нейросеть, задайте переменную окружения GROQ_API_KEY или создайте файл groq_key.txt рядом с server.py.');
    }
  }).catch(function(){
    el.statusChip.className = 'chip bad';
    el.statusText.textContent = 'сервер недоступен';
    showFatal('Не удалось связаться с сервером. Запустите python server.py и обновите страницу.');
  });
}

/* ---------- выбор файла ---------- */
function humanSize(n){
  if (n < 1024) return n + ' Б';
  if (n < 1048576) return Math.round(n / 1024) + ' КБ';
  return (n / 1048576).toFixed(1) + ' МБ';
}

function setFile(f){
  state.file = f || null;
  if (f){
    el.fileName.textContent = f.name + ' · ' + humanSize(f.size);
    el.fileChip.hidden = false;
    el.checkBtn.disabled = state.busy;
  } else {
    el.fileChip.hidden = true;
    el.checkBtn.disabled = true;
  }
}

el.dropzone.addEventListener('click', function(){ el.fileInput.click(); });

el.fileInput.addEventListener('change', function(){
  if (el.fileInput.files && el.fileInput.files[0]) setFile(el.fileInput.files[0]);
});

el.fileClear.addEventListener('click', function(e){
  e.stopPropagation();
  el.fileInput.value = '';
  setFile(null);
});

['dragenter', 'dragover'].forEach(function(ev){
  el.dropzone.addEventListener(ev, function(e){
    e.preventDefault();
    el.dropzone.classList.add('hot');
  });
});

['dragleave', 'drop'].forEach(function(ev){
  el.dropzone.addEventListener(ev, function(e){
    e.preventDefault();
    el.dropzone.classList.remove('hot');
  });
});

el.dropzone.addEventListener('drop', function(e){
  var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) setFile(f);
});

document.addEventListener('paste', function(e){
  var files = e.clipboardData && e.clipboardData.files;
  if (files && files.length){
    setFile(files[0]);
    e.preventDefault();
  }
});

/* ---------- отправка ---------- */
function b64utf8(str){
  var bytes = new TextEncoder().encode(str);
  var s = '';
  for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

el.checkBtn.addEventListener('click', function(){
  if (!state.file || state.busy) return;
  sendFile(state.file, state.file.name);
});

el.textBtn.addEventListener('click', function(){
  var txt = (el.textIn.value || '').trim();
  if (!txt){ showFatal('Вставьте текст для проверки.'); return; }
  var blob = new Blob([txt], { type: 'text/plain;charset=utf-8' });
  sendFile(blob, 'вставленный-текст.txt');
});

function sendFile(blob, name){
  setBusy(true);
  setProgress(0.02, 'Отправляю на сервер…');
  clearFatal();

  blob.arrayBuffer().then(function(buf){
    var mode = el.localOnly.checked ? 'local' : 'ai';
    return fetch('/api/check', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Filename-B64': b64utf8(name || 'document.txt'),
        'X-Mode': mode,
        'X-Model': el.modelSel.value || 'llama-3.3-70b-versatile'
      },
      body: buf
    });
  }).then(function(r){ return r.json(); }).then(function(j){
    if (!j.ok) throw new Error(j.error || 'Сервер отклонил файл');
    state.jobId = j.job_id;
    poll();
  }).catch(function(e){
    setBusy(false);
    showFatal(e.message || String(e));
  });
}

function poll(){
  fetch('/api/job?id=' + encodeURIComponent(state.jobId), { cache: 'no-store' })
    .then(function(r){ return r.json(); })
    .then(function(j){
      if (!j.ok) throw new Error(j.error || 'Задача не найдена');

      setProgress(j.progress || 0, j.stage || 'Обработка…');

      if (j.status === 'done'){
        setProgress(1, 'Готово');
        setBusy(false);
        render(j.result);
        return;
      }
      if (j.status === 'error'){
        setBusy(false);
        showFatal(j.error || 'Неизвестная ошибка на сервере');
        return;
      }
      state.timer = setTimeout(poll, 420);
    })
    .catch(function(e){
      setBusy(false);
      showFatal(e.message || String(e));
    });
}

function setBusy(b){
  state.busy = b;
  el.checkBtn.disabled = b || !state.file;
  el.textBtn.disabled = b;
  el.checkBtn.textContent = b ? 'Проверяю…' : 'Проверить диплом ИИ';
  if (!b) setTimeout(function(){ el.progressWrap.hidden = true; }, 700);
}

function setProgress(p, stage){
  el.progressWrap.hidden = false;
  el.progFill.style.width = Math.round(Math.max(0, Math.min(1, p)) * 100) + '%';
  el.progStage.textContent = stage || 'Обработка…';
}

function showFatal(msg){
  clearFatal();
  var box = document.createElement('div');
  box.className = 'errbox';
  box.id = 'fatalBox';
  box.textContent = 'Ошибка: ' + msg;
  el.docScroll.insertBefore(box, el.docScroll.firstChild);
  el.docScroll.scrollTop = 0;
}

function clearFatal(){
  var old = document.getElementById('fatalBox');
  if (old) old.remove();
}

/* ---------- отрисовка результата ---------- */
function render(r){
  if (!r || !r.paragraphs) return;

  state.result = r;
  state.issues = {};

  var byPara = {};
  r.issues.forEach(function(it){
    state.issues[it.id] = it;
    if (!byPara[it.para]) byPara[it.para] = [];
    byPara[it.para].push(it);
  });

  var paras = {};
  r.paragraphs.forEach(function(p){ paras[p.id] = p; });

  el.emptyState.style.display = 'none';
  clearFatal();
  Array.prototype.forEach.call(el.docScroll.querySelectorAll('.paper'), function(n){ n.remove(); });

  var pages = (r.pages && r.pages.length) ? r.pages : [r.paragraphs.map(function(p){ return p.id; })];
  var frag = document.createDocumentFragment();

  pages.forEach(function(ids, pi){
    var paper = document.createElement('div');
    paper.className = 'paper';

    var pg = document.createElement('div');
    pg.className = 'pgnum';
    pg.textContent = 'страница ' + (pi + 1) + ' из ' + pages.length;
    paper.appendChild(pg);

    ids.forEach(function(id){
      var p = paras[id];
      if (!p) return;
      var tag = p.kind === 'h1' ? 'h1' : p.kind === 'h2' ? 'h2' : p.kind === 'h3' ? 'h3' : p.kind === 'li' ? 'li' : 'p';
      var node = document.createElement(tag);
      node.innerHTML = paraHtml(p.text, byPara[id] || []);
      paper.appendChild(node);
    });

    frag.appendChild(paper);
  });

  el.docScroll.appendChild(frag);
  el.docScroll.scrollTop = 0;

  el.docHead.textContent = r.file || 'Просмотр документа';

  var score = Math.max(0, Math.min(100, r.score || 0));
  el.scoreVal.textContent = score;
  var col = score >= 80 ? '#4ade80' : score >= 55 ? '#ffc857' : '#ff5470';
  el.ring.style.background = 'conic-gradient(' + col + ' ' + (score * 3.6) + 'deg, rgba(255,255,255,.08) 0deg)';

  el.cntErr.textContent = r.errors;
  el.cntWarn.textContent = r.warnings;

  el.scoreMeta.innerHTML =
    '<div class="sm1">' + (r.mode === 'ai' ? 'Нейросеть Groq' : 'Локальный нормоконтроль') + '</div>' +
    '<div class="sm2">' + esc(r.summary || '') + '</div>';

  renderChart(r.chart || []);
  renderList();
  renderNotes(r.notes || []);
}

function paraHtml(text, issues){
  if (!issues.length) return esc(text);

  var arr = issues.slice().sort(function(a, b){ return a.start - b.start; });
  var out = '';
  var pos = 0;

  arr.forEach(function(it){
    var s = Math.max(0, Math.min(it.start, text.length));
    var e = Math.max(s, Math.min(it.end, text.length));
    if (s < pos) return;
    out += esc(text.slice(pos, s));
    var cls = it.severity === 'error' ? 'e' : 'w';
    out += '<mark class="hl ' + cls + '" data-id="' + it.id + '">' +
           esc(text.slice(s, e)) +
           '<sup class="badge">' + it.id + '</sup></mark>';
    pos = e;
  });

  out += esc(text.slice(pos));
  return out;
}

function renderChart(rows){
  if (!rows.length){
    el.chartWrap.innerHTML = '<div class="muted">Замечаний нет, диаграмма пустая</div>';
    return;
  }

  var max = 1;
  rows.forEach(function(r){ max = Math.max(max, r.errors + r.warnings); });

  el.chartWrap.innerHTML = rows.map(function(r){
    var ew = (r.errors / max * 100).toFixed(1);
    var ww = (r.warnings / max * 100).toFixed(1);
    return '<div class="crow">' +
      '<div class="cl"><span>' + esc(r.name) + '</span><b>' + (r.errors + r.warnings) + '</b></div>' +
      '<div class="cbar">' +
        '<i class="ce" data-w="' + ew + '"></i>' +
        '<i class="cw" data-w="' + ww + '"></i>' +
      '</div></div>';
  }).join('');

  setTimeout(function(){
    Array.prototype.forEach.call(el.chartWrap.querySelectorAll('.ce,.cw'), function(b){
      b.style.width = b.getAttribute('data-w') + '%';
    });
  }, 30);
}

function renderList(){
  var r = state.result;
  if (!r) return;

  var list = r.issues.filter(function(it){
    return state.filter === 'all' || it.severity === state.filter;
  });

  if (!list.length){
    el.issuesList.innerHTML = '<div class="muted">' +
      (r.issues.length ? 'В этой категории ничего нет.' : 'Замечаний не найдено, отличная работа!') +
      '</div>';
    return;
  }

  el.issuesList.innerHTML = list.map(function(it){
    var cls = it.severity === 'error' ? 'e' : 'w';
    var expl = String(it.explanation || '');
    if (expl.length > 130) expl = expl.slice(0, 130) + '…';
    return '<div class="issue ' + cls + '" data-id="' + it.id + '">' +
      '<div class="ih"><span class="badge">' + it.id + '</span>' +
      '<span class="it">' + esc(it.title) + '</span></div>' +
      '<div class="iq">' + esc(it.category) + '</div>' +
      '<div class="ix">' + esc(expl) + '</div>' +
    '</div>';
  }).join('');

  Array.prototype.forEach.call(el.issuesList.querySelectorAll('.issue'), function(node){
    node.addEventListener('click', function(){
      focusIssue(parseInt(node.getAttribute('data-id'), 10));
    });
  });
}

el.filters.addEventListener('click', function(e){
  var b = e.target.closest('button');
  if (!b) return;
  state.filter = b.getAttribute('data-f');
  Array.prototype.forEach.call(el.filters.querySelectorAll('button'), function(x){
    x.classList.toggle('on', x === b);
  });
  renderList();
});

function addNote(text){
  var d = document.createElement('div');
  d.className = 'note';
  d.textContent = text;
  el.notesWrap.appendChild(d);
}

function renderNotes(notes){
  if (!notes.length) return;
  el.notesWrap.innerHTML = '';
  notes.forEach(function(n){ addNote(n); });
}

function focusIssue(id){
  var mark = el.docScroll.querySelector('mark.hl[data-id="' + id + '"]');
  if (!mark) return;
  mark.scrollIntoView({ block: 'center', behavior: 'smooth' });
  mark.classList.add('pulse');
  setTimeout(function(){ mark.classList.remove('pulse'); }, 2400);
  showTip(mark);
}

/* ---------- выноска ---------- */
var tipTimer = null;

function showTip(mark){
  var it = state.issues[parseInt(mark.getAttribute('data-id'), 10)];
  if (!it) return;

  clearTimeout(tipTimer);
  var isErr = it.severity === 'error';

  el.tip.innerHTML =
    '<div class="th">' +
      '<span class="sev ' + (isErr ? 'e' : 'w') + '">' + (isErr ? 'ошибка' : 'недочёт') + '</span>' +
      '<span class="cat">' + esc(it.category) + '</span>' +
    '</div>' +
    '<div class="tt">' + esc(it.title) + '</div>' +
    (it.quote ? '<div class="tq">«' + esc(it.quote) + '»</div>' : '') +
    (it.explanation ? '<div class="te">' + esc(it.explanation) + '</div>' : '') +
    (it.suggestion ? '<div class="ts"><b>Как исправить:</b> ' + esc(it.suggestion) + '</div>' : '') +
    '<div class="src">' + (it.source === 'ai' ? 'нашла нейросеть Groq' : 'локальный нормоконтроль') + '</div>';

  el.tip.classList.add('show');
  placeTip(mark.getBoundingClientRect());
}

function placeTip(rect){
  var tw = el.tip.offsetWidth;
  var th = el.tip.offsetHeight;
  var pad = 12;

  var x = rect.left + rect.width / 2 - tw / 2;
  var y = rect.top - th - 12;

  if (y < pad) y = rect.bottom + 12;
  if (y + th > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - th - pad);
  if (x < pad) x = pad;
  if (x + tw > window.innerWidth - pad) x = window.innerWidth - tw - pad;

  el.tip.style.left = Math.round(x) + 'px';
  el.tip.style.top = Math.round(y) + 'px';
}

function hideTip(){
  tipTimer = setTimeout(function(){ el.tip.classList.remove('show'); }, 110);
}

el.docScroll.addEventListener('mouseover', function(e){
  var mark = e.target.closest('mark.hl');
  if (mark) showTip(mark);
});

el.docScroll.addEventListener('mouseout', function(e){
  var mark = e.target.closest('mark.hl');
  if (mark) hideTip();
});

el.docScroll.addEventListener('click', function(e){
  var mark = e.target.closest('mark.hl');
  if (mark) showTip(mark);
});

document.addEventListener('click', function(e){
  if (!e.target.closest('mark.hl') && !e.target.closest('.issue')){
    el.tip.classList.remove('show');
  }
});

window.addEventListener('scroll', function(){ el.tip.classList.remove('show'); }, true);
window.addEventListener('resize', function(){ el.tip.classList.remove('show'); });

/* ---------- старт ---------- */
loadHealth();
