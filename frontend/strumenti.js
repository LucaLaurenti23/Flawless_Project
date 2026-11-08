// Flawless Project - strumenti: riassunto, dati chiave, bozze, confronto tra versioni, modelli.
// Usa $, esc, api, postJson, flusso, markdown, scaricaDocx... da comune.js.
$('#logo').innerHTML = ICONE.logo;
const parametri = new URLSearchParams(location.search);
const stato = { fascicolo: null, documenti: [], modelli: [], righeDati: [], analisi: '' };

// ------------------------------------------------------------------ schede
function mostra(t) {
  document.querySelectorAll('#schede button').forEach((b) => b.classList.toggle('attiva', b.dataset.t === t));
  document.querySelectorAll('.sezione-strumento').forEach((s) => { s.hidden = s.dataset.t !== t; });
  history.replaceState(null, '', `?t=${t}`);
  if (t === 'estrazione') mostraDati();
}
document.querySelectorAll('#schede button').forEach((b) => b.addEventListener('click', () => mostra(b.dataset.t)));

async function caricaDocumenti() {
  stato.documenti = await api(`/cases/${stato.fascicolo}/documents`);
  const opzioni = stato.documenti.map((d) => `<option value="${d.id}">${esc(d.filename)}</option>`).join('')
    || '<option value="">— nessun documento nel fascicolo —</option>';
  document.querySelectorAll('[data-documenti]').forEach((s) => {
    const prima = s.value;
    s.innerHTML = opzioni;
    if (stato.documenti.some((d) => String(d.id) === prima)) s.value = prima;
  });
  // confronto: di default A = caricato prima, B = caricato dopo (l'elenco arriva dal più recente)
  if (stato.documenti.length > 1 && $('#c-a').value === $('#c-b').value) {
    $('#c-a').value = stato.documenti[1].id;
    $('#c-b').value = stato.documenti[0].id;
  }
}

function occupato(pulsanti, si) { pulsanti.forEach((p) => { p.disabled = si; }); }
const documentoScelto = (sel) => {
  const id = Number($(sel).value);
  if (!id) throw new Error('Carica prima un documento nel fascicolo.');
  return id;
};
const nomeDocumento = (id) => stato.documenti.find((d) => d.id === id)?.filename.replace(/\.[^.]+$/, '') || 'documento';

// -------------------------------------------------------------- riassunto
let testoRiassunto = '';
$('#r-avvia').addEventListener('click', async () => {
  const pulsanti = [$('#r-avvia'), $('#r-copia'), $('#r-scarica')];
  try {
    const id = documentoScelto('#r-doc');
    occupato(pulsanti, true);
    testoRiassunto = '';
    $('#r-uscita').innerHTML = '';
    $('#r-stato').textContent = 'Avvio… per documenti lunghi può richiedere alcuni minuti';
    let avvisi = [];
    await flusso('/summarize', { document_id: id }, (ev) => {
      if (ev.type === 'status') $('#r-stato').textContent = ev.text;
      if (ev.type === 'token') { testoRiassunto += ev.text; $('#r-uscita').innerHTML = markdown(testoRiassunto); }
      if (ev.type === 'avviso') avvisi = ev.testi;
    });
    $('#r-stato').textContent = avvisi.map((a) => `⚠ ${a}`).join(' ');
  } catch (err) {
    $('#r-stato').textContent = 'Errore: ' + err.message;
  } finally {
    occupato(pulsanti, false);
    $('#r-copia').disabled = $('#r-scarica').disabled = !testoRiassunto;
  }
});
$('#r-copia').addEventListener('click', () => navigator.clipboard.writeText(senzaMarkdown(testoRiassunto)));
$('#r-scarica').addEventListener('click', () => scaricaDocx(`Riassunto ${nomeDocumento(Number($('#r-doc').value))}`, testoRiassunto)
  .catch((err) => { $('#r-stato').textContent = err.message; }));

// ------------------------------------------------------------ dati chiave
const COLONNE = [['categoria', 'Categoria'], ['valore', 'Valore'], ['dettaglio', 'Dettaglio'], ['pagina', 'Pagina'], ['nel_testo', 'Nel testo']];

function tabellaDati(righe, statoEstrazione) {
  stato.righeDati = righe;
  $('#e-csv').disabled = !righe.length;
  if (!righe.length) {
    const messaggi = {
      fatto: 'Nessun dato trovato nel documento.',
      'non eseguita': 'Documento lungo: i dati non vengono estratti in automatico. Parti, date e scadenze di questo documento non compaiono finché non avvii l’estrazione.',
    };
    $('#e-uscita').innerHTML = `<div class="vuoto">${messaggi[statoEstrazione] || `Estrazione: ${esc(statoEstrazione)}.`}</div>`;
    return;
  }
  $('#e-uscita').innerHTML = `<p class="stato-lavoro">Le righe evidenziate non compaiono alla lettera nel documento: verificale.</p>
    <table class="md-tab tab-dati"><thead><tr>${COLONNE.map(([, t]) => `<th>${t}</th>`).join('')}</tr></thead>
    <tbody>${righe.map((r) => `<tr class="${r.nel_testo === 'sì' ? '' : 'da-verificare'}">${COLONNE.map(([k]) => `<td>${esc(r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

let attesaDati = null;
async function mostraDati() {
  clearTimeout(attesaDati);
  const id = Number($('#e-doc').value);
  if (!id) { $('#e-uscita').innerHTML = '<div class="vuoto">Nessun documento nel fascicolo.</div>'; return; }
  const dati = await api(`/documents/${id}/extraction`);
  const inCoda = dati.status === 'in corso' || dati.status === 'in attesa';
  $('#e-stato').textContent = inCoda ? `Estrazione ${dati.status}: lavora in background e le domande hanno la precedenza.` : '';
  $('#e-avvia').disabled = inCoda;
  $('#e-avvia').textContent = dati.status === 'non eseguita' ? 'Estrai i dati' : 'Estrai di nuovo';
  tabellaDati(dati.rows, dati.status);
  if (inCoda) attesaDati = setTimeout(() => mostraDati().catch(() => {}), 5000);
}
$('#e-doc').addEventListener('change', () => mostraDati().catch((err) => { $('#e-stato').textContent = err.message; }));

$('#e-avvia').addEventListener('click', async () => {
  try {
    const id = documentoScelto('#e-doc');
    await api(`/documents/${id}/extraction`, { method: 'POST' });
    await mostraDati();
  } catch (err) {
    $('#e-stato').textContent = 'Errore: ' + err.message;
  }
});

$('#e-csv').addEventListener('click', () => {
  // punto e virgola e BOM: Excel in italiano apre il file con le colonne giuste
  const cella = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const righe = [COLONNE.map(([, t]) => cella(t)).join(';'), ...stato.righeDati.map((r) => COLONNE.map(([k]) => cella(r[k])).join(';'))];
  scaricaBlob(new Blob(['﻿' + righe.join('\r\n')], { type: 'text/csv;charset=utf-8' }), `Dati ${nomeDocumento(Number($('#e-doc').value))}.csv`);
});

// ------------------------------------------------------------------ bozze
async function caricaModelli(scelto) {
  stato.modelli = await api('/templates');
  const inBozza = $('#b-modello').value;
  $('#b-modello').innerHTML = '<option value="">(nessun modello: bozza libera)</option>'
    + stato.modelli.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join('');
  if (stato.modelli.some((m) => String(m.id) === inBozza)) $('#b-modello').value = inBozza;
  $('#m-scelta').innerHTML = '<option value="">+ Nuovo modello</option>'
    + stato.modelli.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join('');
  $('#m-scelta').value = scelto ?? (stato.modelli[0]?.id || '');
  mostraModello();
}
// --- bozza da modello: un modulo con un campo per ogni segnaposto {{...}} del modello ---
const modelloScelto = () => stato.modelli.find((x) => String(x.id) === $('#b-modello').value);
stato.valori = {};
stato.campi = [];

async function cambiaModello() {
  const m = modelloScelto();
  const conModello = Boolean(m);
  $('#b-modulo').hidden = $('#b-azioni-modulo').hidden = !conModello;
  $('#b-azioni-libera').hidden = $('#b-campo-tipo').hidden = conModello;
  $('#b-viste').hidden = $('#b-anteprima').hidden = $('#b-uscita').hidden = $('#b-legenda').hidden = true;
  $('#b-avvia').textContent = conModello ? 'Compila con l\'IA' : 'Genera bozza';
  $('#b-etichetta-istruzioni').textContent = conModello ? 'Dati per l\'IA (facoltativo: i campi si possono compilare a mano)' : 'Istruzioni e dati';
  $('#b-stato').textContent = '';
  if (!conModello) return;
  const r = await api(`/templates/${m.id}/campi`);
  stato.campi = r.campi;
  // i valori già inseriti restano se il nuovo modello ha campi con lo stesso nome
  r.campi.forEach((c) => { if (!stato.valori[c.nome] && c.predefinito) stato.valori[c.nome] = c.predefinito; });
  disegnaCampi();
  aggiornaAnteprimaModulo();
}
$('#b-modello').addEventListener('change', cambiaModello);

const SUGGERIMENTI = { data: 'es. 3 marzo 2026', importo: 'es. 1.500,00', lungo: 'Una o più frasi' };
function disegnaCampi() {
  $('#b-campi').innerHTML = stato.campi.map((c) => {
    const valore = esc(stato.valori[c.nome] || '');
    const attributi = `data-campo="${esc(c.nome)}" placeholder="${SUGGERIMENTI[c.tipo] || ''}"`;
    return `<label class="campo"><span>${esc(c.etichetta)}</span>${c.tipo === 'lungo'
      ? `<textarea ${attributi} rows="3">${valore}</textarea>` : `<input ${attributi} value="${valore}">`}</label>`;
  }).join('') || '<p class="vuoto">Questo modello non ha campi {{...}}: aggiungili nella scheda Modelli.</p>';
}

let attesaAnteprima;
$('#b-campi').addEventListener('input', (e) => {
  const nome = e.target.dataset.campo;
  if (!nome) return;
  stato.valori[nome] = e.target.value;
  e.target.classList.remove('compilato-ia');
  clearTimeout(attesaAnteprima);
  attesaAnteprima = setTimeout(aggiornaAnteprimaModulo, 350);
});

async function aggiornaAnteprimaModulo() {
  const m = modelloScelto();
  if (!m) return;
  try {
    $('#b-anteprima-modulo').innerHTML = (await postJson(`/templates/${m.id}/anteprima`, { valori: stato.valori })).html;
  } catch (err) { $('#b-anteprima-modulo').textContent = 'Anteprima non disponibile: ' + err.message; }
}

async function scaricaModulo(formato) {
  const m = modelloScelto();
  try {
    const r = await fetch(`/api/templates/${m.id}/${formato}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ valori: stato.valori }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    scaricaBlob(await r.blob(), `${m.name}.${formato}`);
  } catch (err) { $('#b-stato').textContent = 'Errore: ' + err.message; }
}
$('#b-pdf').addEventListener('click', () => scaricaModulo('pdf'));
$('#b-word').addEventListener('click', () => scaricaModulo('docx'));
$('#b-svuota').addEventListener('click', () => {
  if (!confirm('Cancellare i valori di tutti i campi?')) return;
  stato.valori = {};
  disegnaCampi();
  aggiornaAnteprimaModulo();
});

async function compilaConIa(m) {
  const pulsanti = [$('#b-avvia'), $('#b-pdf'), $('#b-word')];
  occupato(pulsanti, true);
  $('#b-fonti').textContent = '';
  try {
    let proposti = null;
    let scartati = [];
    await flusso(`/templates/${m.id}/compila`, {
      case_id: stato.fascicolo, instructions: $('#b-istruzioni').value.trim(),
      use_case_docs: $('#b-documenti').checked, valori: stato.valori,
    }, (ev) => {
      if (ev.type === 'status') $('#b-stato').textContent = ev.text;
      if (ev.type === 'result') { proposti = ev.valori; scartati = ev.scartati || []; }
      if (ev.type === 'sources' && ev.sources.length) {
        $('#b-fonti').textContent = 'Passaggi del fascicolo usati: ' + ev.sources.map((s) => `${s.filename} (${pagina(s.page)})`).join(' · ');
      }
    });
    const nuovi = Object.keys(proposti || {}).filter((k) => proposti[k] && proposti[k] !== stato.valori[k]);
    stato.valori = { ...stato.valori, ...proposti };
    disegnaCampi();
    nuovi.forEach((k) => document.querySelector(`[data-campo="${CSS.escape(k)}"]`)?.classList.add('compilato-ia'));
    $('#b-nota-ia').hidden = !nuovi.length;
    const vuoti = stato.campi.filter((c) => !stato.valori[c.nome]).length;
    $('#b-stato').textContent = `${nuovi.length} campi compilati dall'IA` + (vuoti ? `, ${vuoti} ancora da compilare (in giallo).` : '.')
      + (scartati.length ? ` ⚠ Lasciati vuoti perché il dato non è nelle istruzioni: ${scartati.join(', ')}.` : '');
    aggiornaAnteprimaModulo();
  } catch (err) {
    $('#b-stato').textContent = 'Errore: ' + err.message;
  } finally {
    occupato(pulsanti, false);
  }
}

$('#b-avvia').addEventListener('click', async () => {
  const m = modelloScelto();
  if (m) return compilaConIa(m);
  const istruzioni = $('#b-istruzioni').value.trim();
  if (!istruzioni) { $('#b-stato').textContent = 'Scrivi i dati e le istruzioni per la bozza.'; return; }
  const pulsanti = [$('#b-avvia'), $('#b-copia'), $('#b-scarica')];
  const uscita = $('#b-uscita');
  occupato(pulsanti, true);
  // mentre il modello scrive si vede il testo; a bozza finita, l'anteprima impaginata
  $('#b-viste').hidden = $('#b-legenda').hidden = $('#b-anteprima').hidden = true;
  uscita.hidden = false;
  uscita.value = '';
  $('#b-fonti').textContent = '';
  let avvisi = [];
  try {
    await flusso('/draft', {
      case_id: stato.fascicolo, doc_type: $('#b-tipo').value.trim(), instructions: istruzioni,
      template_id: null, use_case_docs: $('#b-documenti').checked,
    }, (ev) => {
      if (ev.type === 'status') $('#b-stato').textContent = ev.text;
      if (ev.type === 'token') { uscita.value += ev.text; uscita.scrollTop = uscita.scrollHeight; }
      if (ev.type === 'avviso') avvisi = ev.testi;
      if (ev.type === 'sources' && ev.sources.length) {
        $('#b-fonti').textContent = 'Passaggi del fascicolo usati: ' + ev.sources.map((s) => `${s.filename} (${pagina(s.page)})`).join(' · ');
      }
    });
    $('#b-stato').textContent = 'Bozza pronta: controllala nell\'anteprima; con «Modifica testo» puoi correggerla prima di scaricarla.'
      + avvisi.map((a) => ` ⚠ ${a}`).join('');
  } catch (err) {
    $('#b-stato').textContent = 'Errore: ' + err.message;
  } finally {
    occupato(pulsanti, false);
    const pronta = Boolean(uscita.value.trim());
    $('#b-copia').disabled = $('#b-scarica').disabled = !pronta;
    if (pronta) {
      $('#b-viste').hidden = $('#b-legenda').hidden = false;
      vistaBozza('anteprima');
    }
  }
});

async function vistaBozza(vista) {
  document.querySelectorAll('#b-viste button').forEach((b) => b.classList.toggle('attiva', b.dataset.vista === vista));
  $('#b-uscita').hidden = vista !== 'modifica';
  $('#b-anteprima').hidden = vista !== 'anteprima';
  if (vista === 'anteprima') {
    try {
      $('#b-anteprima').innerHTML = (await postJson('/export/anteprima', { text: $('#b-uscita').value })).html;
    } catch (err) {
      $('#b-anteprima').textContent = 'Anteprima non disponibile: ' + err.message;
    }
  }
}
document.querySelectorAll('#b-viste button').forEach((b) => b.addEventListener('click', () => vistaBozza(b.dataset.vista)));
$('#b-copia').addEventListener('click', () => navigator.clipboard.writeText($('#b-uscita').value));
$('#b-scarica').addEventListener('click', () => scaricaDocx($('#b-tipo').value.trim() || 'Bozza', $('#b-uscita').value)
  .catch((err) => { $('#b-stato').textContent = err.message; }));

// -------------------------------------------------------------- confronto
const coppia = () => {
  const a = Number($('#c-a').value), b = Number($('#c-b').value);
  if (!a || !b || a === b) throw new Error('Scegli due documenti diversi.');
  return { document_a: a, document_b: b };
};

function disegnaDiff(r) {
  const s = r.stats;
  $('#c-stato').textContent = `A = ${r.a} · B = ${r.b} · ${s.modificati} modificati, ${s.aggiunti} aggiunti, ${s.rimossi} rimossi, ${s.invariati} invariati`;
  if (!r.blocks.some((b) => b.op !== 'equal')) { $('#c-diff').innerHTML = '<div class="vuoto">Le due versioni hanno lo stesso testo.</div>'; return; }
  $('#c-diff').innerHTML = r.blocks.map((b) => {
    if (b.op === 'equal') return `<div class="invariati">… ${b.count} ${b.count === 1 ? 'paragrafo invariato' : 'paragrafi invariati'} …</div>`;
    if (b.op === 'delete') return `<div class="blocco delete"><header>Rimosso · A ${esc(pagina(b.page_a))}</header><del>${esc(b.text)}</del></div>`;
    if (b.op === 'insert') return `<div class="blocco insert"><header>Aggiunto · B ${esc(pagina(b.page_b))}</header><ins>${esc(b.text)}</ins></div>`;
    return `<div class="blocco replace"><header>Modificato · B ${esc(pagina(b.page_b))}</header>${b.segments.map(([op, t]) =>
      (op === 'equal' ? esc(t) : op === 'delete' ? `<del>${esc(t)}</del>` : `<ins>${esc(t)}</ins>`)).join(' ')}</div>`;
  }).join('');
}

$('#c-avvia').addEventListener('click', async () => {
  try { disegnaDiff(await postJson('/compare', coppia())); } catch (err) { $('#c-stato').textContent = err.message; }
});

$('#c-analizza').addEventListener('click', async () => {
  const pulsanti = [$('#c-avvia'), $('#c-analizza'), $('#c-scarica')];
  try {
    const corpo = coppia();
    occupato(pulsanti, true);
    disegnaDiff(await postJson('/compare', corpo));
    stato.analisi = '';
    $('#c-analisi').innerHTML = '';
    await flusso('/compare/analyze', corpo, (ev) => {
      if (ev.type === 'token') { stato.analisi += ev.text; $('#c-analisi').innerHTML = markdown(stato.analisi); }
    });
  } catch (err) {
    $('#c-analisi').insertAdjacentHTML('beforeend', `<p style="color:var(--errore)">${esc(err.message)}</p>`);
  } finally {
    occupato(pulsanti, false);
    $('#c-scarica').disabled = !stato.analisi;
  }
});
$('#c-scarica').addEventListener('click', () => {
  const { document_a: a, document_b: b } = coppia();
  scaricaDocx(`Confronto ${nomeDocumento(a)} - ${nomeDocumento(b)}`, stato.analisi).catch((err) => { $('#c-stato').textContent = err.message; });
});

// ---------------------------------------------------------------- modelli
function mostraModello() {
  const m = stato.modelli.find((x) => String(x.id) === $('#m-scelta').value);
  $('#m-nome').value = m?.name || '';
  $('#m-testo').value = m?.body || '';
  $('#m-elimina').disabled = !m;
  $('#m-stato').textContent = '';
  mostraCampiModello();
}
$('#m-scelta').addEventListener('change', mostraModello);

// i campi del modulo sono i segnaposto {{nome}} del testo: si mostrano mentre si scrive il modello
function mostraCampiModello() {
  const nomi = [...new Set([...$('#m-testo').value.matchAll(/\{\{\s*([\w ]+?)\s*\}\}/g)].map((x) => x[1].trim()))];
  $('#m-campi').innerHTML = nomi.length
    ? `Campi del modulo (${nomi.length}): ${nomi.map((n) => `<span class="etichetta">${esc(n)}</span>`).join(' ')}`
    : 'Nessun campo: scrivi i dati da compilare tra doppie graffe, es. {{cliente}}, {{data}}, {{importo}}.';
}
$('#m-testo').addEventListener('input', mostraCampiModello);

$('#m-salva').addEventListener('click', async () => {
  const corpo = { name: $('#m-nome').value.trim(), body: $('#m-testo').value };
  if (!corpo.name || !corpo.body.trim()) { $('#m-stato').textContent = 'Nome e testo sono obbligatori.'; return; }
  try {
    const id = Number($('#m-scelta').value);
    const r = id ? await postJson(`/templates/${id}`, corpo, 'PUT') : await postJson('/templates', corpo);
    await caricaModelli(id || r.id);
    $('#m-stato').textContent = 'Modello salvato.';
  } catch (err) { $('#m-stato').textContent = err.message; }
});

$('#m-elimina').addEventListener('click', async () => {
  const id = Number($('#m-scelta').value);
  if (!id || !confirm(`Eliminare il modello «${$('#m-nome').value}»?`)) return;
  try { await api(`/templates/${id}`, { method: 'DELETE' }); await caricaModelli(''); } catch (err) { $('#m-stato').textContent = err.message; }
});

// ------------------------------------------------------------------ avvio
(async () => {
  try {
    stato.fascicolo = await preparaFascicolo($('#fascicolo'), async (id) => {
      stato.fascicolo = id;
      await caricaDocumenti();
      if (!$('.sezione-strumento[data-t="estrazione"]').hidden) mostraDati();
    });
    await Promise.all([caricaDocumenti(), caricaModelli()]);
    const doc = parametri.get('doc');
    if (doc && stato.documenti.some((d) => String(d.id) === doc)) document.querySelectorAll('#r-doc, #e-doc').forEach((s) => { s.value = doc; });
    mostra(parametri.get('t') || 'riassunto');
  } catch (err) {
    document.querySelector('.pagina').insertAdjacentHTML('afterbegin', `<div class="vuoto" style="color:var(--errore)">${esc(err.message)}</div>`);
  }
})();
