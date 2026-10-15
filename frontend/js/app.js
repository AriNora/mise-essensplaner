/**
 * Mise — Frontend-Logik (Vanilla JS, ein Modul, kein Build-Schritt).
 *
 * Aufbau:
 *   - Kleine Helfer (Escaping, Zahlenformat, Toast, Navigation)
 *   - Pro Ansicht eine render-Funktion, die in #app schreibt und Events verdrahtet
 *   - Ein hash-basierter Router am Ende, der die passende Ansicht aufruft
 */
import { api } from "./api.js";

const app = document.getElementById("app");
let importDraft = null; // Zwischenspeicher fuer einen Import-Entwurf

const CATEGORIES = [
  "Obst & Gemüse", "Hülsenfrüchte", "Getreide & Backwaren",
  "Pflanzendrinks & Tofu", "Nüsse & Samen", "Öle & Essige",
  "Gewürze & Würze", "Konserven & Vorrat", "Sonstiges",
];
const PAGE_SIZE = 50;
const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const DAY_NAMES = { Mo: "Montag", Di: "Dienstag", Mi: "Mittwoch", Do: "Donnerstag", Fr: "Freitag", Sa: "Samstag", So: "Sonntag" };

// Facetten des Tag-Systems (Reihenfolge = Anzeigereihenfolge).
const KIND_ORDER = ["typ", "kueche", "eigenschaft"];
const KIND_LABELS = { typ: "Gericht-Typ", kueche: "Küche", eigenschaft: "Eigenschaft" };
// Kontrolliertes Vokabular fuer den Editor (Filterleiste zeigt nur benutzte Tags).
const TAG_VOCAB = {
  typ: ["Hauptgericht", "Suppe", "Eintopf", "Pasta", "Bowl", "Curry", "Salat",
        "Frühstück", "Dessert", "Snack", "Beilage", "Aufstrich/Dip", "Getränk"],
  kueche: ["Italienisch", "Indisch", "Thai", "Mexikanisch", "Griechisch", "Japanisch",
           "Koreanisch", "Chinesisch", "Asiatisch", "Orientalisch"],
  eigenschaft: ["schnell", "One-Pot", "Meal-Prep", "proteinreich", "glutenfrei", "budgetfreundlich"],
};

/* ----------------------------- Helfer ----------------------------- */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtNum = (n) =>
  n == null ? "" : Number(n).toLocaleString("de-DE", { maximumFractionDigits: 2 });

const node = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};

function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) { t = node(`<div class="toast"></div>`); document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

function setActiveNav(route) {
  document.querySelectorAll("#nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.route === route));
}

async function refreshPlanBadge() {
  try {
    const plan = await api.getPlan();
    const badge = document.getElementById("plan-badge");
    badge.textContent = plan.length;
    badge.hidden = plan.length === 0;
  } catch (_) {}
}

const go = (hash) => { location.hash = hash; };

/* --------------------------- Rezeptliste --------------------------- */
const listState = { search: "", offset: 0, facets: { typ: [], kueche: [], eigenschaft: [] } };
const HASH_PARAM = { typ: "typ", kueche: "kueche", eigenschaft: "eig" }; // Facette -> Hash-Schluessel

// Filter + Suche in den URL-Hash schreiben: teilbar, bleibt beim Neuladen erhalten.
function buildRecipesHash() {
  const p = new URLSearchParams();
  if (listState.search) p.set("q", listState.search);
  for (const k of KIND_ORDER) if (listState.facets[k].length) p.set(HASH_PARAM[k], listState.facets[k].join(","));
  const qs = p.toString();
  return "#/recipes" + (qs ? "?" + qs : "");
}

// Hash aktualisieren OHNE erneutes Routing (replaceState loest kein hashchange aus).
function syncHash() {
  history.replaceState(null, "", buildRecipesHash());
}

// Hash -> Filter-Zustand (beim Betreten der Liste, auch ueber geteilten Link).
function applyRecipesQuery(queryStr) {
  const p = new URLSearchParams(queryStr || "");
  listState.search = p.get("q") || "";
  listState.offset = 0;
  for (const k of KIND_ORDER) {
    const v = p.get(HASH_PARAM[k]) || "";
    listState.facets[k] = v ? v.split(",").map((s) => s.trim()).filter(Boolean) : [];
  }
}

const anyFacetActive = () => KIND_ORDER.some((k) => listState.facets[k].length);

// Filterleiste aus den benutzten Tags (mit Trefferzahl) aufbauen.
function renderFilters(tags) {
  const wrap = document.getElementById("filters");
  if (!wrap) return;
  const byKind = { typ: [], kueche: [], eigenschaft: [] };
  for (const t of tags) if (byKind[t.kind]) byKind[t.kind].push(t);

  let html = "";
  for (const k of KIND_ORDER) {
    if (!byKind[k].length) continue;
    const chips = byKind[k].map((t) => {
      const active = listState.facets[k].includes(t.name);
      return `<button class="chip${active ? " active" : ""}" data-kind="${k}" data-name="${esc(t.name)}">${esc(t.name)}<span class="chip-count">${t.count}</span></button>`;
    }).join("");
    html += `<div class="filter-facet"><span class="filter-label">${esc(KIND_LABELS[k])}</span><div class="chips">${chips}</div></div>`;
  }
  if (!html) { wrap.innerHTML = ""; return; } // noch keine Tags vergeben
  html += `<button class="filter-reset" id="filter-reset" ${anyFacetActive() ? "" : "hidden"}>Filter zurücksetzen</button>`;
  wrap.innerHTML = html;

  wrap.querySelectorAll(".chip").forEach((btn) => {
    btn.onclick = () => {
      const { kind, name } = btn.dataset;
      const arr = listState.facets[kind];
      const i = arr.indexOf(name);
      if (i === -1) arr.push(name); else arr.splice(i, 1);
      btn.classList.toggle("active");
      listState.offset = 0;
      syncHash();
      document.getElementById("filter-reset").hidden = !anyFacetActive();
      loadList();
    };
  });
  const reset = document.getElementById("filter-reset");
  if (reset) reset.onclick = () => {
    for (const k of KIND_ORDER) listState.facets[k] = [];
    listState.offset = 0;
    syncHash();
    wrap.querySelectorAll(".chip.active").forEach((c) => c.classList.remove("active"));
    reset.hidden = true;
    loadList();
  };
}

async function viewRecipes() {
  setActiveNav("recipes");
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h1>Rezepte</h1>
        <div class="sub" id="recipe-count">lade …</div>
      </div>
      <div style="display:flex; gap:.5rem;">
        <button class="btn" id="import-recipe">Importieren</button>
        <button class="btn btn-primary" id="new-recipe">+ Neues Rezept</button>
      </div>
    </div>
    <input class="search" id="search" type="search" placeholder="Rezept suchen …"
           value="${esc(listState.search)}" autocomplete="off" />
    <div class="filters" id="filters"></div>
    <ul class="recipe-list" id="recipe-list"></ul>
    <div class="pager" id="pager"></div>
    <details class="backup-box" id="backup-box">
      <summary>Sicherung</summary>
      <p class="kv">Alle Rezepte, Bilder und der Vorrat in einer Datei – zum Aufbewahren oder für einen neuen Rechner.
        Beim Einspielen wird nichts überschrieben: Rezepte mit gleichem Namen bleiben, wie sie sind.</p>
      <div class="backup-actions">
        <a class="btn" href="/api/backup" download>Alles sichern</a>
        <button class="btn" type="button" id="restore-btn">Sicherung einspielen …</button>
        <input type="file" id="restore-file" accept=".zip,application/zip" hidden />
      </div>
      <p class="kv" id="restore-msg" role="status"></p>
    </details>
  `;
  document.getElementById("restore-btn").onclick = () => document.getElementById("restore-file").click();
  document.getElementById("restore-file").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const msg = document.getElementById("restore-msg");
    msg.textContent = "Sicherung wird eingespielt …";
    try {
      const r = await api.restoreBackup(file);
      const parts = [`${r.recipes_added} Rezept(e) ergänzt`];
      if (r.recipes_skipped) parts.push(`${r.recipes_skipped} schon vorhanden`);
      if (r.images_added) parts.push(`${r.images_added} Bild(er)`);
      if (r.pantry_added) parts.push(`${r.pantry_added} Vorrats-Eintrag/-Einträge`);
      if (r.recipes_invalid.length) parts.push(`nicht lesbar: ${r.recipes_invalid.join(", ")}`);
      msg.textContent = parts.join(" · ") + ".";
      loadList();
      api.listTags().then((data) => renderFilters(data.tags)).catch(() => {});
    } catch (err) {
      msg.textContent = err.message;
    }
  };
  document.getElementById("new-recipe").onclick = () => go("#/new");
  document.getElementById("import-recipe").onclick = () => go("#/import");

  const search = document.getElementById("search");
  let timer;
  search.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { listState.search = search.value; listState.offset = 0; syncHash(); loadList(); }, 200);
  };

  // Filterleiste aus den vorhandenen Tags aufbauen (parallel zur Liste).
  api.listTags().then((data) => renderFilters(data.tags)).catch(() => {});
  loadList();
}

async function loadList() {
  const listEl = document.getElementById("recipe-list");
  const data = await api.listRecipes(listState.search, PAGE_SIZE, listState.offset, listState.facets);
  document.getElementById("recipe-count").textContent =
    `${data.total} ${data.total === 1 ? "Rezept" : "Rezepte"}`;

  if (data.items.length === 0) {
    const filtered = listState.search || anyFacetActive();
    listEl.innerHTML = `<div class="empty"><div class="big">Nichts gefunden</div>
      ${filtered ? "Passe Suche oder Filter an." : "Lege ein neues Rezept an."}</div>`;
    document.getElementById("pager").innerHTML = "";
    return;
  }

  listEl.innerHTML = "";
  for (const r of data.items) {
    const row = node(`
      <li class="recipe-row" tabindex="0">
        <span class="recipe-row-main">${r.image ? `<img class="recipe-thumb" src="${esc(r.image)}" alt="" />` : `<span class="recipe-thumb placeholder">▦</span>`}<span class="title">${esc(r.name)}</span></span>
        <span class="meta">${r.ingredient_count} Zutaten · ${r.servings} Port.</span>
      </li>`);
    const open = () => go(`#/recipes/${r.id}`);
    row.onclick = open;
    row.onkeydown = (e) => { if (e.key === "Enter") open(); };
    listEl.appendChild(row);
  }

  // Seitenblaetterung
  const pager = document.getElementById("pager");
  const from = listState.offset + 1;
  const to = Math.min(listState.offset + PAGE_SIZE, data.total);
  pager.innerHTML = "";
  const prev = node(`<button class="btn btn-sm" ${listState.offset === 0 ? "disabled" : ""}>← Zurück</button>`);
  const next = node(`<button class="btn btn-sm" ${to >= data.total ? "disabled" : ""}>Weiter →</button>`);
  prev.onclick = () => { listState.offset = Math.max(0, listState.offset - PAGE_SIZE); loadList(); };
  next.onclick = () => { listState.offset += PAGE_SIZE; loadList(); };
  pager.append(prev, node(`<span>${from}–${to} von ${data.total}</span>`), next);
}

/* --------------------------- Rezept-Detail -------------------------- */
async function viewRecipeDetail(id) {
  setActiveNav("recipes");
  let r;
  try { r = await api.getRecipe(id); }
  catch (_) { app.innerHTML = `<div class="empty">Rezept nicht gefunden.</div>`; return; }

  const rows = r.ingredients.map((i) => `
    <tr>
      <td class="amount">${i.amount != null ? esc(fmtNum(i.amount)) : ""} ${esc(i.unit || "")}</td>
      <td>${esc(i.name)}</td>
      <td class="prep-tag">${esc(i.preparation || "")}</td>
    </tr>`).join("");

  app.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(r.name)}</h1>
        <div class="sub">Basis: ${r.servings} Portionen · ${r.ingredients.length} Zutaten</div>
      </div>
      <div style="display:flex; gap:.5rem;">
        <button class="btn" id="edit">Bearbeiten</button>
        <button class="btn btn-danger" id="del">Löschen</button>
      </div>
    </div>

    ${r.tags && r.tags.length ? `<div class="tag-row">${r.tags.map((t) => `<span class="chip chip-static chip-${esc(t.kind)}">${esc(t.name)}</span>`).join("")}</div>` : ""}

    ${r.image ? `<img class="recipe-photo" src="${esc(r.image)}" alt="${esc(r.name)}" />` : ""}
    <div class="card photo-card">
      <input type="file" id="img-input" accept="image/jpeg,image/png,image/webp,image/gif" hidden />
      <button class="btn" id="img-pick">${r.image ? "Bild ändern" : "Bild hochladen"}</button>
      ${r.image ? '<button class="btn btn-danger" id="img-del">Bild entfernen</button>' : ""}
      <span class="kv">JPG, PNG, WEBP oder GIF · max 5 MB</span>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Zutaten</h3>
      <table class="ing-table">
        <thead><tr><th>Menge</th><th>Zutat</th><th>Vorbereitung</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="3" class="kv">keine Zutaten</td></tr>`}</tbody>
      </table>
    </div>

    ${r.instructions ? `<div class="card"><h3 style="margin-top:0">Zubereitung</h3>
        <div class="steps">${esc(r.instructions)}</div></div>` : ""}

    ${r.source ? `<div class="card"><h3 style="margin-top:0">Quelle</h3>
        ${/^https?:\/\//i.test(r.source)
          ? `<a href="${esc(r.source)}" target="_blank" rel="noopener noreferrer" style="word-break:break-all">${esc(r.source)}</a>`
          : `<div class="kv">${esc(r.source)}</div>`}</div>` : ""}

    <div class="card">
      <h3 style="margin-top:0">Zum Wochenplan hinzufügen</h3>
      <div class="stepper" style="margin-bottom:.7rem">
        <span class="kv">Portionen:</span>
        <button id="ps-minus">−</button>
        <span class="val" id="ps-val">${r.servings}</span>
        <button id="ps-plus">+</button>
      </div>
      <div style="display:flex; align-items:center; gap:.5rem; margin-bottom:.9rem;">
        <span class="kv">Tag (optional):</span>
        <select id="ps-day">
          <option value="">— kein Tag —</option>
          ${DAYS.map((d) => `<option value="${d}">${DAY_NAMES[d]}</option>`).join("")}
        </select>
      </div>
      <button class="btn btn-primary" id="add-plan">In den Wochenplan</button>
      <a class="btn btn-ghost" href="#/recipes">← Zurück</a>
    </div>
  `;

  document.getElementById("edit").onclick = () => go(`#/recipes/${id}/edit`);
  const imgInput = document.getElementById("img-input");
  document.getElementById("img-pick").onclick = () => imgInput.click();
  imgInput.onchange = async () => {
    const file = imgInput.files[0];
    if (!file) return;
    try { await api.uploadRecipeImage(id, file); toast("Bild gespeichert"); viewRecipeDetail(id); }
    catch (e) { toast("Fehler: " + e.message); }
  };
  const imgDel = document.getElementById("img-del");
  if (imgDel) imgDel.onclick = async () => {
    await api.deleteRecipeImage(id); toast("Bild entfernt"); viewRecipeDetail(id);
  };
  document.getElementById("del").onclick = async () => {
    if (!confirm(`„${r.name}" wirklich löschen?`)) return;
    await api.deleteRecipe(id); toast("Rezept gelöscht"); go("#/recipes");
  };

  let portions = r.servings;
  const val = document.getElementById("ps-val");
  document.getElementById("ps-minus").onclick = () => { portions = Math.max(1, portions - 1); val.textContent = portions; };
  document.getElementById("ps-plus").onclick = () => { portions += 1; val.textContent = portions; };
  document.getElementById("add-plan").onclick = async () => {
    const day = document.getElementById("ps-day").value || null;
    await api.addToPlan({ recipe_id: Number(id), servings: portions, day });
    await refreshPlanBadge();
    toast("Zum Wochenplan hinzugefügt");
  };
}

/* ---------------------------- Editor ------------------------------- */
// In diesen Facetten darf der Nutzer eigene Tags anlegen (offenes Vokabular).
// Das Basis-Vokabular bleibt als Vorschlag erhalten; eigene Eintraege kommen dazu.
const CUSTOM_FACETS = ["typ", "kueche", "eigenschaft"];
// Facetten-passende Beispiele im Eingabefeld.
const CUSTOM_PLACEHOLDER = { typ: "z. B. Auflauf", kueche: "z. B. Türkisch", eigenschaft: "z. B. kalorienarm" };

// Tag-Namen vereinheitlichen: Kommas/doppelte Leerzeichen raus (Kommas wuerden
// die Filter-Parameter zerlegen), sanfte Gross-Schreibung, Laenge begrenzen.
function sanitizeTagName(value) {
  let s = (value || "").replace(/,/g, " ").replace(/\s+/g, " ").trim();
  if (!s) return "";
  s = s.charAt(0).toUpperCase() + s.slice(1);
  return s.slice(0, 30);
}

// Auswahlmoeglichkeiten einer Facette = Basis-Vokabular + bereits benutzte Tags
// (aus /api/tags) + die am Rezept gesetzten. Dedup case-insensitiv.
function facetOptions(kind, selected, knownTags) {
  const seen = new Map(); // lowercase -> Anzeigename (erste Schreibweise gewinnt)
  const add = (name) => { const key = name.toLowerCase(); if (!seen.has(key)) seen.set(key, name); };
  (TAG_VOCAB[kind] || []).forEach(add);
  (knownTags || []).filter((t) => t.kind === kind).forEach((t) => add(t.name));
  (selected || []).filter((t) => t.kind === kind).forEach((t) => add(t.name));
  const names = [...seen.values()];
  if (kind === "kueche") names.sort((a, b) => a.localeCompare(b, "de")); // waechst -> alphabetisch
  return names;
}

// Tag-Auswahl im Editor: Chips je Facette, an/aus per Klick. In CUSTOM_FACETS
// zusaetzlich ein "+ Andere…"-Feld zum Anlegen eigener Tags.
function renderTagPicker(container, selected, knownTags) {
  const sel = new Set((selected || []).map((t) => `${t.kind}|${t.name.toLowerCase()}`));
  container.innerHTML = KIND_ORDER.map((k) => {
    const chips = facetOptions(k, selected, knownTags).map((name) => {
      const active = sel.has(`${k}|${name.toLowerCase()}`);
      return `<button type="button" class="chip${active ? " active" : ""}" data-kind="${k}" data-name="${esc(name)}">${esc(name)}</button>`;
    }).join("");
    const adder = CUSTOM_FACETS.includes(k)
      ? `<button type="button" class="chip chip-add" data-add="${k}">+ Andere…</button>` : "";
    return `<div class="filter-facet"><span class="filter-label">${esc(KIND_LABELS[k])}</span><div class="chips">${chips}${adder}</div></div>`;
  }).join("");

  container.querySelectorAll(".chip:not(.chip-add)").forEach((b) => {
    b.onclick = () => b.classList.toggle("active");
  });
  container.querySelectorAll(".chip-add").forEach((b) => {
    b.onclick = () => openCustomInput(b, b.dataset.add);
  });
}

// Kleines Eingabefeld neben "+ Andere…" zum Tippen einer neuen Kategorie.
function openCustomInput(addBtn, kind) {
  if (addBtn.dataset.open === "1") return;
  addBtn.dataset.open = "1";
  const form = node(`<span class="chip-add-form">
    <input type="text" class="chip-add-input" maxlength="30" placeholder="${esc(CUSTOM_PLACEHOLDER[kind] || "Neue Kategorie")}" />
    <button type="button" class="chip chip-add-ok">Hinzufügen</button></span>`);
  addBtn.insertAdjacentElement("afterend", form);
  const input = form.querySelector(".chip-add-input");
  const chipsRow = addBtn.parentElement;
  input.focus();

  const close = () => { form.remove(); addBtn.dataset.open = ""; };
  const commit = () => {
    const name = sanitizeTagName(input.value);
    if (name) addCustomChip(chipsRow, addBtn, kind, name);
    close();
  };
  form.querySelector(".chip-add-ok").onclick = commit;
  input.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  };
  // Klick auf "Hinzufügen" loest erst blur aus -> kurze Verzoegerung, dann schliessen.
  input.onblur = () => setTimeout(() => { if (addBtn.dataset.open === "1") close(); }, 120);
}

// Neuen Chip einfuegen (oder vorhandenen aktivieren, falls schon da).
function addCustomChip(chipsRow, addBtn, kind, name) {
  const existing = [...chipsRow.querySelectorAll(".chip:not(.chip-add)")]
    .find((c) => (c.dataset.name || "").toLowerCase() === name.toLowerCase());
  if (existing) { existing.classList.add("active"); return; }
  const chip = node(`<button type="button" class="chip active"></button>`);
  chip.dataset.kind = kind;
  chip.dataset.name = name;
  chip.textContent = name;
  chip.onclick = () => chip.classList.toggle("active");
  addBtn.insertAdjacentElement("beforebegin", chip); // vor dem "+ Andere…"
}

function ingredientRow(data = {}) {
  const catOptions = CATEGORIES.map((c) =>
    `<option ${c === data.category ? "selected" : ""}>${c}</option>`).join("");
  const row = node(`
    <div class="ing-edit-row">
      <input class="ing-amount" type="number" step="0.1" min="0" placeholder="Menge"
             value="${data.amount != null ? data.amount : ""}" aria-label="Menge" />
      <input class="ing-unit" list="dl-units" placeholder="Einheit"
             value="${esc(data.unit || "")}" aria-label="Einheit" />
      <input class="ing-name" list="dl-ingredients" placeholder="Zutat"
             value="${esc(data.name || "")}" aria-label="Zutat" />
      <input class="ing-prep" list="dl-preps" placeholder="Vorbereitung"
             value="${esc(data.preparation || "")}" aria-label="Vorbereitung" />
      <select class="ing-cat" aria-label="Warengruppe">
        <option value="">Warengruppe …</option>${catOptions}
      </select>
      <button class="x" title="Zeile entfernen" aria-label="Zeile entfernen">×</button>
    </div>`);
  row.querySelector(".x").onclick = () => row.remove();
  return row;
}

async function viewEditor(id = null) {
  setActiveNav("recipes");
  const editing = id != null;
  let r = { name: "", servings: 2, instructions: "", source: "", ingredients: [] };
  if (editing) {
    try { r = await api.getRecipe(id); }
    catch (_) { app.innerHTML = `<div class="empty">Rezept nicht gefunden.</div>`; return; }
  } else if (importDraft) {
    r = importDraft;       // aus dem Import vorgefuellt
    importDraft = null;    // nur einmal verwenden
  }

  app.innerHTML = `
    <div class="page-head"><h1>${editing ? "Rezept bearbeiten" : "Neues Rezept"}</h1></div>
    <div class="card">
      <div class="form-grid">
        <div class="row-2">
          <div class="field"><label>Name</label>
            <input id="f-name" value="${esc(r.name)}" placeholder="z.B. Linsen-Dal" /></div>
          <div class="field"><label>Basis-Portionen</label>
            <input id="f-serv" type="number" min="1" value="${r.servings}" /></div>
        </div>

        <div class="field">
          <label>Zutaten</label>
          <div class="ing-edit-row ing-head">
            <span>Menge</span><span>Einheit</span><span>Zutat</span><span>Vorbereitung</span><span>Warengruppe</span><span></span>
          </div>
          <div class="ing-editor" id="ings"></div>
          <button class="btn btn-sm" id="add-ing" style="margin-top:.5rem">+ Zutat</button>
        </div>

        <div class="field"><label>Zubereitung (optional)</label>
          <textarea id="f-instr" rows="5" placeholder="Schritt für Schritt …">${esc(r.instructions || "")}</textarea></div>

        <div class="field"><label>Quelle (Link, optional)</label>
          <input id="f-source" value="${esc(r.source || "")}" placeholder="https://…" /></div>

        <div class="field"><label>Kategorien (Mehrfachauswahl)</label>
          <div class="tag-pick" id="tag-pick"></div></div>

        <div style="display:flex; gap:.6rem;">
          <button class="btn btn-primary" id="save">${editing ? "Änderungen speichern" : "Rezept anlegen"}</button>
          <a class="btn btn-ghost" href="${editing ? `#/recipes/${id}` : "#/recipes"}">Abbrechen</a>
        </div>
      </div>
    </div>
  `;

  // Zutaten-Datalist fuellen (Autovervollstaendigung)
  try {
    const ings = await api.listIngredients("");
    const dl = document.getElementById("dl-ingredients");
    dl.innerHTML = ings.map((i) => `<option value="${esc(i.name)}"></option>`).join("");
  } catch (_) {}

  const ingsEl = document.getElementById("ings");
  const initial = r.ingredients.length ? r.ingredients : [{}];
  initial.forEach((i) => ingsEl.appendChild(ingredientRow(i)));
  document.getElementById("add-ing").onclick = () => ingsEl.appendChild(ingredientRow());

  const tagPick = document.getElementById("tag-pick");
  // Bereits benutzte Tags holen, damit eigene Küchen als Vorschlag erscheinen.
  const knownTags = await api.listTags().then((d) => d.tags).catch(() => []);
  renderTagPicker(tagPick, r.tags || [], knownTags);

  document.getElementById("save").onclick = async () => {
    const name = document.getElementById("f-name").value.trim();
    if (!name) { toast("Bitte einen Namen angeben"); return; }
    const servings = Math.max(1, parseInt(document.getElementById("f-serv").value || "1", 10));

    const ingredients = [...ingsEl.querySelectorAll(".ing-edit-row")]
      .map((row) => ({
        amount: row.querySelector(".ing-amount").value === "" ? null : Number(row.querySelector(".ing-amount").value),
        unit: row.querySelector(".ing-unit").value.trim() || null,
        name: row.querySelector(".ing-name").value.trim(),
        preparation: row.querySelector(".ing-prep").value.trim() || null,
        category: row.querySelector(".ing-cat").value || null,
      }))
      .filter((i) => i.name); // leere Zeilen verwerfen

    const tags = [...tagPick.querySelectorAll(".chip.active")]
      .map((c) => ({ kind: c.dataset.kind, name: c.dataset.name }));

    const payload = { name, servings, instructions: document.getElementById("f-instr").value.trim() || null, source: document.getElementById("f-source").value.trim() || null, ingredients, tags };
    try {
      const saved = editing ? await api.updateRecipe(id, payload) : await api.createRecipe(payload);
      toast(editing ? "Gespeichert" : "Rezept angelegt");
      go(`#/recipes/${saved.id}`);
    } catch (e) { toast("Fehler: " + e.message); }
  };
}

/* --------------------------- Wochenplan ---------------------------- */
async function viewPlan() {
  setActiveNav("plan");
  const plan = await api.getPlan();

  app.innerHTML = `
    <div class="page-head"><div><h1>Wochenplan</h1>
      <div class="sub">${plan.length === 0
        ? "Noch nichts geplant — füge Gerichte aus den Rezepten hinzu und ordne sie den Tagen zu."
        : plan.length + (plan.length === 1 ? " Gericht" : " Gerichte") + " eingeplant"}</div></div></div>
    <div id="week"></div>
    <div class="plan-actions">
      <a class="btn btn-primary" href="#/shopping">Einkaufsliste anzeigen</a>
      <a class="btn" href="#/prep">Vorbereitungsplan anzeigen</a>
      <button class="btn btn-danger" id="clear" ${plan.length === 0 ? "disabled" : ""}>Plan leeren</button>
    </div>
  `;

  // Einträge nach Wochentag gruppieren ("" = ohne Tag)
  const byDay = {};
  for (const d of DAYS) byDay[d] = [];
  byDay[""] = [];
  for (const e of plan) byDay[DAYS.includes(e.day) ? e.day : ""].push(e);

  const week = document.getElementById("week");
  for (const d of [...DAYS, ""]) {
    const entries = byDay[d];
    if (d === "" && entries.length === 0) continue; // "Ohne Tag" nur zeigen, wenn belegt
    const sec = node(`<div class="day-section">
        <h3 class="day-head">${d === "" ? "Ohne Tag" : DAY_NAMES[d]}</h3>
        <div class="day-body"></div>
      </div>`);
    const body = sec.querySelector(".day-body");
    if (entries.length === 0) body.appendChild(node(`<div class="kv day-empty">—</div>`));
    else entries.forEach((e) => body.appendChild(planEntryRow(e)));
    week.appendChild(sec);
  }

  document.getElementById("clear").onclick = async () => {
    if (plan.length === 0) return;
    if (!confirm("Gesamten Wochenplan leeren?")) return;
    await api.clearPlan(); await refreshPlanBadge(); viewPlan();
  };
}

// Eine Zeile im Wochenplan: Portions-Stepper, Tag-Auswahl, Entfernen
function planEntryRow(e) {
  const dayOpts = ['<option value="">— Tag —</option>']
    .concat(DAYS.map((d) => `<option value="${d}" ${e.day === d ? "selected" : ""}>${d}</option>`))
    .join("");
  const row = node(`
    <div class="plan-row">
      <div>
        <div style="font-weight:600"><a href="#/recipes/${e.recipe_id}" style="color:inherit;text-decoration:none">${esc(e.recipe_name)}</a></div>
        <div class="kv">Basis ${e.base_servings} Portionen</div>
      </div>
      <div style="display:flex; align-items:center; gap:.7rem; flex-wrap:wrap;">
        <select class="day-select" aria-label="Wochentag">${dayOpts}</select>
        <div class="stepper">
          <button class="minus" aria-label="weniger">−</button>
          <span class="val">${e.servings}</span>
          <button class="plus" aria-label="mehr">+</button>
        </div>
        <button class="btn btn-sm btn-danger remove">Entfernen</button>
      </div>
    </div>`);
  const valEl = row.querySelector(".val");
  let s = e.servings;
  row.querySelector(".minus").onclick = async () => { if (s > 1) { s--; valEl.textContent = s; await api.updatePlanEntry(e.id, { servings: s }); } };
  row.querySelector(".plus").onclick = async () => { s++; valEl.textContent = s; await api.updatePlanEntry(e.id, { servings: s }); };
  row.querySelector(".day-select").onchange = async (ev) => { await api.updatePlanEntry(e.id, { day: ev.target.value }); viewPlan(); };
  row.querySelector(".remove").onclick = async () => { await api.removePlanEntry(e.id); await refreshPlanBadge(); viewPlan(); };
  return row;
}

/* -------------------------- Einkaufsliste -------------------------- */
async function viewShopping() {
  setActiveNav("shopping");
  const data = await api.shoppingList();
  if (data.groups.length === 0) {
    app.innerHTML = `<div class="page-head"><h1>Einkaufsliste</h1></div>
      <div class="empty"><div class="big">Noch nichts einzukaufen</div>
      ${data.in_pantry && data.in_pantry.length ? "Alles, was du brauchst, ist im Vorrat." : "Plane zuerst ein paar Rezepte ein."}
      <div style="margin-top:1rem"><a class="btn btn-primary" href="#/recipes">Rezepte ansehen</a></div></div>
      ${inPantryBlock(data.in_pantry)}`;
    return;
  }

  // Laufende Nummer fuer eindeutige Checkbox-IDs (gleicher Name kann in zwei
  // Einheiten vorkommen -> sonst doppelte IDs). data-* traegt die Werte fuer Bring!.
  let n = 0;
  const groups = data.groups.map((g) => `
    <div class="group">
      <h3>${esc(g.category)}</h3>
      <ul class="check-list">
        ${g.items.map((i) => {
          const id = `c-${n++}`;
          const amountText = i.amount != null ? esc(fmtNum(i.amount)) + " " + esc(i.unit || "") : "nach Bedarf";
          return `
          <li data-name="${esc(i.name)}" data-amount="${i.amount != null ? i.amount : ""}" data-unit="${esc(i.unit || "")}">
            <input type="checkbox" id="${id}" />
            <label for="${id}">${esc(i.name)}</label>
            <span class="amount">${amountText}</span>
          </li>`;
        }).join("")}
      </ul>
    </div>`).join("");

  app.innerHTML = `
    <div class="page-head"><div><h1>Einkaufsliste</h1>
      <div class="sub">Hake ab, was du diesmal schon zu Hause hast – an Bring! gehen nur die offenen Posten. Dauerhaftes pflegst du unter „Vorrat“.</div></div>
      <div style="display:flex; gap:.5rem;">
        <button class="btn btn-primary" id="bring">An Bring! senden</button>
        <button class="btn" id="print">Drucken</button>
      </div></div>
    ${groups}
    ${inPantryBlock(data.in_pantry)}
  `;
  document.getElementById("print").onclick = () => window.print();

  // An Bring! senden – nur die NICHT abgehakten Posten (= noch zu kaufen).
  const bringBtn = document.getElementById("bring");
  bringBtn.onclick = async () => {
    const items = [...app.querySelectorAll(".check-list li:not(.done)")].map((li) => ({
      name: li.dataset.name,
      amount: li.dataset.amount === "" ? null : Number(li.dataset.amount),
      unit: li.dataset.unit || null,
    }));
    if (items.length === 0) {
      toast("Alles abgehakt – nichts an Bring! zu senden.");
      return;
    }
    const label = bringBtn.textContent;
    bringBtn.disabled = true;
    bringBtn.textContent = "Sende …";
    try {
      const res = await api.sendToBring(items);
      toast(`${res.sent} ${res.sent === 1 ? "Posten" : "Posten"} an Bring! gesendet${res.list ? " (Liste: " + res.list + ")" : ""}.`);
    } catch (e) {
      toast(e.message);
    } finally {
      bringBtn.disabled = false;
      bringBtn.textContent = label;
    }
  };

  // Abhaken (= vorrätig): markiert die Zeile, schließt sie vom Bring!-Versand aus.
  app.querySelectorAll(".check-list input").forEach((cb) => {
    cb.onchange = () => cb.closest("li").classList.toggle("done", cb.checked);
  });
}

/* ------------------------------- Vorrat ---------------------------- */
// Eingeklappter Abschnitt unter der Einkaufsliste: was wegen des Vorrats fehlt.
// So bleibt sichtbar, wenn der Abgleich eine Zutat zu Unrecht ausblendet.
function inPantryBlock(list) {
  if (!list || !list.length) return "";
  return `<details class="card pantry-skipped">
    <summary>Aus dem Vorrat (${list.length}) – steht nicht auf der Liste</summary>
    <ul class="check-list">
      ${list.map((i) => `<li><label>${esc(i.name)}</label><span class="amount">Vorrat: ${esc(i.pantry)}</span></li>`).join("")}
    </ul>
    <a href="#/pantry">Vorrat bearbeiten</a>
  </details>`;
}

async function viewPantry() {
  setActiveNav("pantry");
  app.innerHTML = `
    <div class="page-head"><div><h1>Vorrat</h1>
      <div class="sub">Zutaten, die du immer da hast. Sie bleiben im Rezept stehen, kommen aber nie auf die Einkaufsliste.</div></div></div>
    <form class="pantry-add" id="pantry-form">
      <input class="search" id="pantry-input" list="dl-ingredients" maxlength="80"
             placeholder="Zutat hinzufügen, z. B. Salz" autocomplete="off" />
      <button class="btn btn-primary" type="submit">Hinzufügen</button>
    </form>
    <div class="chips" id="pantry-chips"></div>
    <p class="kv pantry-hint">Ein Eintrag gilt für alle Formen am Wortende: „Wasser“ deckt auch „kochendes Wasser“
      und „Wasser, lauwarm“. Zusammengesetzte Wörter wie „Meersalz“ oder „Sprudelwasser“ trägst du bei Bedarf einzeln ein.</p>
  `;
  const input = document.getElementById("pantry-input");
  const chips = document.getElementById("pantry-chips");

  async function load() {
    const items = await api.listPantry();
    chips.innerHTML = items.length
      ? items.map((i) => `<button class="chip" data-id="${i.id}" title="Entfernen">${esc(i.name)}<span class="chip-x">×</span></button>`).join("")
      : `<span class="kv">Noch nichts eingetragen.</span>`;
    chips.querySelectorAll(".chip").forEach((btn) => {
      btn.onclick = async () => {
        try { await api.removePantryItem(btn.dataset.id); await load(); }
        catch (e) { toast(e.message); }
      };
    });
  }

  // Vorschlaege aus den bekannten Zutaten (wie im Rezept-Editor).
  let timer;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const ings = await api.listIngredients(input.value);
        document.getElementById("dl-ingredients").innerHTML =
          ings.map((i) => `<option value="${esc(i.name)}"></option>`).join("");
      } catch (_) {}
    }, 150);
  };

  document.getElementById("pantry-form").onsubmit = async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    try {
      await api.addPantryItem(name);
      input.value = "";
      await load();
    } catch (err) { toast(err.message); }
    input.focus();
  };

  await load();
}

/* ------------------------- Vorbereitungsplan ----------------------- */
async function viewPrep() {
  setActiveNav("prep");
  const data = await api.prepPlan();
  if (data.groups.length === 0) {
    app.innerHTML = `<div class="page-head"><h1>Vorbereitung</h1></div>
      <div class="empty"><div class="big">Nichts vorzubereiten</div>
      Sobald Rezepte mit Vorbereitungsschritten eingeplant sind, erscheint hier dein Mise en place.
      <div style="margin-top:1rem"><a class="btn btn-primary" href="#/recipes">Rezepte ansehen</a></div></div>`;
    return;
  }

  const stations = data.groups.map((g) => `
    <div class="station">
      <h3>${esc(g.preparation)}</h3>
      <ul class="check-list">
        ${g.items.map((i) => `
          <li>
            <input type="checkbox" />
            <label>${i.amount != null ? esc(fmtNum(i.amount)) + " " + esc(i.unit || "") + " " : ""}${esc(i.name)}</label>
            <span class="from">${esc(i.recipe)}</span>
          </li>`).join("")}
      </ul>
    </div>`).join("");

  app.innerHTML = `
    <div class="page-head"><div><h1>Vorbereitung</h1>
      <div class="sub">Mise en place — gleiche Handgriffe gebündelt</div></div>
      <button class="btn" id="print">Drucken</button></div>
    ${stations}
  `;
  document.getElementById("print").onclick = () => window.print();
  app.querySelectorAll(".check-list input").forEach((cb) => {
    cb.onchange = () => cb.closest("li").classList.toggle("done", cb.checked);
  });
}

/* ---------------------------- Import ------------------------------- */
function viewImport() {
  setActiveNav("recipes");
  app.innerHTML = `
    <div class="page-head"><div><h1>Rezept importieren</h1>
      <div class="sub">Aus einem Weblink oder eingefügtem Text — du prüfst alles vor dem Speichern.</div></div></div>

    <div class="card">
      <h3 style="margin-top:0">Von einer Webseite</h3>
      <div class="field"><label>Link zum Rezept</label>
        <input id="imp-url" type="url" placeholder="https://…" autocomplete="off" /></div>
      <button class="btn btn-primary" id="imp-url-btn">Von Link importieren</button>
      <div class="kv" style="margin-top:.5rem">Klappt bei den meisten Rezeptseiten (über schema.org/Recipe).</div>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Text einfügen</h3>
      <div class="field"><label>Name (optional)</label>
        <input id="imp-name" placeholder="z.B. Omas Linseneintopf" /></div>
      <div class="field"><label>Zutaten — eine pro Zeile</label>
        <textarea id="imp-text" rows="8" placeholder="200 g rote Linsen
1 Zwiebel, fein gewürfelt
2 EL Olivenöl"></textarea></div>
      <button class="btn btn-primary" id="imp-text-btn">Aus Text übernehmen</button>
    </div>

    <a class="btn btn-ghost" href="#/recipes">← Zurück</a>
  `;

  const urlBtn = document.getElementById("imp-url-btn");
  urlBtn.onclick = async () => {
    const url = document.getElementById("imp-url").value.trim();
    if (!url) { toast("Bitte einen Link einfügen"); return; }
    urlBtn.disabled = true; urlBtn.textContent = "Lade …";
    try {
      importDraft = await api.importFromUrl(url);
      toast("Rezept gefunden — bitte prüfen");
      go("#/new");
    } catch (e) {
      toast(e.message);
      urlBtn.disabled = false; urlBtn.textContent = "Von Link importieren";
    }
  };

  document.getElementById("imp-text-btn").onclick = async () => {
    const text = document.getElementById("imp-text").value;
    const name = document.getElementById("imp-name").value;
    if (!text.trim()) { toast("Bitte zuerst Zutaten einfügen"); return; }
    try {
      importDraft = await api.importFromText(text, name);
      toast("Übernommen — bitte prüfen");
      go("#/new");
    } catch (e) { toast(e.message); }
  };
}

/* ------------------------------ Router ----------------------------- */
async function router() {
  const raw = (location.hash || "#/recipes").slice(2);
  const qi = raw.indexOf("?");
  const path = qi === -1 ? raw : raw.slice(0, qi);
  const queryStr = qi === -1 ? "" : raw.slice(qi + 1);
  const parts = path.split("/"); // "recipes/3/edit" -> ["recipes","3","edit"]
  app.innerHTML = `<div class="empty">lade …</div>`;
  try {
    if (parts[0] === "recipes" && parts[1] && parts[2] === "edit") await viewEditor(parts[1]);
    else if (parts[0] === "recipes" && parts[1]) await viewRecipeDetail(parts[1]);
    else if (parts[0] === "import") await viewImport();
    else if (parts[0] === "new") await viewEditor(null);
    else if (parts[0] === "plan") await viewPlan();
    else if (parts[0] === "shopping") await viewShopping();
    else if (parts[0] === "prep") await viewPrep();
    else if (parts[0] === "pantry") await viewPantry();
    else { applyRecipesQuery(queryStr); await viewRecipes(); }
  } catch (e) {
    app.innerHTML = `<div class="empty"><div class="big">Etwas ist schiefgelaufen</div>${esc(e.message)}</div>`;
  }
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => { router(); refreshPlanBadge(); });
