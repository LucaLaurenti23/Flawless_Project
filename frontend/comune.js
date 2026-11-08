// Flawless Project - funzioni condivise da tutte le pagine (chat, scheda, strumenti, scadenze).
// Nessuna libreria esterna. Va caricato prima degli script delle pagine.
const $ = (s, r = document) => r.querySelector(s);
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reEsc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// ------------------------------------------------------------- navigazione
// Le schede si aprono nella stessa finestra; le frecce in alto a sinistra tornano indietro o vanno avanti
// tra le pagine viste (come quelle del browser, utili quando l'app è aperta senza la barra del browser).
const vaiA = (url) => { location.href = url; };

function frecceNavigazione() {
  const riga = $('.riga-alta');
  if (!riga || $('.frecce', riga)) return;
  riga.insertAdjacentHTML('afterbegin', `<div class="frecce">
    <button class="tema-btn" data-verso="-1" title="Indietro (pagina precedente)" aria-label="Indietro"><svg viewBox="0 0 24 24"><path d="M15 18 9 12l6-6"/></svg></button>
    <button class="tema-btn" data-verso="1" title="Avanti (pagina successiva)" aria-label="Avanti"><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button></div>`);
  const [indietro, avanti] = riga.querySelectorAll('.frecce button');
  indietro.addEventListener('click', () => history.back());
  avanti.addEventListener('click', () => history.forward());
  const aggiorna = () => {   // la Navigation API dice se c'è una pagina prima/dopo; senza, si lasciano attive
    const nav = window.navigation;
    indietro.disabled = nav ? !nav.canGoBack : history.length < 2;
    avanti.disabled = nav ? !nav.canGoForward : false;
  };
  aggiorna();
  window.navigation?.addEventListener('currententrychange', aggiorna);
  addEventListener('pageshow', aggiorna);
}
frecceNavigazione();

// --------------------------------------------------------- API e fascicolo
async function api(percorso, opzioni) {
  const r = await fetch('/api' + percorso, opzioni);
  const dati = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dati.detail || r.statusText);
  return dati;
}
const postJson = (percorso, corpo, metodo = 'POST') => api(percorso, {
  method: metodo, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });

// Legge una risposta in streaming del server: un evento JSON per riga.
async function flusso(percorso, corpo, suEvento, opzioni = {}) {
  const r = await fetch('/api' + percorso, opzioni.body ? { method: 'POST', body: opzioni.body } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  const lettore = r.body.getReader();
  const dec = new TextDecoder();
  let buffer = '', errore = null;
  for (;;) {
    const { value, done } = await lettore.read();
    if (done) break;
    buffer += dec.decode(value, { stream: true });
    const righe = buffer.split('\n');
    buffer = righe.pop();
    for (const riga of righe) {
      if (!riga.trim()) continue;
      const ev = JSON.parse(riga);
      if (ev.type === 'error') errore = ev.text;
      else if (ev.type !== 'done') suEvento(ev);
    }
  }
  if (errore) throw new Error(errore);
}

// Il fascicolo aperto vale per tutte le pagine: si ricorda nel browser.
const CHIAVE_FASCICOLO = 'law-fascicolo';
const fascicoloSalvato = () => { try { return Number(localStorage.getItem(CHIAVE_FASCICOLO)) || null; } catch { return null; } };
const salvaFascicolo = (id) => { try { localStorage.setItem(CHIAVE_FASCICOLO, String(id)); } catch { /* resta solo per questa pagina */ } };

const pagina = (p) => (p ? `p. ${p}` : 'testo');
const sec = (ms) => (ms == null ? '—' : (ms / 1000).toLocaleString('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' s');
const dataIt = (iso) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' }) : '');

// Scarica come .docx un testo del modello (riassunto, bozza, analisi).
async function scaricaDocx(titolo, testo) {
  const r = await fetch('/api/export/docx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: titolo, text: testo }) });
  if (!r.ok) throw new Error('Esportazione non riuscita');
  scaricaBlob(await r.blob(), `${titolo}.docx`);
}
function scaricaBlob(blob, nome) {
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: nome });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

const ICONE = {
  logo: '<svg viewBox="0 0 24 24"><path d="M12 3v17M8 20h8M5 7h14M5 7l-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0z"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  apri: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>',
  date: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  scadenze: '<svg viewBox="0 0 24 24"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6"/></svg>',
  importi: '<svg viewBox="0 0 24 24"><path d="M17 6.5A6.5 6.5 0 1 0 17 17.5M4 10h9M4 14h9"/></svg>',
  scarica: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  copia: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="1"/><path d="M16 8V4H4v12h4"/></svg>',
};

// Selettore del fascicolo nelle pagine figlie: cambia il fascicolo per tutta l'app.
async function preparaFascicolo(selettore, alCambio) {
  const fascicoli = await api('/cases');
  let id = fascicoloSalvato();
  if (!fascicoli.some((f) => f.id === id)) id = fascicoli[0]?.id;
  salvaFascicolo(id);
  selettore.innerHTML = fascicoli.map((f) => `<option value="${f.id}" ${f.id === id ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
  selettore.onchange = () => { salvaFascicolo(Number(selettore.value)); alCambio(Number(selettore.value)); };
  return id;
}

// ------------------------------------------------------------------ Markdown
// Markdown (già con i caratteri speciali neutralizzati da esc): i simboli non restano visibili, diventano formattazione.
// Supporta titoli, elenchi, citazioni, tabelle, grassetto, corsivo, ==evidenziato==, barrato e `codice`.
const mdInline = (s) => s
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*(.+?)\*\*|__(.+?)__/g, (m, a, b) => `<b>${a ?? b}</b>`)
  .replace(/(^|[^*\w])\*(?![\s*])([^*]+?)\*(?![*\w])/g, '$1<i>$2</i>')
  .replace(/==(.+?)==/g, '<mark>$1</mark>')
  .replace(/~~(.+?)~~/g, '<s>$1</s>');

function markdown(testo) {
  const righe = esc(testo).replace(/\r/g, '').split('\n');
  const celle = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  const sepTabella = (r) => r !== undefined && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(r) && r.includes('-') && (r.includes('|') || /^\s*:?-{3,}/.test(r));
  let h = '', i = 0;
  while (i < righe.length) {
    const r = righe[i];
    let m;
    if (!r.trim()) { i++; continue; }
    if (/^\s*```/.test(r)) {                       // blocco di codice (es. la query SQL), mostrato così com'è
      const codice = [];
      i++;
      while (i < righe.length && !/^\s*```/.test(righe[i])) { codice.push(righe[i]); i++; }
      i++;
      h += `<pre class="md-codice"><code>${codice.join('\n')}</code></pre>`;
      continue;
    }
    if (r.includes('|') && sepTabella(righe[i + 1]) && righe[i + 1].includes('|')) {
      const testa = celle(r);
      i += 2;
      let corpo = '';
      while (i < righe.length && righe[i].trim() && righe[i].includes('|')) {
        corpo += `<tr>${celle(righe[i]).map((c) => `<td>${mdInline(c)}</td>`).join('')}</tr>`; i++;
      }
      h += `<table class="md-tab"><thead><tr>${testa.map((c) => `<th>${mdInline(c)}</th>`).join('')}</tr></thead><tbody>${corpo}</tbody></table>`;
    } else if ((m = r.match(/^\s*(#{1,6})\s+(.*)$/))) {
      h += `<div class="md-h md-h${Math.min(m[1].length, 3)}">${mdInline(m[2])}</div>`; i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(r)) {
      h += '<hr>'; i++;
    } else if (/^\s*[-*•+]\s+/.test(r)) {
      let li = '';
      while (i < righe.length && /^\s*[-*•+]\s+/.test(righe[i])) { li += `<li>${mdInline(righe[i].replace(/^\s*[-*•+]\s+/, ''))}</li>`; i++; }
      h += `<ul>${li}</ul>`;
    } else if (/^\s*\d+[.)]\s+/.test(r)) {
      let li = '';
      while (i < righe.length && /^\s*\d+[.)]\s+/.test(righe[i])) { li += `<li>${mdInline(righe[i].replace(/^\s*\d+[.)]\s+/, ''))}</li>`; i++; }
      h += `<ol>${li}</ol>`;
    } else if (/^\s*&gt;\s?/.test(r)) {
      let q = [];
      while (i < righe.length && /^\s*&gt;\s?/.test(righe[i])) { q.push(mdInline(righe[i].replace(/^\s*&gt;\s?/, ''))); i++; }
      h += `<blockquote>${q.join('<br>')}</blockquote>`;
    } else {
      const p = [];
      while (i < righe.length && righe[i].trim() && !/^\s*(#{1,6}\s|[-*•+]\s|\d+[.)]\s|&gt;)/.test(righe[i])) { p.push(mdInline(righe[i])); i++; }
      h += `<p>${p.join('<br>')}</p>`;
    }
  }
  return h;
}

// testo senza simboli markdown, per le anteprime di una riga
const senzaMarkdown = (t) => String(t ?? '').replace(/^\s*#{1,6}\s+/gm, '').replace(/^\s*[-*•+]\s+/gm, '• ')
  .replace(/\*\*(.+?)\*\*|__(.+?)__/g, '$1$2').replace(/(^|[^*\w])\*(?![\s*])([^*]+?)\*(?![*\w])/g, '$1$2')
  .replace(/==(.+?)==|~~(.+?)~~|`([^`]+)`/g, '$1$2$3').replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, '').replace(/\|/g, ' ');

// evidenzia i termini nel testo semplice (prima escape, poi <mark>)
function evidenzia(testo, termini = []) {
  const h = esc(testo);
  const validi = termini.filter(Boolean).sort((a, b) => b.length - a.length);
  if (!validi.length) return h;
  return h.replace(new RegExp(`(${validi.map((t) => reEsc(esc(t))).join('|')})`, 'gi'), '<mark>$1</mark>');
}
