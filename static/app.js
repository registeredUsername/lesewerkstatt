/* ═══════════════════════════════════════════════════════════════════════
   Lesewerkstatt — app.js
   SPA logic: API calls, routing, reader, word management.
   Adapted from the proven lesewerkstatt.html prototype.
   ═══════════════════════════════════════════════════════════════════════ */

/* ============================ API LAYER ============================ */
const API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${r.status}`);
    }
    return r.json();
  },

  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${r.status}`);
    }
    return r.json();
  },

  async postForm(path, formData) {
    const r = await fetch(path, { method: 'POST', body: formData });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${r.status}`);
    }
    return r.json();
  },

  async del(path) {
    const r = await fetch(path, { method: 'DELETE' });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${r.status}`);
    }
    return r.json();
  },
};

/* ============================ STATE ============================ */
let savedWords = {};   // from API { surface: { display, fr, lemma, source_id } }
let activeGloss = {};  // glossary of current text: surfaceLower -> entry
let activeTab = 'lib';
let readMode = 'tap';  // 'tap' | 'inl'
let addMode = 'url';   // 'url' | 'paste' | 'pdf' | 'anki'
let currentSourceId = null;
let ankiDirection = 'de';
let ankiPreview = null;

const main = document.getElementById('main');
const sheet = document.getElementById('sheet');
const backdrop = document.getElementById('backdrop');
const sheetBody = document.getElementById('sheetBody');
let sheetWordEl = null;

/* ============================ HELPERS ============================ */
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function escapeReg(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 1600);
}

function updateCount() {
  document.getElementById('wcount').textContent = Object.keys(savedWords).length;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'Z');
  return d.toLocaleDateString('fr-CH', { day: 'numeric', month: 'short', year: 'numeric' });
}

/* ============================ TABS ============================ */
function renderTabs() {
  document.querySelectorAll('#tabs button').forEach(b =>
    b.setAttribute('aria-selected', b.dataset.tab === activeTab ? 'true' : 'false'));
}

document.querySelectorAll('#tabs button').forEach(b =>
  b.addEventListener('click', () => {
    if (b.dataset.tab === 'lib') renderLibrary();
    else renderAdd();
  })
);

/* ============================ LIBRARY ============================ */
const CATS = [
  ['metier', 'Métier — santé numérique'],
  ['gaming', 'Gaming'],
  ['ia', 'IA'],
  ['aktuell', 'Actualité'],
];

function cardHTML(d) {
  const date = formatDate(d.created_at);
  return `<div class="card" data-id="${d.id}">
    <div class="eyebrow"><span class="dot"></span>${escapeHtml(d.source_label || 'Source')}</div>
    <h3>${escapeHtml(d.title)}</h3>
    <div class="meta">
      <span><b>${d.gloss_count || 0}</b> mots clés</span>
      <span><b>${d.word_count || 0}</b> mots</span>
      <span>~${Math.max(1, Math.round((d.word_count || 0) / 110))} min</span>
      ${date ? `<span>${date}</span>` : ''}
    </div>
  </div>`;
}

async function renderLibrary() {
  activeTab = 'lib';
  renderTabs();

  main.innerHTML = `<div class="loading"><div class="spin"></div><div class="label">Chargement…</div></div>`;

  try {
    const sources = await API.get('/api/sources');

    if (!sources.length) {
      main.innerHTML = `
        <p class="lead">Aucune source pour le moment.<br>
        <b>Ajoute un article</b> via l'onglet « Ajouter » — URL, texte collé ou PDF.</p>`;
      return;
    }

    let html = `<p class="lead">Tes sources. <b>Touche un mot souligné</b> pour la traduction, ou bascule en mode intercalé.</p>`;

    CATS.forEach(([key, label]) => {
      const items = sources.filter(d => d.category === key);
      if (!items.length) return;
      html += `<div class="cathead">${label} <span>${items.length}</span></div>`;
      items.forEach(d => html += cardHTML(d));
    });

    // Uncategorized
    const known = CATS.map(c => c[0]);
    const other = sources.filter(d => !known.includes(d.category));
    if (other.length) {
      html += `<div class="cathead">Autre <span>${other.length}</span></div>`;
      other.forEach(d => html += cardHTML(d));
    }

    main.innerHTML = html;
    main.querySelectorAll('.card').forEach(c =>
      c.addEventListener('click', () => openSource(parseInt(c.dataset.id)))
    );
  } catch (err) {
    main.innerHTML = `<div class="err">Erreur : ${escapeHtml(err.message)}</div>`;
  }
}

async function openSource(id) {
  main.innerHTML = `<div class="loading"><div class="spin"></div><div class="label">Chargement de la source…</div></div>`;

  try {
    const source = await API.get(`/api/sources/${id}`);
    currentSourceId = id;

    // Build gloss map: { surfaceLower: { fr, lemma, note } }
    activeGloss = {};
    const glossMap = {};
    (source.gloss || []).forEach(entry => {
      glossMap[entry.w] = { fr: entry.fr, lemma: entry.lemma || '', note: entry.note || '' };
      activeGloss[entry.w.toLowerCase()] = { fr: entry.fr, lemma: entry.lemma || '', note: entry.note || '' };
    });

    renderReader({
      heading: source.title,
      text: source.text,
      gloss: glossMap,
      tag: source.source_label || 'Source',
      url: source.url,
      sourceId: id,
    });
  } catch (err) {
    main.innerHTML = `<div class="err">Erreur : ${escapeHtml(err.message)}</div>`;
  }
}

/* ============================ READER ============================ */
function buildArticleHTML(text, gloss) {
  const keys = Object.keys(gloss).sort((a, b) => b.length - a.length);
  if (!keys.length) return escapeHtml(text);
  const pattern = new RegExp('(' + keys.map(escapeReg).join('|') + ')', 'g');
  let out = '', last = 0, m;
  while ((m = pattern.exec(text)) !== null) {
    const surf = m[0], i = m.index;
    const prev = i > 0 ? text[i - 1] : ' ';
    if (/[A-Za-zÀ-ÿß]/.test(prev)) { continue; }
    out += escapeHtml(text.slice(last, i));
    const entry = gloss[surf] || gloss[Object.keys(gloss).find(k => k.toLowerCase() === surf.toLowerCase())];
    const sl = surf.toLowerCase();
    const isSaved = !!savedWords[sl];
    out += `<span class="tw${isSaved ? ' saved' : ''}" data-w="${escapeHtml(surf)}">` +
           `${escapeHtml(surf)}<span class="gl">${escapeHtml(entry ? entry.fr.split(/[,;]/)[0] : '')}</span></span>`;
    last = i + surf.length;
    pattern.lastIndex = last;
  }
  out += escapeHtml(text.slice(last));
  return out;
}

function renderReader({ heading, text, gloss, tag, url, sourceId }) {
  const articleHTML = buildArticleHTML(text, gloss);
  const deleteBtn = sourceId
    ? `<button class="back" id="delSource" style="color:var(--slate);font-weight:500;margin-left:0.5rem">Supprimer</button>`
    : '';

  main.innerHTML = `
    <div class="readtop">
      <button class="back" id="backBtn">‹ Retour</button>
      ${deleteBtn}
      <div class="spacer"></div>
      <div class="seg" role="group" aria-label="Mode de lecture">
        <button id="mTap" aria-pressed="${readMode === 'tap'}">Toucher</button>
        <button id="mInl" aria-pressed="${readMode === 'inl'}">Intercalé</button>
      </div>
    </div>
    <div class="src">${escapeHtml(tag)} ${url ? `· <a href="${url}" target="_blank" rel="noopener">source ↗</a>` : ''}</div>
    <div class="article ${readMode === 'inl' ? 'inl' : ''}" id="article">
      ${heading ? `<h2>${escapeHtml(heading)}</h2>` : ''}
      ${articleHTML}
    </div>`;

  document.getElementById('backBtn').addEventListener('click', () => renderLibrary());
  document.getElementById('mTap').addEventListener('click', () => setMode('tap'));
  document.getElementById('mInl').addEventListener('click', () => setMode('inl'));

  const delBtn = document.getElementById('delSource');
  if (delBtn) {
    delBtn.addEventListener('click', async () => {
      if (!confirm('Supprimer cette source ?')) return;
      try {
        await API.del(`/api/sources/${sourceId}`);
        toast('Source supprimée');
        renderLibrary();
      } catch (e) {
        toast('Erreur : ' + e.message);
      }
    });
  }

  bindWords();
}

function setMode(m) {
  readMode = m;
  const a = document.getElementById('article');
  if (a) a.classList.toggle('inl', m === 'inl');
  document.getElementById('mTap').setAttribute('aria-pressed', m === 'tap');
  document.getElementById('mInl').setAttribute('aria-pressed', m === 'inl');
}

function bindWords() {
  main.querySelectorAll('.tw').forEach(el =>
    el.addEventListener('click', () => openSheet(el.dataset.w, el))
  );
}

/* ============================ BOTTOM SHEET (WORD CARD) ============================ */
function openSheet(surf, el) {
  const sl = surf.toLowerCase();
  const e = activeGloss[sl];
  if (!e) return;
  sheetWordEl = el;
  main.querySelectorAll('.tw.on').forEach(x => x.classList.remove('on'));
  el.classList.add('on');
  const isSaved = !!savedWords[sl];
  sheetBody.innerHTML = `
    <div class="wc-head">
      <h4>${escapeHtml(surf)}</h4>
      ${e.lemma ? `<span class="wc-lemma">${escapeHtml(e.lemma)}</span>` : ''}
    </div>
    <div class="wc-fr">${escapeHtml(e.fr)}</div>
    ${e.note ? `<div class="wc-note">${e.note.replace(/([a-zäöüß]+- ?\+ ?[a-zäöüß]+)/gi, '<span class="mono">$1</span>')}</div>` : ''}
    <div class="wc-actions">
      <button id="keepBtn" class="keep ${isSaved ? 'is-saved' : ''}">${isSaved ? '✓ Gardé' : '+ Garder'}</button>
      <button id="closeBtn">Fermer</button>
    </div>`;
  document.getElementById('keepBtn').addEventListener('click', () => toggleSave(surf, e));
  document.getElementById('closeBtn').addEventListener('click', closeSheet);
  backdrop.classList.add('show');
  sheet.classList.add('show');
}

function closeSheet() {
  sheet.classList.remove('show');
  backdrop.classList.remove('show');
  main.querySelectorAll('.tw.on').forEach(x => x.classList.remove('on'));
}

backdrop.addEventListener('click', closeSheet);

function decompositionToNote(decomposition) {
  const lines = (decomposition || [])
    .map(d => (d.part || '').trim() && (d.meaning || '').trim()
      ? `- ${d.part.trim()} : ${d.meaning.trim()}`
      : null)
    .filter(Boolean);
  return lines.length ? lines.join('\n') : null;
}

async function toggleSave(surf, e) {
  const sl = surf.toLowerCase();
  const btn = document.getElementById('keepBtn');
  try {
    if (savedWords[sl]) {
      await API.del(`/api/words/${encodeURIComponent(sl)}`);
      delete savedWords[sl];
      if (sheetWordEl) sheetWordEl.classList.remove('saved');
      toast('Retiré');
    } else {
      // Show loading state on the button
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Génération…';
      }

      let display = surf;
      let fr = e.fr;
      let note = e.note || null;

      try {
        // Call LLM for high-quality entry (same as Entrée Anki)
        const result = await API.post('/api/anki-entry/generate', {
          word: e.lemma || surf,
          direction: 'de',
        });
        display = result.de;
        fr = result.fr;
        note = decompositionToNote(result.decomposition);
      } catch (llmErr) {
        // Fallback: use raw glossary data
        toast('Ajouté (mode simplifié — IA indisponible)');
      }

      await API.post('/api/words', {
        surface: sl,
        display: display,
        fr: fr,
        lemma: e.lemma || null,
        source_id: currentSourceId,
        note: note,
      });
      savedWords[sl] = { display: display, fr: fr, lemma: e.lemma || '', note: note || '' };
      if (sheetWordEl) sheetWordEl.classList.add('saved');
      toast('Gardé pour Anki');
    }
  } catch (err) {
    toast('Erreur : ' + err.message);
  }
  updateCount();
  if (btn) {
    btn.disabled = false;
    const on = !!savedWords[sl];
    btn.classList.toggle('is-saved', on);
    btn.textContent = on ? '✓ Gardé' : '+ Garder';
  }
}

/* ============================ MES MOTS (WORD LIST) ============================ */
async function openWords() {
  // Refresh word list from API
  try {
    const words = await API.get('/api/words');
    savedWords = {};
    words.forEach(w => {
      savedWords[w.surface] = { display: w.display, fr: w.fr, lemma: w.lemma || '', note: w.note || '' };
    });
    updateCount();
  } catch (e) { /* use cached */ }

  const keys = Object.keys(savedWords);
  let body;
  if (!keys.length) {
    body = `<p class="words-empty">Aucun mot enregistré.<br>Touche un mot en lecture, puis « Garder » pour le retrouver ici et l'exporter vers Anki.</p>`;
  } else {
    body = `<div class="wlist">` + keys.map(k => {
      const w = savedWords[k];
      return `<div class="wrow" data-k="${escapeHtml(k)}">
        <span class="de">${escapeHtml(w.display)}</span>
        <span class="fr">${escapeHtml(w.fr)}</span>
        <button class="del" aria-label="Retirer">×</button></div>`;
    }).join('') + `</div>`;
  }

  sheetBody.innerHTML = `
    <div class="wc-head"><h4 style="font-family:var(--sans);font-size:1.15rem">Mes mots</h4>
    <span class="wc-lemma">${keys.length}</span></div>
    ${body}
    <div class="toolbar">
      <button class="exp" id="expBtn" ${keys.length ? '' : 'disabled'}>Exporter vers Anki</button>
      <button id="closeBtn2">Fermer</button>
    </div>`;

  sheetBody.querySelectorAll('.del').forEach(b => b.addEventListener('click', async ev => {
    const row = ev.target.closest('.wrow');
    const k = row.dataset.k;
    try {
      await API.del(`/api/words/${encodeURIComponent(k)}`);
      delete savedWords[k];
      updateCount();
      // Refresh word highlight in reader
      main.querySelectorAll(`.tw`).forEach(el => {
        if (el.dataset.w.toLowerCase() === k) el.classList.remove('saved');
      });
      openWords();
    } catch (e) {
      toast('Erreur : ' + e.message);
    }
  }));

  document.getElementById('expBtn')?.addEventListener('click', exportAnki);
  document.getElementById('closeBtn2').addEventListener('click', closeSheet);
  backdrop.classList.add('show');
  sheet.classList.add('show');
}

document.getElementById('openWords').addEventListener('click', openWords);

function exportAnki() {
  // Use the API export endpoint
  window.location.href = '/api/words/export';
  toast('Fichier Anki téléchargé');
}

/* ============================ ADD SOURCE ============================ */
function renderAdd() {
  activeTab = 'add';
  renderTabs();

  main.innerHTML = `
    <p class="lead">Ajoute une source allemande — article web, texte copié ou PDF. Le glossaire sera généré automatiquement.</p>

    <div class="mode-tabs" id="addModeTabs">
      <button class="${addMode === 'url' ? 'active' : ''}" data-mode="url">🔗 URL</button>
      <button class="${addMode === 'paste' ? 'active' : ''}" data-mode="paste">📋 Texte</button>
      <button class="${addMode === 'pdf' ? 'active' : ''}" data-mode="pdf">📄 PDF</button>
      <button class="${addMode === 'anki' ? 'active' : ''}" data-mode="anki">🧠 Entrée Anki</button>
    </div>

    <div id="addForm"></div>
    <div id="addErr"></div>`;

  document.querySelectorAll('#addModeTabs button').forEach(b =>
    b.addEventListener('click', () => {
      addMode = b.dataset.mode;
      document.querySelectorAll('#addModeTabs button').forEach(x =>
        x.classList.toggle('active', x.dataset.mode === addMode));
      renderAddForm();
    })
  );

  renderAddForm();
}

function renderAddForm() {
  const form = document.getElementById('addForm');
  document.getElementById('addErr').innerHTML = '';

  if (addMode === 'url') {
    form.innerHTML = `
      <div class="form-section">
        <label class="form-label" for="addUrl">Adresse web</label>
        <input class="form-input" id="addUrl" type="url" placeholder="https://www.example.ch/article">
      </div>
      <div class="form-row">
        <div>
          <label class="form-label" for="addLabel">Source (optionnel)</label>
          <input class="form-input" id="addLabel" placeholder="NZZ, admin.ch…">
        </div>
        <div>
          <label class="form-label" for="addCat">Catégorie</label>
          <select class="form-input" id="addCat">
            <option value="aktuell">Actualité</option>
            <option value="metier">Métier</option>
            <option value="gaming">Gaming</option>
            <option value="ia">IA</option>
          </select>
        </div>
      </div>
      <button class="primary" id="addSubmit">Analyser l'article</button>
      <p class="hint">L'article sera extrait, les mots difficiles identifiés par IA. Peut prendre ~15 secondes.</p>`;

    document.getElementById('addSubmit').addEventListener('click', submitUrl);

  } else if (addMode === 'paste') {
    form.innerHTML = `
      <div class="form-section">
        <label class="form-label" for="addTitle">Titre</label>
        <input class="form-input" id="addTitle" placeholder="Titre du texte">
      </div>
      <div class="form-row">
        <div>
          <label class="form-label" for="addLabel">Source</label>
          <input class="form-input" id="addLabel" placeholder="NZZ, admin.ch…" value="Source">
        </div>
        <div>
          <label class="form-label" for="addCat">Catégorie</label>
          <select class="form-input" id="addCat">
            <option value="aktuell">Actualité</option>
            <option value="metier">Métier</option>
            <option value="gaming">Gaming</option>
            <option value="ia">IA</option>
          </select>
        </div>
      </div>
      <div class="form-section">
        <label class="form-label" for="addText">Texte allemand</label>
        <textarea class="form-input" id="addText" placeholder="Text hier einfügen…"></textarea>
      </div>
      <button class="primary" id="addSubmit">Traiter le texte</button>
      <p class="hint">Idéal : 1–4 paragraphes. Le glossaire est généré automatiquement (~15 s).</p>`;

    document.getElementById('addSubmit').addEventListener('click', submitPaste);

  } else if (addMode === 'pdf') {
    form.innerHTML = `
      <div class="form-row">
        <div>
          <label class="form-label" for="addLabel">Source (optionnel)</label>
          <input class="form-input" id="addLabel" placeholder="DigiSanté, BAG…">
        </div>
        <div>
          <label class="form-label" for="addCat">Catégorie</label>
          <select class="form-input" id="addCat">
            <option value="metier" selected>Métier</option>
            <option value="aktuell">Actualité</option>
            <option value="gaming">Gaming</option>
            <option value="ia">IA</option>
          </select>
        </div>
      </div>
      <div class="upload-zone" id="uploadZone">
        <div class="icon">📄</div>
        <div class="label">Dépose un PDF ici</div>
        <div class="sub">ou clique pour sélectionner</div>
        <div class="filename" id="pdfName"></div>
      </div>
      <input type="file" id="pdfFile" accept=".pdf" hidden>
      <button class="primary" id="addSubmit" disabled>Analyser le PDF</button>
      <p class="hint">Le texte sera extrait du PDF, puis analysé (~15–30 s selon la longueur).</p>`;

    const zone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('pdfFile');
    const submitBtn = document.getElementById('addSubmit');

    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });

    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      if (file) {
        document.getElementById('pdfName').textContent = file.name;
        submitBtn.disabled = false;
      }
    });

    submitBtn.addEventListener('click', submitPdf);
  } else if (addMode === 'anki') {
    if (!ankiPreview) {
      // ── Input form ──
      form.innerHTML = `
        <div class="anki-direction">
          <div class="seg" role="group" aria-label="Direction">
            <button id="ankiDe" aria-pressed="${ankiDirection === 'de'}">🇩🇪 Allemand</button>
            <button id="ankiFr" aria-pressed="${ankiDirection === 'fr'}">🇫🇷 Français</button>
          </div>
        </div>
        <div class="form-section">
          <label class="form-label" for="ankiWord">${ankiDirection === 'de' ? 'Mot allemand' : 'Mot français'}</label>
          <input class="form-input" id="ankiWord" type="text" placeholder="${ankiDirection === 'de' ? 'z.B. abstimmen, Krankenkasse…' : 'ex. assurance maladie, voter…'}">
        </div>
        <button class="primary" id="ankiGenerate">Générer la fiche</button>
        <p class="hint">L'IA trouvera la forme de dictionnaire, la traduction et la décomposition morphologique (~5 s).</p>`;

      document.getElementById('ankiDe').addEventListener('click', () => {
        ankiDirection = 'de';
        renderAddForm();
      });
      document.getElementById('ankiFr').addEventListener('click', () => {
        ankiDirection = 'fr';
        renderAddForm();
      });
      document.getElementById('ankiGenerate').addEventListener('click', submitAnkiGenerate);

      // Enter key submits
      document.getElementById('ankiWord').addEventListener('keydown', e => {
        if (e.key === 'Enter') submitAnkiGenerate();
      });
    } else {
      // ── Editable preview ──
      const p = ankiPreview;
      let decompHTML = '';
      if (p.decomposition && p.decomposition.length) {
        decompHTML = p.decomposition.map((d, i) =>
          `<div class="decomp-row" data-i="${i}">
            <input class="decomp-part" value="${escapeHtml(d.part)}" placeholder="Partie">
            <input class="decomp-meaning" value="${escapeHtml(d.meaning)}" placeholder="Sens">
            <button class="del" aria-label="Supprimer">×</button>
          </div>`
        ).join('');
      }

      form.innerHTML = `
        <div class="anki-preview">
          <div class="form-section">
            <label class="form-label" for="ankiDe">Recto (allemand)</label>
            <input class="form-input" id="ankiDeField" type="text" value="${escapeHtml(p.de)}">
          </div>
          <div class="form-section">
            <label class="form-label" for="ankiFr">Verso (français)</label>
            <input class="form-input" id="ankiFrField" type="text" value="${escapeHtml(p.fr)}">
          </div>
          <div class="form-section">
            <div class="decomp-label">
              <span class="form-label" style="margin-bottom:0">Décomposition</span>
            </div>
            <div id="decompList">${decompHTML}</div>
            <button class="decomp-add" id="decompAdd">+ Ajouter une décomposition</button>
          </div>
        </div>
        <div class="anki-actions">
          <button class="primary" id="ankiSave">Ajouter à mes mots</button>
          <button class="primary secondary-btn" id="ankiCancel">Annuler</button>
        </div>`;

      // Delete decomposition row
      form.querySelectorAll('.decomp-row .del').forEach(btn =>
        btn.addEventListener('click', () => {
          const row = btn.closest('.decomp-row');
          row.remove();
        })
      );

      // Add decomposition row
      document.getElementById('decompAdd').addEventListener('click', () => {
        const list = document.getElementById('decompList');
        const div = document.createElement('div');
        div.className = 'decomp-row';
        div.innerHTML = `
          <input class="decomp-part" value="" placeholder="Partie">
          <input class="decomp-meaning" value="" placeholder="Sens">
          <button class="del" aria-label="Supprimer">×</button>`;
        div.querySelector('.del').addEventListener('click', () => div.remove());
        list.appendChild(div);
      });

      // Save
      document.getElementById('ankiSave').addEventListener('click', submitAnkiSave);

      // Cancel
      document.getElementById('ankiCancel').addEventListener('click', () => {
        ankiPreview = null;
        renderAddForm();
      });
    }
  }
}

async function submitUrl() {
  const url = document.getElementById('addUrl')?.value?.trim();
  const errBox = document.getElementById('addErr');
  errBox.innerHTML = '';

  if (!url) {
    errBox.innerHTML = `<div class="err">Fournis une URL.</div>`;
    return;
  }

  const label = document.getElementById('addLabel')?.value?.trim() || 'Source';
  const category = document.getElementById('addCat')?.value || 'aktuell';

  showIngesting();

  try {
    const fd = new FormData();
    fd.append('url', url);
    fd.append('source_label', label);
    fd.append('category', category);
    const source = await API.postForm('/api/sources', fd);
    handleSourceCreated(source);
  } catch (err) {
    renderAdd();
    document.getElementById('addErr').innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
  }
}

async function submitPaste() {
  const text = document.getElementById('addText')?.value?.trim();
  const title = document.getElementById('addTitle')?.value?.trim();
  const errBox = document.getElementById('addErr');
  errBox.innerHTML = '';

  if (!text || text.length < 20) {
    errBox.innerHTML = `<div class="err">Texte trop court — colle au moins un paragraphe.</div>`;
    return;
  }
  if (!title) {
    errBox.innerHTML = `<div class="err">Le titre est requis.</div>`;
    return;
  }

  const label = document.getElementById('addLabel')?.value?.trim() || 'Source';
  const category = document.getElementById('addCat')?.value || 'aktuell';

  showIngesting();

  try {
    const fd = new FormData();
    fd.append('text', text);
    fd.append('title', title);
    fd.append('source_label', label);
    fd.append('category', category);
    const source = await API.postForm('/api/sources', fd);
    handleSourceCreated(source);
  } catch (err) {
    renderAdd();
    document.getElementById('addErr').innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
  }
}

async function submitPdf() {
  const fileInput = document.getElementById('pdfFile');
  const file = fileInput?.files?.[0];
  const errBox = document.getElementById('addErr');
  errBox.innerHTML = '';

  if (!file) {
    errBox.innerHTML = `<div class="err">Sélectionne un fichier PDF.</div>`;
    return;
  }

  const label = document.getElementById('addLabel')?.value?.trim() || 'Source';
  const category = document.getElementById('addCat')?.value || 'metier';

  showIngesting();

  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('source_label', label);
    fd.append('category', category);
    const source = await API.postForm('/api/sources', fd);
    handleSourceCreated(source);
  } catch (err) {
    renderAdd();
    document.getElementById('addErr').innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
  }
}

function showIngesting() {
  main.innerHTML = `
    <div class="loading">
      <div class="spin"></div>
      <div class="label">Extraction et analyse en cours…</div>
      <div class="progress-bar"><div class="fill"></div></div>
      <p class="hint" style="text-align:center;margin-top:0.8rem">Le texte est extrait, puis un modèle d'IA identifie les mots difficiles.<br>Cela peut prendre 10–30 secondes.</p>
    </div>`;
}

function handleSourceCreated(source) {
  if (source.warning) {
    toast(source.warning);
  }
  toast('Source ajoutée !');
  openSource(source.id);
}

/* ============================ ANKI ENTRY ============================ */
async function submitAnkiGenerate() {
  const word = document.getElementById('ankiWord')?.value?.trim();
  const errBox = document.getElementById('addErr');
  errBox.innerHTML = '';

  if (!word) {
    errBox.innerHTML = `<div class="err">Saisis un mot.</div>`;
    return;
  }

  const btn = document.getElementById('ankiGenerate');
  const origText = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = `<span class="anki-loading"><span class="spin"></span> Génération…</span>`;

  try {
    const result = await API.post('/api/anki-entry/generate', {
      word: word,
      direction: ankiDirection,
    });
    ankiPreview = result;
    renderAddForm();
  } catch (err) {
    errBox.innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
    btn.disabled = false;
    btn.textContent = origText;
  }
}

async function submitAnkiSave() {
  const de = document.getElementById('ankiDeField')?.value?.trim();
  const fr = document.getElementById('ankiFrField')?.value?.trim();
  const errBox = document.getElementById('addErr');
  errBox.innerHTML = '';

  if (!de || !fr) {
    errBox.innerHTML = `<div class="err">Les champs recto et verso sont requis.</div>`;
    return;
  }

  // Gather decomposition from DOM
  const decomposition = [];
  document.querySelectorAll('#decompList .decomp-row').forEach(row => {
    const part = row.querySelector('.decomp-part')?.value?.trim();
    const meaning = row.querySelector('.decomp-meaning')?.value?.trim();
    if (part && meaning) {
      decomposition.push({ part, meaning });
    }
  });

  const saveBtn = document.getElementById('ankiSave');
  saveBtn.disabled = true;

  try {
    const saved = await API.post('/api/anki-entry/save', { de, fr, decomposition });
    savedWords[saved.surface] = { display: saved.display, fr: saved.fr, lemma: saved.lemma || '', note: saved.note || '' };
    updateCount();
    toast('Ajouté !');
    ankiPreview = null;
    renderAddForm();
  } catch (err) {
    errBox.innerHTML = `<div class="err">${escapeHtml(err.message)}</div>`;
    saveBtn.disabled = false;
  }
}

/* ============================ LOAD SAVED WORDS ============================ */
async function loadSavedWords() {
  try {
    const words = await API.get('/api/words');
    savedWords = {};
    words.forEach(w => {
      savedWords[w.surface] = { display: w.display, fr: w.fr, lemma: w.lemma || '', note: w.note || '' };
    });
  } catch (e) {
    // Offline or error — use empty
    savedWords = {};
  }
  updateCount();
}

/* ============================ SERVICE WORKER ============================ */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

/* ============================ INIT ============================ */
loadSavedWords().then(renderLibrary);
