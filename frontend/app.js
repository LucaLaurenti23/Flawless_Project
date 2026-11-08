// Flawless Project - pagina principale: storico, fascicoli, documenti e tempi (sinistra), chat (centro),
// elementi del fascicolo (destra). Usa $, esc, api, flusso, markdown... da comune.js.
const media = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
const NOMI_TIPO = { parti: 'Parti', date: 'Date', scadenze: 'Scadenze', importi: 'Importi' };
const ESTENSIONI_OK = ['.pdf', '.docx', '.txt', '.md'];   // come SUPPORTED in backend/documents.py
const estensioneOk = (nome) => ESTENSIONI_OK.some((e) => nome.toLowerCase().endsWith(e));

const stato = {
  scheda: 'storico', fascicoli: [], fascicolo: null, documenti: [], conversazioni: [], tempi: [], server: {},
  elementi: { parti: [], date: [], scadenze: [], importi: [] }, infoDocumenti: [], tipoDestra: 'parti',
  aperte: new Set(), occupato: false, conversazione: null, modalita: 'rag', approfondita: false,
  normativa: { atti: [], parti: 0, indicizzate: 0, aggiornamento: {} },
};
const NOMI_MODALITA = { rag: 'documenti', norm: 'normativa', chat: 'libera' };

$('#logo').innerHTML = ICONE.logo;
$('#avatar-chat').insertAdjacentHTML('afterbegin', ICONE.logo);
const fascicoloCorrente = () => stato.fascicoli.find((f) => f.id === stato.fascicolo);

// ------------------------------------------------------------------ dati
async function aggiornaTutto() {
  const [server, fascicoli] = await Promise.all([api('/status'), api('/cases')]);
  stato.server = server;
  stato.fascicoli = fascicoli;
  let id = stato.fascicolo || fascicoloSalvato();
  if (!fascicoli.some((f) => f.id === id)) id = fascicoli[0]?.id;
  stato.fascicolo = id;
  salvaFascicolo(id);
  const [documenti, conversazioni, tempi, elementi, norme] = await Promise.all([
    api(`/cases/${id}/documents`), api(`/cases/${id}/conversations`), api(`/cases/${id}/timings`), api(`/cases/${id}/elements`),
    api('/normativa'),
  ]);
  Object.assign(stato, { documenti, conversazioni, tempi, elementi: elementi.elementi, infoDocumenti: elementi.documenti, normativa: norme });
  disegnaStato();
  disegnaSinistra();
  disegnaElementi();
  disegnaAmbito();
}

async function aggiornaElementi() {
  const id = stato.fascicolo;
  const [documenti, elementi] = await Promise.all([api(`/cases/${id}/documents`), api(`/cases/${id}/elements`)]);
  if (id !== stato.fascicolo) return;
  Object.assign(stato, { documenti, elementi: elementi.elementi, infoDocumenti: elementi.documenti });
  disegnaElementi();
  if (stato.scheda === 'documenti') disegnaSinistra();
}

// ------------------------------------------------------------- testata
function disegnaStato() {
  const s = stato.server;
  const f = fascicoloCorrente();
  const selFascicolo = $('#fascicolo');
  selFascicolo.innerHTML = stato.fascicoli.map((x) => `<option value="${x.id}" ${x.id === stato.fascicolo ? 'selected' : ''}>${esc(x.name)}</option>`).join('');
  const sel = $('#modello');
  const modelli = Array.from(new Set([s.chat_model, ...(s.models || [])]));
  if (sel.dataset.elenco !== modelli.join('|')) {
    sel.innerHTML = modelli.map((m) => `<option ${m === s.chat_model ? 'selected' : ''}>${esc(m)}</option>`).join('');
    sel.dataset.elenco = modelli.join('|');
  }
  const pill = (id, classe, testo) => { $(id).innerHTML = `<i class="punto ${classe}"></i>${esc(testo)}`; };
  $('#stato-fascicolo span').textContent = f ? f.name + (f.client ? ` · ${f.client}` : '') : '—';
  pill('#stato-ollama', s.ollama ? 'ok' : 'ko', s.ollama ? 'Ollama attivo' : 'Ollama spento');
  const embeddingOk = s.ollama && !(s.missing_models || []).some((m) => m.startsWith(s.embed_model));
  pill('#stato-embedding', embeddingOk ? 'ok' : 'attesa', embeddingOk ? `Ricerca semantica · ${s.embed_model}` : 'Modello di ricerca mancante');
  $('#stato-documenti span').textContent = f ? `${f.documents} documenti · ${f.chunks} frammenti` : '—';
  const n = s.normativa || {};
  const pct = n.parti ? Math.floor(n.indicizzate / n.parti * 100) : 0;
  pill('#stato-normativa', n.aggiornamento ? 'attesa' : !n.atti ? 'ko' : pct >= 100 ? 'ok' : 'attesa',
    n.aggiornamento ? 'Normativa: aggiornamento…' : !n.atti ? 'Normativa assente'
    : `Normativa · ${n.atti} atti${n.raccolta ? ` + ${n.raccolta.toLocaleString('it-IT')} in raccolta` : ''} · significato ${pct}%`);
  $('#stato-normativa').title = 'Testi ufficiali da Normattiva ed EUR-Lex. La percentuale indica quanta parte è già cercabile '
    + 'anche per significato (calcolo in background); la ricerca per parole e per numero di articolo funziona già su tutto.';
  const ok = stato.tempi.map((t) => t.tempi);
  $('#stato-media span').textContent = `media ${sec(media(ok.map((t) => t.totale_ms)))} · prima parola ${sec(media(ok.map((t) => t.prima_parola_ms).filter((x) => x != null)))}`;
  const manca = (s.missing_models || []).length;
  $('#punto-chat').className = 'punto ' + (!s.ollama ? 'ko' : manca ? 'attesa' : 'ok');
  $('#sotto-chat').textContent = !s.ollama ? 'Ollama non raggiungibile: avvialo e ricarica la pagina'
    : manca ? `Modelli mancanti: ${s.missing_models.join(', ')} (ollama pull)`
    : stato.modalita === 'rag' ? `${s.chat_model} · sui documenti · ${stato.approfondita ? `${s.top_k_deep} brani (approfondita)` : `${s.top_k} brani`} per domanda`
    : stato.modalita === 'norm' ? `${s.chat_model} · sui testi di legge · ${stato.approfondita ? `${s.top_k_deep} articoli (approfondita)` : `${s.top_k} articoli`} per domanda`
    : `${s.chat_model} · sui testi di legge, con ipotesi · ${s.top_k} articoli per domanda`;
}

$('#approfondita').addEventListener('click', () => {
  stato.approfondita = !stato.approfondita;
  $('#approfondita').classList.toggle('attiva', stato.approfondita);
  disegnaStato();
});

$('#modello').addEventListener('change', async (e) => {
  try {
    await postJson('/model', { model: e.target.value });
    stato.server.chat_model = e.target.value;
    disegnaStato();
    sistema(`Modello cambiato in ${e.target.value}: la prima risposta sarà più lenta (caricamento in memoria).`);
  } catch (err) { sistema('Errore: ' + err.message); }
});

$('#fascicolo').addEventListener('change', (e) => cambiaFascicolo(Number(e.target.value)));
async function cambiaFascicolo(id) {
  if (stato.occupato) { $('#fascicolo').value = stato.fascicolo; return sistema('Attendi la fine della risposta prima di cambiare fascicolo.'); }
  stato.fascicolo = id;
  salvaFascicolo(id);
  stato.aperte.clear();
  nuovaConversazione();
  await aggiornaTutto();
}

$('#cerca-documenti').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.value.trim()) apri(`scheda.html?q=${encodeURIComponent(e.target.value.trim())}`);
});

// mentre il modello scrive si apre una nuova scheda: lasciare la pagina interromperebbe la risposta
const apri = (url) => (stato.occupato ? window.open(url, '_blank') : (location.href = url));
document.querySelectorAll('.accessi a').forEach((a) => a.addEventListener('click', (e) => {
  if (stato.occupato) { e.preventDefault(); window.open(a.getAttribute('href'), '_blank'); }
}));

// ------------------------------------------------------- fascicoli (modale)
function modaleFascicolo(fascicolo = null) {
  const velo = document.createElement('div');
  velo.className = 'velo-modale';
  velo.innerHTML = `<form class="modale">
    <h2>${fascicolo ? 'Modifica fascicolo' : 'Nuovo fascicolo'}</h2>
    <label class="campo"><span>Nome del fascicolo</span><input name="name" required value="${esc(fascicolo?.name)}" placeholder="es. Rossi c. Bianchi – sfratto"></label>
    <label class="campo"><span>Cliente</span><input name="client" value="${esc(fascicolo?.client)}"></label>
    <label class="campo"><span>Note</span><textarea name="notes" rows="3">${esc(fascicolo?.notes)}</textarea></label>
    <div class="errore" style="color:var(--errore);font-size:12px" data-errore></div>
    <div class="azioni-modale"><button type="button" class="btn-piccolo grigio" data-annulla>Annulla</button>
      <button class="btn-piccolo">${fascicolo ? 'Salva' : 'Crea fascicolo'}</button></div></form>`;
  document.body.appendChild(velo);
  const form = $('form', velo);
  form.name.focus();
  const chiudi = () => velo.remove();
  $('[data-annulla]', velo).addEventListener('click', chiudi);
  velo.addEventListener('click', (e) => { if (e.target === velo) chiudi(); });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const dati = Object.fromEntries(new FormData(form));
    try {
      if (fascicolo) {
        await postJson(`/cases/${fascicolo.id}`, dati, 'PUT');
        await aggiornaTutto();
      } else {
        const r = await postJson('/cases', dati);
        chiudi();
        return cambiaFascicolo(r.id);
      }
      chiudi();
    } catch (err) { $('[data-errore]', velo).textContent = err.message; }
  });
}
$('#nuovo-fascicolo').addEventListener('click', () => modaleFascicolo());

// ------------------------------------------------------ pannello sinistro
const TITOLI = { storico: 'Storico', fascicoli: 'Fascicoli', documenti: 'Documenti', leggi: 'Testi di legge', tempi: 'Tempi di risposta' };
document.querySelectorAll('.icona-scheda').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.icona-scheda').forEach((x) => x.classList.toggle('attiva', x === b));
  stato.scheda = b.dataset.scheda;
  $('#filtro-sinistra').value = '';
  disegnaSinistra();
}));
$('#filtro-sinistra').addEventListener('input', disegnaSinistra);
$('#azione-sinistra').addEventListener('click', async () => {
  if (stato.scheda === 'fascicoli') modaleFascicolo();
  if (stato.scheda === 'documenti') $('#file').click();
  if (stato.scheda === 'leggi') {
    if (!confirm('Riscaricare tutti i testi di legge da Normattiva ed EUR-Lex nella versione vigente oggi?\n'
      + 'Richiede alcuni minuti; gli articoli rimasti uguali conservano la ricerca per significato già calcolata.')) return;
    try { await postJson('/normativa/aggiorna', {}); sistema('Aggiornamento dei testi di legge avviato.'); aggiornaTutto(); } catch (err) { sistema('Errore: ' + err.message); }
  }
});

function disegnaSinistra() {
  $('#titolo-sinistra').textContent = TITOLI[stato.scheda];
  const azione = { fascicoli: 'Nuovo', documenti: 'Aggiungi', leggi: 'Aggiorna' }[stato.scheda];
  $('#azione-sinistra').hidden = !azione;
  $('#azione-sinistra').textContent = azione || '';
  const filtro = $('#filtro-sinistra').value.trim().toLowerCase();
  ({ storico: disegnaStorico, fascicoli: disegnaFascicoli, documenti: disegnaDocumenti, leggi: disegnaLeggi, tempi: disegnaTempi })[stato.scheda]($('#lista-sinistra'), filtro);
}

function disegnaLeggi(lista, filtro) {
  const n = stato.normativa;
  const agg = n.aggiornamento || {};
  $('#conta-sinistra').textContent = agg.attivo ? `aggiorno ${agg.fatti}/${agg.totale} · ${agg.atto}` : `${n.atti.length} atti`;
  const voci = n.atti.filter((a) => !filtro || `${a.sigla} ${a.titolo} ${a.area}`.toLowerCase().includes(filtro));
  const dataBreve = (iso) => (iso ? iso.split('-').reverse().join('/') : '—');
  lista.innerHTML = (n.atti.length ? `<div class="sequenza"><h3>Fonti ufficiali</h3>
      Testi vigenti da <b>Normattiva</b> (Poligrafico dello Stato) ed <b>EUR-Lex</b> (Unione europea), riutilizzabili con licenza CC BY 4.0.
      La ricerca per numero di articolo e per parole funziona subito; quella per significato si completa in background.</div>` : '')
    + voci.map((a) => {
      const pct = a.parti ? Math.floor(a.indicizzate / a.parti * 100) : 0;
      return `<article class="voce" data-id="${a.id}">
        <div class="testa"><span>${esc(a.area)}</span><span>${esc(a.fonte)}</span></div>
        <div class="domanda">${esc(a.sigla)}</div>
        <div class="anteprima">${esc(a.titolo)}</div>
        <div class="piede"><span class="fila"><span class="etichetta bordeaux" title="vigente alla data dello scaricamento">al ${esc(dataBreve(a.vigente_al))}</span>
          <span class="etichetta" title="articoli · ricerca per significato">${a.articoli} art. · ${pct}%</span></span>
          <span class="fila"><a class="btn-piccolo grigio" href="${esc(a.url)}" target="_blank" rel="noopener" title="Testo ufficiale">${ICONE.apri}Fonte</a>
          <button class="btn-piccolo" data-chiedi-atto title="Fai domande solo su questo atto">Chiedi</button></span></div>
      </article>`;
    }).join('')
    || `<div class="vuoto">${filtro ? 'Nessun risultato.' : 'Archivio normativo vuoto: premi «Aggiorna» per scaricare i testi di legge dai siti ufficiali.'}</div>`;
}

const oraBreve = (t) => (t ? `${t.slice(8, 10)}/${t.slice(5, 7)} ${t.slice(11, 16)}` : '');

function disegnaStorico(lista, filtro) {
  const voci = stato.conversazioni.filter((c) => !filtro || `${c.title} ${c.ultima_risposta || ''}`.toLowerCase().includes(filtro));
  $('#conta-sinistra').textContent = `${stato.conversazioni.length} conversazioni`;
  lista.innerHTML = voci.map((c) => {
    const aperta = stato.aperte.has(c.id);
    const t = c.meta?.tempi;
    return `<article class="voce ${aperta || c.id === stato.conversazione ? 'aperta' : ''}" data-id="${c.id}">
      <div class="testa"><span>${esc(oraBreve(c.updated_at || c.created_at))}</span><span>${esc(c.meta?.modello || '')}</span></div>
      <div class="domanda" data-espandi>${esc(c.title)}</div>
      <div class="anteprima corpo" data-espandi>${aperta ? markdown(c.ultima_risposta || '') : esc(senzaMarkdown(c.ultima_risposta || ''))}</div>
      <div class="piede">
        <span class="fila"><span class="etichetta ${c.kind === 'chat' ? '' : 'bordeaux'}">${NOMI_MODALITA[c.kind] || c.kind}</span>
          <span class="etichetta" title="domande · tempo dell'ultima risposta">${c.domande} dom.${t ? ` · ${sec(t.totale_ms)}` : ''}</span></span>
        <span class="fila"><button class="btn-piccolo grigio" data-elimina title="Elimina la conversazione">Elimina</button>
        <button class="btn-piccolo" data-riprendi title="Riapri la conversazione nella chat e continua">${ICONE.apri}Riprendi</button></span>
      </div></article>`;
  }).join('') || `<div class="vuoto">${filtro ? 'Nessun risultato.' : 'Ancora nessuna conversazione in questo fascicolo.'}</div>`;
}

function disegnaFascicoli(lista, filtro) {
  const voci = stato.fascicoli.filter((f) => !filtro || `${f.name} ${f.client} ${f.notes}`.toLowerCase().includes(filtro));
  $('#conta-sinistra').textContent = `${stato.fascicoli.length} fascicoli`;
  lista.innerHTML = voci.map((f) => `
    <article class="voce ${f.id === stato.fascicolo ? 'aperta' : ''}" data-id="${f.id}">
      <div class="testa"><span>aperto ${esc(oraBreve(f.created_at).slice(0, 5))}</span><span>${f.id === stato.fascicolo ? 'in uso' : ''}</span></div>
      <div class="domanda" data-seleziona>${esc(f.name)}</div>
      <div class="anteprima">${f.client ? `Cliente: ${esc(f.client)}` : '<span style="color:var(--debole)">nessun cliente indicato</span>'}${f.notes ? `<br>${esc(f.notes)}` : ''}</div>
      <div class="piede">
        <span class="fila"><span class="etichetta bordeaux">${f.documents} doc.</span><span class="etichetta">${f.conversations} conv.</span></span>
        <span class="fila"><button class="btn-piccolo grigio" data-modifica>Modifica</button>
          <button class="btn-piccolo grigio" data-elimina-fascicolo>Elimina</button>
          ${f.id === stato.fascicolo ? '' : `<button class="btn-piccolo" data-seleziona>${ICONE.apri}Apri</button>`}</span>
      </div></article>`).join('') || '<div class="vuoto">Nessun fascicolo.</div>';
}

const ETICHETTA_ESTRAZIONE = { fatto: '', 'in attesa': 'dati: in coda', 'in corso': 'dati: in estrazione', errore: 'dati: errore', 'non eseguita': 'dati: da avviare' };

function disegnaDocumenti(lista, filtro) {
  const info = Object.fromEntries(stato.infoDocumenti.map((d) => [d.id, d]));
  const voci = stato.documenti.filter((d) => !filtro || `${d.filename} ${info[d.id]?.tipo || ''}`.toLowerCase().includes(filtro));
  $('#conta-sinistra').textContent = `${stato.documenti.length} documenti`;
  lista.innerHTML = voci.map((d) => {
    const i = info[d.id] || {};
    const statoDati = ETICHETTA_ESTRAZIONE[d.estrazione] ?? '';
    const dettagli = [i.autorita, ...(i.numeri_ruolo || []).map((n) => `R.G. ${n}`)].filter(Boolean).join(' · ');
    return `<article class="voce" data-id="${d.id}">
      <div class="testa"><span>${esc(oraBreve(d.created_at))}</span><span>
        ${d.warning.includes('pochissimo testo') ? `<span class="etichetta errore" title="${esc(d.warning)}">⚠ senza testo</span> ` : ''}
        ${d.warning.includes('riconosciuto con OCR') ? `<span class="etichetta attenzione" title="${esc(d.warning)}">⚠ letto con OCR</span> ` : ''}
        ${d.warning.includes('istruzioni') ? `<span class="etichetta sospetto" title="${esc(d.warning)}">⚠ istruzioni sospette</span> ` : ''}
        ${statoDati ? `<span class="etichetta ${d.estrazione === 'errore' ? 'errore' : 'attenzione'}" title="${esc(i.errore || '')}">${statoDati}</span> ` : ''}
        ${i.tipo ? `<span class="etichetta bordeaux">${esc(i.tipo)}</span>` : ''}</span></div>
      <div class="domanda" data-documento>${esc(d.filename)}</div>
      ${dettagli ? `<div class="anteprima">${esc(dettagli)}</div>` : ''}
      <div class="piede"><span class="etichetta">${d.pages ? `${d.pages} pag. · ` : ''}${d.chars} caratteri</span>
        <span class="fila"><button class="btn-piccolo grigio" data-rimuovi>${ICONE.x}Rimuovi</button>
          <button class="btn-piccolo grigio" data-riassumi title="Riassunto strutturato del documento">Riassumi</button>
          <button class="btn-piccolo" data-documento>${ICONE.apri}Apri</button></span></div>
    </article>`;
  }).join('') || `<div class="vuoto">${filtro ? 'Nessun risultato.' : 'Nessun documento: aggiungili con + nella chat o trascinali qui.'}</div>`;
}

function disegnaTempi(lista, filtro) {
  const ok = stato.tempi;
  $('#conta-sinistra').textContent = `${ok.length} risposte`;
  const tot = ok.map((v) => v.tempi.totale_ms);
  const pp = ok.map((v) => v.tempi.prima_parola_ms).filter((x) => x != null);
  const ultimo = ok[ok.length - 1];
  const perModello = {};
  ok.forEach((v) => (perModello[v.modello] ||= []).push(v));
  const righeModelli = Object.entries(perModello).map(([m, vv]) => {
    const ts = vv.map((v) => v.tempi.tok_s).filter(Boolean);
    return `<tr><td>${esc(m)}</td><td class="num">${vv.length}</td><td class="num">${sec(media(vv.map((v) => v.tempi.totale_ms)))}</td>
      <td class="num">${sec(media(vv.map((v) => v.tempi.prima_parola_ms).filter((x) => x != null)))}</td><td class="num">${ts.length ? media(ts).toFixed(0) : '—'}</td></tr>`;
  }).join('');
  const max = Math.max(1, ...tot);
  const voci = ok.filter((v) => !filtro || v.domanda.toLowerCase().includes(filtro) || v.modello.toLowerCase().includes(filtro)).reverse();
  lista.innerHTML = `
    <div class="kpi">
      <div class="evidenza"><b>${sec(media(tot))}</b><span>tempo medio di risposta</span></div>
      <div><b>${sec(media(pp))}</b><span>media alla prima parola</span></div>
      <div><b>${sec(ultimo?.tempi.totale_ms)}</b><span>ultima risposta</span></div>
      <div><b>${tot.length ? sec(Math.min(...tot)) : '—'}</b><span>la più veloce</span></div>
    </div>
    ${righeModelli ? `<div class="sequenza"><h3>Confronto modelli</h3><table class="modelli">
      <tr><th>Modello</th><th class="num">N</th><th class="num">Medio</th><th class="num">1ª parola</th><th class="num">tok/s</th></tr>${righeModelli}</table></div>` : ''}
    <div class="legenda"><span><i style="background:var(--debole)"></i>ricerca</span><span><i style="background:var(--tenue)"></i>attesa prima parola</span><span><i style="background:var(--testo)"></i>generazione</span></div>
    ${voci.map((v) => {
      const t = v.tempi, r = t.ricerca_ms || 0, p = Math.max(0, (t.prima_parola_ms ?? t.totale_ms) - r), g = Math.max(0, t.totale_ms - r - p);
      const w = (x) => (x / max * 100).toFixed(1) + '%';
      return `<div class="riga-tempo" title="${esc(v.domanda)}">
        <span class="q">${esc(v.domanda)}</span><span class="t">${sec(t.totale_ms)}</span>
        <div class="barra"><i class="ricerca" style="width:${w(r)}"></i><i class="attesa" style="width:${w(p)}"></i><i class="gen" style="width:${w(g)}"></i></div>
        <span class="dett">${esc(v.modello)} · ricerca ${r} ms · 1ª parola ${sec(t.prima_parola_ms)}${t.tok_s ? ` · ${t.tok_s} tok/s` : ''} · ${esc(oraBreve(v.ora))}</span>
      </div>`;
    }).join('') || '<div class="vuoto">Nessuna risposta da misurare.</div>'}`;
}

$('#lista-sinistra').addEventListener('click', async (e) => {
  const voce = e.target.closest('.voce');
  if (!voce) return;
  const id = Number(voce.dataset.id);
  try {
    if (stato.scheda === 'storico') {
      const c = stato.conversazioni.find((x) => x.id === id);
      if (e.target.closest('[data-riprendi]')) return caricaConversazione(id);
      if (e.target.closest('[data-elimina]')) {
        if (!confirm(`Eliminare la conversazione «${c.title}»? Non si può annullare.`)) return;
        await api(`/conversations/${id}`, { method: 'DELETE' });
        if (stato.conversazione === id) nuovaConversazione();
        return aggiornaTutto();
      }
      if (e.target.closest('[data-espandi]')) {
        stato.aperte.has(id) ? stato.aperte.delete(id) : stato.aperte.add(id);
        disegnaSinistra();
      }
    } else if (stato.scheda === 'fascicoli') {
      const f = stato.fascicoli.find((x) => x.id === id);
      if (e.target.closest('[data-modifica]')) return modaleFascicolo(f);
      if (e.target.closest('[data-elimina-fascicolo]')) {
        if (stato.occupato) return sistema('Attendi la fine della risposta prima di eliminare un fascicolo.');
        if (!confirm(`Eliminare il fascicolo «${f.name}» con i suoi ${f.documents} documenti e ${f.conversations} conversazioni? Non si può annullare.\n\nI testi di legge restano nell'archivio.`)) return;
        await api(`/cases/${id}`, { method: 'DELETE' });
        if (id === stato.fascicolo) { stato.fascicolo = null; nuovaConversazione(); }
        return aggiornaTutto();
      }
      if (e.target.closest('[data-seleziona]') && id !== stato.fascicolo) return cambiaFascicolo(id);
    } else if (stato.scheda === 'leggi') {
      if (e.target.closest('[data-chiedi-atto]')) {
        if (stato.occupato) return;
        if (stato.modalita !== 'norm') { impostaModalita('norm'); nuovaConversazione(); }
        $('#ambito').value = String(id);
        $('#domanda').focus();
      }
    } else if (stato.scheda === 'documenti') {
      if (e.target.closest('[data-rimuovi]')) return rimuoviDocumento(voce, id);
      if (e.target.closest('[data-riassumi]')) return apri(`strumenti.html?t=riassunto&doc=${id}`);
      if (e.target.closest('[data-documento]')) return apri(`scheda.html?doc=${id}`);
    }
  } catch (err) { sistema('Errore: ' + err.message); }
});

async function rimuoviDocumento(voce, id) {
  const d = stato.documenti.find((x) => x.id === id);
  if (!confirm(`Togliere «${d.filename}» dal fascicolo? Il file e i dati estratti vengono cancellati.`)) return;
  voce.classList.add('in-corso');
  try {
    await api(`/documents/${id}`, { method: 'DELETE' });
    sistema(`Rimosso ${d.filename}.`);
    await aggiornaTutto();
  } catch (err) {
    voce.classList.remove('in-corso');
    sistema('Errore nella rimozione: ' + err.message);
  }
}

// ------------------------------------------------------- pannello destro
const COLORI = ['#7b1e34', '#5c5c66', '#97304a', '#45454d', '#6b2537', '#73737d'];
const colore = (n) => COLORI[[...n].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORI.length];
const iniziali = (n) => n.split(/\s+/).filter((p) => /^[A-ZÀ-Ý]/i.test(p) && !/^(sig|sig\.ra|dott|avv|s\.r\.l|s\.p\.a)/i.test(p))
  .map((p) => p[0]).slice(0, 2).join('').toUpperCase() || n[0].toUpperCase();
const oggi = new Date().toISOString().slice(0, 10);
const daVerificare = '<span class="etichetta attenzione" title="Il valore non compare alla lettera nel documento">da verificare</span>';

function voceParte(p) {
  const docs = new Set(p.fonti.map((f) => f.document_id)).size;
  return `<button class="persona-voce" data-cerca="${esc(p.nome)}" title="Passaggi dei documenti in cui compare ${esc(p.nome)}">
      <span class="iniziali" style="background:${colore(p.nome)}">${esc(iniziali(p.nome))}</span>
      <span class="info"><b>${esc(p.nome)}</b>
        <span class="ruoli">${p.verificato ? esc(p.ruoli.join(' · ') || '—') : daVerificare}</span></span>
      <span class="numero" title="documenti in cui compare">${docs}</span>
    </button>`;
}

function voceElemento(tipo, e) {
  const passata = e.data_iso && e.data_iso < oggi;
  const quando = tipo !== 'importi' && e.data_iso ? `<span class="numero data ${passata ? 'passata' : ''}" title="${passata ? 'data passata' : 'data futura'}">${esc(dataIt(e.data_iso))}</span>`
    : `<span class="numero data" title="pagina">${esc(pagina(e.pagina))}</span>`;
  return `<button class="persona-voce" data-cerca="${esc(e.valore)}" title="${esc(e.filename)} · ${esc(pagina(e.pagina))}">
      <span class="icona-tipo">${ICONE[tipo]}</span>
      <span class="info"><b>${esc(e.valore)}</b>
        <span class="estratto">${e.verificato ? '' : daVerificare + ' '}${esc(e.dettaglio)} <span class="etichetta">${esc(e.filename)}</span></span></span>
      ${quando}
    </button>`;
}

function disegnaElementi() {
  const tipo = stato.tipoDestra;
  const filtro = $('#filtro-elementi').value.trim().toLowerCase();
  document.querySelectorAll('#schede-elementi button').forEach((b) => {
    b.classList.toggle('attiva', b.dataset.tipo === tipo);
    b.querySelector('span').textContent = stato.elementi[b.dataset.tipo]?.length || '';
  });
  const tutte = stato.elementi[tipo] || [];
  const testo = (e) => (tipo === 'parti' ? `${e.nome} ${e.ruoli.join(' ')}` : `${e.valore} ${e.dettaglio} ${e.filename}`).toLowerCase();
  const voci = tutte.filter((e) => !filtro || testo(e).includes(filtro));
  $('#conta-elementi').textContent = Object.values(stato.elementi).reduce((a, l) => a + l.length, 0) + ' totali';
  $('#lista-elementi').innerHTML = voci.map((e) => (tipo === 'parti' ? voceParte(e) : voceElemento(tipo, e))).join('')
    || `<div class="vuoto">${filtro ? 'Nessun risultato.' : `${NOMI_TIPO[tipo]} dei documenti compariranno qui dopo l'estrazione automatica.`}</div>`;
  const inCorso = stato.documenti.filter((d) => d.estrazione === 'in attesa' || d.estrazione === 'in corso').length;
  $('#stato-estrazione').textContent = inCorso ? `Estrazione dati in corso: ${inCorso} document${inCorso === 1 ? 'o' : 'i'}…` : '';
}
document.querySelectorAll('#schede-elementi button').forEach((b) => b.addEventListener('click', () => {
  stato.tipoDestra = b.dataset.tipo;
  $('#filtro-elementi').value = '';
  disegnaElementi();
}));
$('#filtro-elementi').addEventListener('input', disegnaElementi);
$('#lista-elementi').addEventListener('click', (e) => {
  const b = e.target.closest('[data-cerca]');
  if (b) apri(`scheda.html?q=${encodeURIComponent(b.dataset.cerca)}`);
});

// ------------------------------------------------------------------ chat
const messaggi = $('#messaggi');
const PROVE = {
  rag: ['Chi sono le parti e con quale ruolo?', 'Quali scadenze e termini sono previsti?', 'Quali sono gli obblighi principali?'],
  norm: ['Cosa prevede l\'art. 1385 c.c.?', 'Qual è la durata minima di una locazione abitativa?', 'Entro quanto si impugna un licenziamento?'],
};
const CHIAVE_CONV = 'law-conversazione';
const INVIO = '  (Invio per inviare, Maiusc+Invio per andare a capo)';

function benvenuto() {
  const prove = (PROVE[stato.modalita] || []).map((p) => `<button class="chip" data-prova>${esc(p)}</button>`).join('');
  messaggi.innerHTML = {
    rag: `<div class="benvenuto"><h2>Pronto a esaminare il fascicolo</h2>
      <p>Rispondo solo in base ai documenti del fascicolo e cito le fonti. Con <b>+</b> aggiungi atti e documenti.</p><div>${prove}</div></div>`,
    norm: `<div class="benvenuto"><h2>Consulta la legge</h2>
      <p>Rispondo con il testo ufficiale vigente di codici e leggi (Normattiva, EUR-Lex) e cito gli articoli.
      Puoi chiedere un articolo preciso, ad esempio «art. 1454 c.c.».</p><div>${prove}</div></div>`,
    chat: `<div class="benvenuto"><h2>Chat libera</h2>
      <p>Chiedi qualunque questione giuridica, anche ipotetica. Parto dai testi di legge in archivio e, se non bastano,
      ragiono per ipotesi, dichiarandole come tali. Non uso i documenti dei fascicoli.</p></div>`,
  }[stato.modalita];
}

function disegnaAmbito() {
  const sel = $('#ambito');
  const scelto = sel.dataset.modalita === stato.modalita ? sel.value : '';
  if (stato.modalita === 'norm') {
    const perArea = {};
    stato.normativa.atti.forEach((a) => (perArea[a.area] ||= []).push(a));
    sel.innerHTML = '<option value="">Tutta la normativa</option>' + Object.entries(perArea).map(([area, atti]) =>
      `<optgroup label="${esc(area)}">${atti.map((a) => `<option value="${a.id}" ${String(a.id) === scelto ? 'selected' : ''}>${esc(a.sigla)}</option>`).join('')}</optgroup>`).join('');
  } else {
    sel.innerHTML = '<option value="">Tutti i documenti</option>'
      + stato.documenti.map((d) => `<option value="${d.id}" ${String(d.id) === scelto ? 'selected' : ''}>${esc(d.filename)}</option>`).join('');
  }
  sel.dataset.modalita = stato.modalita;
  sel.title = stato.modalita === 'norm' ? 'In quali leggi cercare' : 'In quali documenti cercare';
  // in chat libera non servono: restano al loro posto ma invisibili, così la barra non si sposta
  sel.classList.toggle('invisibile', stato.modalita === 'chat');
  $('#riquadro-approfondita').classList.toggle('invisibile', stato.modalita === 'chat');
}

function impostaModalita(m) {
  stato.modalita = m;
  document.querySelectorAll('.modalita button[data-modalita]').forEach((b) => b.classList.toggle('attiva', b.dataset.modalita === m));
  $('#avviso-libera').hidden = m !== 'chat';
  $('#domanda').placeholder = { rag: 'Chiedi sui documenti del fascicolo…', norm: 'Chiedi alla legge, es. «art. 1454 c.c.» o «termine per l\'appello»…',
    chat: 'Domanda generale di diritto…' }[m] + INVIO;
  disegnaAmbito();
  disegnaStato();
}
document.querySelectorAll('.modalita button[data-modalita]').forEach((b) => b.addEventListener('click', () => {
  if (stato.occupato || b.dataset.modalita === stato.modalita) return;
  impostaModalita(b.dataset.modalita);
  nuovaConversazione();
}));

function nuovaConversazione() {
  stato.conversazione = null;
  try { sessionStorage.removeItem(CHIAVE_CONV); } catch { /* memoria non disponibile */ }
  benvenuto();
  if (stato.scheda === 'storico') disegnaSinistra();
}
$('#nuova').addEventListener('click', () => { if (!stato.occupato) nuovaConversazione(); });

messaggi.addEventListener('click', (e) => {
  const prova = e.target.closest('[data-prova]');
  if (prova) return chiedi(prova.textContent);
  const norma = e.target.closest('[data-norma]');
  if (norma) return apri(`scheda.html?norma=${norma.dataset.norma}`);
  const fonte = e.target.closest('[data-doc]');
  if (fonte) apri(`scheda.html?doc=${fonte.dataset.doc}${fonte.dataset.pagina ? `&p=${fonte.dataset.pagina}` : ''}`);
});

function scorri() { messaggi.scrollTop = messaggi.scrollHeight; }
const ora = () => new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });

function sistema(testo) {
  $('.benvenuto', messaggi)?.remove();
  messaggi.insertAdjacentHTML('beforeend', `<div class="msg sistema">${esc(testo)}</div>`);
  scorri();
}

// Una fonte è un brano di documento del fascicolo oppure un articolo di legge (norma_id).
const etichettaFonte = (f) => (f.norma_id ? f.etichetta : `${f.filename} · ${pagina(f.page)}`);
const attributiFonte = (f) => (f.norma_id ? `data-norma="${f.norma_id}"` : `data-doc="${f.document_id}" data-pagina="${f.page ?? ''}"`);

// testo del modello -> HTML: Markdown (comune.js) e citazioni [1] [2] cliccabili verso il documento o l'articolo
function formatta(testo, fonti = []) {
  return markdown(testo).replace(/\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\]/g, (m, interno) => interno.split(/[,;]\s*/).map((n) => {
    const f = fonti.find((x) => x.n === Number(n));
    return f ? `<span class="cit" ${attributiFonte(f)} title="${esc(etichettaFonte(f))}">${n}</span>` : `[${esc(n)}]`;
  }).join(' '));
}

function aggiungiUtente(testo, orario = ora()) {
  $('.benvenuto', messaggi)?.remove();
  messaggi.insertAdjacentHTML('beforeend', `<div class="msg utente"><span class="ora">${esc(orario)}</span>${esc(testo)}</div>`);
}

function nuovaRisposta(orario = ora()) {
  const el = document.createElement('div');
  el.className = 'msg modello';
  el.innerHTML = `<span class="ora">${esc(orario)}</span><div class="chi"><span class="avatar" style="width:30px;height:30px">
    ${ICONE.logo.replace('<svg', '<svg style="width:17px;height:17px"')}</span>Assistente</div>
    <div class="corpo cursore"></div><div class="extra"><div class="fila stato-ricerca">${{ rag: 'cerco nei documenti…', norm: 'cerco nella normativa…', chat: 'cerco nella normativa…' }[stato.modalita]}</div></div>`;
  messaggi.appendChild(el);
  scorri();
  return el;
}

// Il testo ufficiale sotto la risposta: il modello può sbagliare, l'avvocato deve poter confrontare subito.
// Aperti gli articoli citati nella risposta (o il primo, se non ne cita nessuno); gli altri restano chiusi.
function testiUfficiali(fonti, testo) {
  const norme = fonti.filter((f) => f.norma_id && f.text);
  if (!norme.length) return '';
  const citata = (f) => new RegExp(`\\[[^\\]]*\\b${f.n}\\b[^\\]]*\\]`).test(testo);
  const nessunaCitata = !norme.some(citata);
  return `<div class="testi-ufficiali"><div class="titolo-testi">Testo ufficiale: controlla qui la risposta</div>
    ${norme.map((f, i) => `<details class="testo-norma" ${citata(f) || (nessunaCitata && i === 0) ? 'open' : ''}>
      <summary><b>${f.n}</b> ${esc(f.etichetta)}${f.rubrica ? ` – ${esc(f.rubrica)}` : ''}</summary>
      <div class="testo-articolo">${esc(f.text)}</div>
      <div class="fila">${f.parziale ? '<span class="etichetta attenzione">solo una parte dell\'articolo</span>' : ''}
        <span class="chip" data-norma="${f.norma_id}">${ICONE.file} Apri l'articolo intero</span></div></details>`).join('')}</div>`;
}

function completaRisposta(el, { testo, fonti = [], meta = {}, errore = null }) {
  const corpo = $('.corpo', el);
  corpo.classList.remove('cursore');
  corpo.innerHTML = formatta(testo, fonti) || '<span style="color:var(--debole)">(nessun testo)</span>';
  const t = meta.tempi;
  el.querySelector('.extra').innerHTML = `
    ${errore ? `<div class="errore">${esc(errore)}</div>` : ''}
    ${testiUfficiali(fonti, testo)}
    ${fonti.length ? `<div class="fila">Fonti:${fonti.map((f) => `<span class="chip${f.sospetto ? ' sospetto' : ''}" ${attributiFonte(f)}
      title="${esc((f.sospetto ? 'ATTENZIONE: questo passaggio contiene istruzioni rivolte all\'assistente (possibile manipolazione). L\'assistente le tratta come semplice testo.\n\n' : '')
        + ((f.rubrica ? f.rubrica + '\n' : '') + (f.text || '')).slice(0, 400))}">${f.sospetto ? '⚠' : ICONE.file}<b>${f.n}</b> ${esc(etichettaFonte(f))}</span>`).join('')}</div>` : ''}
    ${fonti.some((f) => f.norma_id) ? `<div class="fila">Testo vigente al ${esc((fonti.find((f) => f.vigente_al)?.vigente_al || '').split('-').reverse().join('/'))} · fonte ufficiale: ${esc([...new Set(fonti.map((f) => f.fonte).filter(Boolean))].join(', '))}</div>` : ''}
    ${t ? `<div class="tempi-msg">prima parola <b>${sec(t.prima_parola_ms)}</b> · totale <b>${sec(t.totale_ms)}</b>${t.ricerca_ms ? ` · ricerca ${t.ricerca_ms} ms` : ''}${t.tok_s ? ` · ${t.tok_s} tok/s` : ''} · ${esc(meta.modello)}</div>` : ''}`;
  scorri();
}

async function chiedi(domanda) {
  domanda = domanda.trim();
  if (!domanda || stato.occupato) return;
  stato.occupato = true;
  $('#invia').disabled = true;
  aggiungiUtente(domanda);
  const el = nuovaRisposta();
  const corpo = $('.corpo', el);
  const risposta = { testo: '', fonti: [], meta: {} };
  const ambito = Number($('#ambito').value) || null;
  const [percorso, corpoRichiesta] = {
    rag: ['/ask', { question: domanda, case_id: stato.fascicolo, conversation_id: stato.conversazione,
      document_ids: ambito ? [ambito] : null, deep: stato.approfondita }],
    norm: ['/ask-normativa', { question: domanda, case_id: stato.fascicolo, conversation_id: stato.conversazione,
      atti: ambito ? [ambito] : null, deep: stato.approfondita }],
    chat: ['/chat', { message: domanda, case_id: stato.fascicolo, conversation_id: stato.conversazione }],
  }[stato.modalita];
  try {
    await flusso(percorso, corpoRichiesta, (ev) => {
      if (ev.type === 'conversation') {
        stato.conversazione = ev.id;
        try { sessionStorage.setItem(CHIAVE_CONV, String(ev.id)); } catch { /* memoria non disponibile */ }
      } else if (ev.type === 'sources') {
        risposta.fonti = ev.sources;
        const cosa = stato.modalita === 'rag' ? ['brani trovati', 'nessun documento indicizzato'] : ['articoli trovati', 'nessun articolo trovato'];
        $('.stato-ricerca', el).textContent = ev.sources.length ? `${ev.sources.length} ${cosa[0]} · scrivo la risposta…` : cosa[1];
      } else if (ev.type === 'token') {
        risposta.testo += ev.text;
        corpo.innerHTML = formatta(risposta.testo, risposta.fonti);
        scorri();
      } else if (ev.type === 'meta') {
        risposta.meta = ev;
      }
    });
  } catch (err) {
    risposta.errore = err.message;
  } finally {
    completaRisposta(el, risposta);
    stato.occupato = false;
    $('#invia').disabled = false;
    aggiornaTutto().catch(() => {});
  }
}

async function caricaConversazione(id) {
  if (stato.occupato) return;
  const c = await api(`/conversations/${id}`);
  impostaModalita(c.kind);
  stato.conversazione = c.id;
  try { sessionStorage.setItem(CHIAVE_CONV, String(c.id)); } catch { /* memoria non disponibile */ }
  messaggi.innerHTML = '';
  for (const m of c.messages) {
    const orario = (m.created_at || '').slice(11, 16);
    if (m.role === 'user') aggiungiUtente(m.content, orario);
    else completaRisposta(nuovaRisposta(orario), { testo: m.content, fonti: m.sources, meta: m.meta });
  }
  if (!c.messages.length) benvenuto();
  if (stato.scheda === 'storico') disegnaSinistra();
}

const area = $('#domanda');
function invia() { const t = area.value; area.value = ''; adatta(); chiedi(t); }
function adatta() { area.style.height = 'auto'; area.style.height = Math.min(area.scrollHeight, 140) + 'px'; }
area.addEventListener('input', adatta);
area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); invia(); } });
$('#invia').addEventListener('click', invia);

// ------------------------------------------------------------- file (+)
$('#piu').addEventListener('click', () => $('#file').click());
$('#file').addEventListener('change', (e) => { carica([...e.target.files]); e.target.value = ''; });
$('#piu-cartella').addEventListener('click', () => $('#cartella').click());
$('#cartella').addEventListener('change', (e) => { carica([...e.target.files]); e.target.value = ''; });

async function carica(files) {
  const buoni = files.filter((f) => estensioneOk(f.name));
  if (files.length > buoni.length) sistema(`${files.length - buoni.length} file saltati: formati ammessi PDF, Word (.docx), testo (.txt, .md).`);
  const fascicolo = stato.fascicolo;
  for (const f of buoni) {
    const chip = document.createElement('span');
    chip.className = 'file-chip carico';
    chip.innerHTML = `${ICONE.file}<span>${esc(f.name)} · carico…</span>`;
    $('#file-in-esame').appendChild(chip);
    const dati = new FormData();
    dati.append('file', f);
    try {
      let esito = null;
      await flusso(`/cases/${fascicolo}/documents`, null, (ev) => {
        if (ev.type === 'status') $('span', chip).textContent = ev.text;
        if (ev.type === 'result') esito = ev;
      }, { body: dati });
      chip.remove();
      sistema(`Aggiunto ${f.name}: ${esito.chunks} frammenti indicizzati. `
        + (esito.estrazione_avviata ? 'Estrazione di parti, date e importi in corso.'
          : 'Documento lungo: per estrarre parti, date e scadenze usa Strumenti › Dati chiave.')
        + (esito.warning ? `\n⚠ ${esito.warning}` : ''));
    } catch (err) {
      chip.remove();
      sistema(`${f.name}: ${err.message}`);
    }
    aggiornaTutto().catch(() => {});
  }
}

// trascina e rilascia sulla chat (anche cartelle intere)
async function fileTrascinati(dt) {
  const entrate = [...dt.items].map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  if (!entrate.some((e) => e.isDirectory)) return [...dt.files];
  const file = [];
  const leggiTutte = (lettore) => new Promise((ok, ko) => {
    const tutte = [];
    const giro = () => lettore.readEntries((parte) => { if (!parte.length) return ok(tutte); tutte.push(...parte); giro(); }, ko);
    giro();
  });
  async function visita(e) {
    if (e.isFile) file.push(await new Promise((ok, ko) => e.file(ok, ko)));
    else if (e.isDirectory) for (const figlio of await leggiTutte(e.createReader())) await visita(figlio);
  }
  for (const e of entrate) await visita(e);
  return file;
}
const zona = $('#zona-chat');
let profondita = 0;
zona.addEventListener('dragenter', (e) => { if ([...e.dataTransfer.types].includes('Files')) { profondita++; $('#trascina').classList.remove('nascosto'); } });
zona.addEventListener('dragleave', () => { if (--profondita <= 0) { profondita = 0; $('#trascina').classList.add('nascosto'); } });
zona.addEventListener('dragover', (e) => e.preventDefault());
zona.addEventListener('drop', async (e) => {
  e.preventDefault(); profondita = 0; $('#trascina').classList.add('nascosto');
  carica(await fileTrascinati(e.dataTransfer).catch(() => [...e.dataTransfer.files]));
});

// ---------------------------------------------------------------- avvio
benvenuto();
aggiornaTutto().then(() => {
  // tornando da un'altra pagina si ritrova la conversazione aperta
  let id = null;
  try { id = Number(sessionStorage.getItem(CHIAVE_CONV)) || null; } catch { /* memoria non disponibile */ }
  if (id && stato.conversazioni.some((c) => c.id === id)) caricaConversazione(id);
}).catch((err) => sistema('Server non raggiungibile: ' + err.message));

setInterval(() => {
  if (stato.occupato) return;
  api('/status').then((s) => { stato.server = s; disegnaStato(); }).catch(() => {});
  // le estrazioni in background aggiornano la colonna di destra man mano che finiscono
  if (stato.documenti.some((d) => d.estrazione === 'in attesa' || d.estrazione === 'in corso')) aggiornaElementi().catch(() => {});
}, 5000);
