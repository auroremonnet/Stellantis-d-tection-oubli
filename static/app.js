// CARE · dashboard de test
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "—" : Math.round(v * 100) + " %");
const sec = (v) => (v == null || v === "" || isNaN(v) ? "—" : Number(v).toFixed(1).replace(".", ",") + " s");
const liste = (v) => (Array.isArray(v) ? v : String(v ?? "").split(",")).map((x) => String(x).trim()).filter(Boolean);
const pluriel = (n, mot) => `${n} ${mot}${n > 1 ? "s" : ""}`;

const OBJECTIF_NCAP_S = 15; // Euro NCAP 2026 : avertissement < 15 s après le départ du conducteur
const OBJETS_DEFAUT = ["téléphone", "clés", "portefeuille", "carte bancaire", "sac", "ordinateur", "poupon", "veste", "gourde", "autre"];
const LABEL_VERITE = { vivant: "Vivant", objet: "Objet de valeur", vide: "Rien à signaler" };
const VERDICT = {
  critique: { cls: "crit", tag: "CRITIQUE", titre: "Présence vivante à bord" },
  objet: { cls: "obj", tag: "OBJET OUBLIÉ", titre: "Objet laissé dans l'habitacle" },
  aucun: { cls: "ok", tag: "RIEN À SIGNALER", titre: "Habitacle sans risque" },
};

let CONFIG = null;
let ESSAIS = [];
let THERMIQUE_MESUREE = false;
let verite = null;
let MODE = "auto";
let FILTRE = "tous";
let VERDICT_ID = "";
let MODELE_PRET = false;
let SURV_ARME = false;
const OBJETS = new Set();

const memoire = {
  lire: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  ecrire: (k, v) => { try { localStorage.setItem(k, v); } catch { /* stockage indisponible */ } },
};

// ---------------------------------------------------------------- caméras
function flux(img, sid, onState) {
  const suivant = (delai) => setTimeout(() => { img.src = `/snapshot/${sid}?t=${Date.now()}`; }, delai);
  img.onload = () => { onState(true); suivant(120); };
  img.onerror = () => { onState(false); suivant(2000); };
  suivant(0);
}

function construireCameras(e) {
  $("#cam-grid").classList.toggle("une", e.rgb.length === 1);
  $("#cam-grid").innerHTML = e.rgb.map((c) => `
    <div class="cam-tile" id="tile-${esc(c.id)}">
      <img id="img-${esc(c.id)}" alt="${esc(c.label)}">
      <span class="cam-label"><i class="dot" id="dot-${esc(c.id)}" aria-hidden="true"></i>${esc(c.label)}</span>
      <span class="cam-off" id="off-${esc(c.id)}">Connexion…</span>
    </div>`).join("");
  for (const c of e.rgb) flux($(`#img-${c.id}`), c.id, (ok) => { $(`#off-${c.id}`).hidden = ok; });
  $("#thermal").hidden = !e.thermique;
  if (e.thermique) flux($("#img-thermal"), "thermal", (ok) => { $("#off-thermal").hidden = ok; });
  $("#cams-sub").textContent = `${pluriel(e.rgb.length, "caméra")} RGB${e.thermique ? " + thermique" : ""} · vue plongeante`;
}

function pill(el, etat, texte, detail) {
  el.className = "pill " + etat;
  el.innerHTML = `<i aria-hidden="true"></i>${esc(texte)}`;
  el.setAttribute("aria-label", detail ? `${texte} : ${detail}` : texte);
  el.title = detail || "";
}

async function rafraichirEtat() {
  try {
    const e = await (await fetch("/api/etat")).json();
    $("#badge-demo").hidden = !e.demo;
    const m = e.modele;
    const moteur = { yoloe: "YOLOE (prompts)", coco: "COCO",
      hybride: m.custom ? "Hybride · YOLOE + modèle entraîné" : "YOLOE (modèle entraîné absent)" }[m.moteur] || m.moteur;
    MODELE_PRET = m.pret;
    pill($("#st-modele"), m.pret ? (m.avertissement ? "wait" : "ok") : m.erreur ? "ko" : "wait",
      m.pret ? moteur : m.erreur ? "Modèle en erreur" : "Chargement du modèle…", m.erreur || m.avertissement || m.nom);
    const n = e.rgb.filter((c) => c.ok).length;
    pill($("#st-rgb"), n === e.rgb.length ? "ok" : n ? "wait" : "ko", `Caméras ${n}/${e.rgb.length}`);
    for (const c of e.rgb) {
      const d = $(`#dot-${c.id}`);
      if (d) d.className = "dot " + (c.ok ? "ok" : "ko");
      const off = $(`#off-${c.id}`);
      if (off && !c.ok) off.textContent = c.erreur ? `Hors ligne · ${c.erreur}` : "Hors ligne";
    }
    const th = e.thermique;
    if (!th) pill($("#st-th"), "", "Thermique désactivée");
    else {
      pill($("#st-th"), th.ok ? "ok" : "ko", th.ok ? "Thermique" : "Thermique hors ligne");
      $("#dot-thermal").className = "dot " + (th.ok ? "ok" : "ko");
      $("#th-mode").textContent = th.ok ? th.mode : "—";
      $("#th-px").textContent = th.pixels_chauds ?? "—";
      $("#th-tmax").textContent = th.tmax == null ? "n/d" : th.tmax + " °C";
    }
    const a = e.alertes || {};
    pill($("#st-ntfy"), !a.actif ? "" : a.erreur ? "ko" : "ok",
      !a.actif ? "Alertes téléphone coupées" : a.erreur ? "Alertes téléphone en erreur" : "Alertes téléphone",
      a.erreur || (a.actif ? `${pluriel(a.envois || 0, "notification")} envoyée${(a.envois || 0) > 1 ? "s" : ""}` : ""));
    afficherReference(e.reference, e.demo);
  } catch { /* serveur arrêté */ }
}

// ---------------------------------------------------------------- référence habitacle vide
let REF_SIG = null;
function afficherReference(r, demo) {
  const etat = $("#ref-etat"), btn = $("#btn-ref");
  if (demo) {
    etat.textContent = "· indisponible en démo"; btn.disabled = true;
    $("#ref-thumbs").innerHTML = ""; return;
  }
  const sig = JSON.stringify(r);
  if (sig === REF_SIG) return;
  REF_SIG = sig;
  $("#btn-ref-del").hidden = !(r && r.active);
  if (!r || !r.active) {
    etat.innerHTML = '· <span class="ref-warn">aucune</span>';
    $("#ref-thumbs").innerHTML = "";
    return;
  }
  const fixes = Object.values(r.detections_fixes || {}).reduce((a, b) => a + b, 0);
  etat.textContent = `· ${(r.horodatage || "").slice(11, 16)} · ${pluriel(fixes, "objet")} fixe${fixes > 1 ? "s" : ""} ignoré${fixes > 1 ? "s" : ""}`;
  $("#ref-thumbs").innerHTML = r.cameras.map((sid) => `<figure>
    <img class="mini" loading="lazy" src="/reference/${esc(sid)}.jpg?t=${Date.now()}" alt="Référence ${esc(sid)}">
    <figcaption>${esc(sid)} · ${r.detections_fixes?.[sid] ?? 0} fixe(s)</figcaption></figure>`).join("");
}

$("#btn-ref").onclick = async () => {
  const btn = $("#btn-ref");
  btn.disabled = true; btn.textContent = "Capture…";
  try {
    const r = await fetch("/api/reference", { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    REF_SIG = null; afficherReference(d, false);
  } catch (e) { erreur(e.message); }
  finally { btn.disabled = false; btn.textContent = "Recapturer maintenant"; }
};
$("#btn-ref-del").onclick = async () => {
  const d = await (await fetch("/api/reference", { method: "DELETE" })).json();
  REF_SIG = null; afficherReference(d, false);
};

// ---------------------------------------------------------------- pilotage
function construireFormulaire() {
  const sel = $("#f-scenario");
  sel.innerHTML = CONFIG.scenarios.map((s) => `<option value="${esc(s.code)}">${esc(s.code)} · ${esc(s.nom)}</option>`).join("");
  $("#f-variante").innerHTML = CONFIG.variantes.map((v) => `<option>${esc(v)}</option>`).join("");
  const objets = CONFIG.objets_poses?.length ? CONFIG.objets_poses : OBJETS_DEFAUT;
  $("#f-objets").innerHTML = objets.map((o) => `<button type="button" class="chip" data-o="${esc(o)}" aria-pressed="false">${esc(o)}</button>`).join("");
  sel.onchange = choisirScenario;
  $("#f-variante").onchange = majCompteur;
  $("#f-verite").onclick = (ev) => { const b = ev.target.closest("[data-v]"); if (b) choisirVerite(b.dataset.v); };
  $("#f-objets").onclick = (ev) => {
    const b = ev.target.closest("[data-o]");
    if (!b) return;
    OBJETS.has(b.dataset.o) ? OBJETS.delete(b.dataset.o) : OBJETS.add(b.dataset.o);
    majPuces();
  };
  $("#f-mode").onclick = (ev) => { const b = ev.target.closest("[data-m]"); if (b) choisirMode(b.dataset.m); };
  $("#pilot").onsubmit = soumettre;
  choisirMode(memoire.lire("care-mode") === "manuel" ? "manuel" : "auto");
  choisirScenario();
}

function choisirScenario() {
  const s = CONFIG.scenarios.find((x) => x.code === $("#f-scenario").value);
  OBJETS.clear();
  for (const o of s?.objets || []) OBJETS.add(o);
  choisirVerite(s?.verite);
  majCompteur();
}

function choisirVerite(v) {
  verite = v || null;
  for (const b of $("#f-verite").children) {
    b.classList.toggle("on", b.dataset.v === verite);
    b.setAttribute("aria-pressed", b.dataset.v === verite);
  }
  $("#bloc-objets").hidden = !["objet", "vide"].includes(verite);
  majPuces();
}

function majPuces() {
  for (const b of $("#f-objets").children) {
    b.classList.toggle("on", OBJETS.has(b.dataset.o));
    b.setAttribute("aria-pressed", OBJETS.has(b.dataset.o));
  }
}

function choisirMode(m) {
  if (SURV_ARME) m = "auto"; // une surveillance armée impose le mode automatique
  MODE = m;
  memoire.ecrire("care-mode", m);
  for (const b of $("#f-mode").children) {
    b.classList.toggle("on", b.dataset.m === m);
    b.setAttribute("aria-pressed", b.dataset.m === m);
  }
  $("#aide-mode").textContent = m === "auto"
    ? "Habitacle vide, tout le monde dehors : armer. Le conducteur monte, pose ses affaires et descend ; l'analyse part seule après son départ."
    : "Portes fermées, conducteur sorti : lancer l'analyse.";
  erreur("");
  majBoutonPrincipal();
}

function majBoutonPrincipal() {
  const btn = $("#btn-principal");
  btn.disabled = SURV_ARME;
  $(".txt", btn).textContent = SURV_ARME ? "Surveillance armée" : MODE === "auto" ? "Armer la surveillance" : "Lancer l'analyse";
  $("#aide-mode").hidden = SURV_ARME;
}

// Appelé par surveillance.js : pendant une surveillance armée, le contexte de l'essai est figé
function verrouillerPilotage(arme) {
  SURV_ARME = arme;
  $("#f-contexte").disabled = arme;
  $("#f-contexte").hidden = arme; // le contexte reste rappelé dans le statut de la surveillance
  for (const b of $("#f-mode").children) b.disabled = arme;
  if (arme) choisirMode("auto"); else majBoutonPrincipal();
}

function contexteEssai() {
  return {
    scenario: $("#f-scenario").value, variante: $("#f-variante").value, verite: verite || "",
    commentaire: $("#f-commentaire").value.trim(),
    objets_poses: ["objet", "vide"].includes(verite) ? [...OBJETS] : [],
  };
}

function majCompteur() {
  const sc = $("#f-scenario").value, va = $("#f-variante").value;
  const n = ESSAIS.filter((e) => e.scenario === sc && e.variante === va).length;
  const cible = CONFIG.repetitions_cible;
  $("#compteur").textContent = `Répétition ${n + 1}${cible ? " / " + cible : ""}`;
}

function erreur(msg) {
  const el = $("#pilot-erreur");
  el.textContent = msg || "";
  el.hidden = !msg;
}

function attente(btn, actif, texte) {
  $(".spinner", btn).hidden = !actif;
  if (texte) $(".txt", btn).textContent = texte;
  btn.disabled = actif;
}

async function soumettre(ev) {
  ev.preventDefault();
  erreur("");
  const ctx = contexteEssai();
  if (!ctx.verite) return erreur("Choisis la vérité terrain.");
  if (!MODELE_PRET) return erreur("Le modèle n'est pas encore chargé.");
  if (MODE === "auto") return window.CARE_SURV?.armer(ctx);
  const btn = $("#btn-principal");
  attente(btn, true, "Analyse en cours…");
  try {
    const r = await fetch("/api/essais", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ctx) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    $("#f-commentaire").value = "";
    await chargerEssais();
    afficherVerdict(d);
  } catch (e) { erreur(e.message); }
  finally { attente(btn, false, "Lancer l'analyse"); }
}

// ---------------------------------------------------------------- verdict
// Essai manuel : la règle d'alerte considère toute personne vue comme l'opérateur présent (pas de
// notification) ; le bandeau montre donc la décision de l'analyse, comme l'ancienne carte résultat.
const NIVEAU_DECISION = { CRITIQUE: "critique", ALERTE: "objet", RAS: null };

// `e` : ligne du journal, ou résultat brut de la surveillance (essai sans vérité terrain)
function afficherVerdict(e) {
  if (!e || !e.id || e.id < VERDICT_ID) return;
  VERDICT_ID = e.id;
  const auto = e.mode === "auto";
  const decision = e.decision_A2 || e.decision_A1;
  const niveau = !auto && decision ? NIVEAU_DECISION[decision] : e.niveau_alerte ?? null;
  const V = VERDICT[niveau] || VERDICT.aucun;
  const vivants = liste(e.classes_vivant);
  if (e.vivant_thermique && !vivants.length) vivants.push("source de chaleur");
  const detecte = [...vivants, ...liste(e.objets)];
  const latence = auto ? e.latence_alerte_s : e.latence_s;
  const ncap = auto && latence != null && latence !== ""
    ? `<span class="badge ${Number(latence) <= OBJECTIF_NCAP_S ? "ok" : "ko"}">${Number(latence) <= OBJECTIF_NCAP_S ? "✓" : "✗"} objectif Euro NCAP ≤ ${OBJECTIF_NCAP_S} s</span>` : "";
  const th = e.vivant_thermique;
  const el = $("#verdict");
  el.className = "verdict " + V.cls;
  el.innerHTML = `
    <div class="verdict-main">
      <div class="verdict-txt">
        <span class="verdict-tag">${V.tag}</span>
        <strong>${V.titre}</strong>
        <span class="verdict-det">${detecte.length ? "Détecté : " + esc(detecte.join(", ")) : "Aucune détection"}</span>
      </div>
      <div class="verdict-lat">
        <b>${sec(latence)}</b>
        <span>${auto ? "départ → verdict" : "durée d'analyse"}</span>
        ${ncap}
      </div>
      ${e.image === false ? "" : `<img class="verdict-img" src="/images/${esc(e.id)}_rgb.jpg" alt="Image annotée de l'essai" onerror="this.remove()">`}
    </div>
    <details class="verdict-details">
      <summary>Détails</summary>
      <dl class="kv">
        <dt>Essai</dt><dd>${esc(e.scenario || "—")} · ${esc(e.variante || "")} · vérité <b>${esc(LABEL_VERITE[e.verite] || "non renseignée")}</b> · ${auto ? "automatique" : "manuel"}${e.horodatage || e.verite ? "" : ' · <span class="ref-warn">non journalisé (sans vérité terrain)</span>'}</dd>
        <dt>Objets posés</dt><dd>${esc(liste(e.objets_poses).join(", ")) || '<span class="no">non renseignés</span>'}</dd>
        <dt>Vivant (RGB)</dt><dd>${e.vivant_rgb ? `<span class="yes">oui</span> · ${esc(liste(e.classes_vivant).join(", "))}` : '<span class="no">rien de vivant</span>'}</dd>
        <dt>Thermique</dt><dd>${th == null ? '<span class="no">non utilisée</span>' : th ? `<span class="yes">chaud</span> · ${esc(e.pixels_chauds)} px${e.tmax ? " · " + esc(e.tmax) + " °C" : ""}` : `<span class="no">rien</span> · ${esc(e.pixels_chauds)} px`}</dd>
        <dt>Objets détectés</dt><dd>${esc(liste(e.objets).join(", ")) || '<span class="no">aucun</span>'}</dd>
        <dt>Référence</dt><dd>${e.reference_utilisee
          ? `utilisée · ${pluriel(Number(e.zones_nouvelles) || 0, "zone")} nouvelle${Number(e.zones_nouvelles) > 1 ? "s" : ""}${e.lumiere_changee ? ' · <span class="ref-warn">lumière changée, zones ignorées</span>' : ""}`
          : '<span class="no">non utilisée</span>'}</dd>
        ${e.A1 ? `<dt>Évaluation</dt><dd>A1 ${tag(e.A1)}${e.A2 ? " &nbsp; A2 " + tag(e.A2) : ""}</dd>` : ""}
        <dt>Analyse</dt><dd>${sec(e.latence_s)}</dd>
      </dl>
    </details>`;
  el.hidden = false;
  document.querySelectorAll(".cam-tile.hit").forEach((t) => t.classList.remove("hit"));
  for (const id of liste(e.cameras_vivant)) $(`#tile-${CSS.escape(id)}`)?.classList.add("hit");
}

const tag = (r) => (r ? `<span class="tag ${r}">${r}</span>` : '<span class="tag na">—</span>');

// ---------------------------------------------------------------- données
async function chargerEssais() {
  const d = await (await fetch("/api/essais")).json();
  ESSAIS = d.essais;
  THERMIQUE_MESUREE = d.metriques.thermique_mesuree;
  document.body.classList.toggle("sans-thermique", !THERMIQUE_MESUREE);
  afficherKpis(d.metriques.indicateurs);
  afficherParObjet(d.metriques.par_objet);
  afficherGraphique(d.metriques.scenarios);
  afficherTable();
  majCompteur();
}

function tuile({ titre, valeur, unite, sous, pied, badge, vide }) {
  return `<div class="card kpi${vide ? " kpi-vide" : ""}">
    <h3>${titre}</h3>
    <div class="hero">${valeur}${unite ? `<small>${unite}</small>` : ""}</div>
    <div class="kpi-sous">${sous}</div>
    ${badge || ""}
    ${pied ? `<div class="kpi-pied">${pied}</div>` : ""}
  </div>`;
}

function afficherKpis(ind) {
  const v = ind.vivant, o = ind.objets, f = ind.fausses_alertes, l = ind.latence;
  const approche = { A2: "Approche A2 · RGB + thermique", A1: "Approche A1 · RGB seul", "A1/A2": "A2 si thermique mesurée, sinon A1" }[v.approche];
  $("#kpis").innerHTML = [
    tuile({ titre: "Présences vivantes détectées", valeur: pct(v.taux), vide: v.taux == null,
      sous: v.n ? `${v.detectes} / ${pluriel(v.n, "essai")} « vivant »` : "Aucun essai « vivant » pour l'instant",
      pied: approche }),
    tuile({ titre: "Objets oubliés détectés", valeur: pct(o.taux), vide: o.taux == null,
      sous: o.n ? `${o.detectes} / ${pluriel(o.n, "essai")} « objet » avec alerte objet` : "Aucun essai « objet » pour l'instant" }),
    tuile({ titre: "Fausses alertes", valeur: pct(f.taux), vide: f.taux == null,
      sous: f.n ? `${f.alertes} / ${pluriel(f.n, "essai")} sans risque ont alerté` : "Aucun essai « rien à signaler » pour l'instant",
      pied: f.n ? "Plus bas = mieux" : "" }),
    tuile({ titre: "Latence d'alerte", valeur: l.moyenne == null ? "—" : sec(l.moyenne).replace(" s", ""), unite: l.moyenne == null ? "" : "s en moyenne",
      vide: l.moyenne == null,
      sous: l.n ? `pire cas <b>${sec(l.pire)}</b> · ${pluriel(l.n, "essai")} auto` : "Aucun essai automatique pour l'instant",
      badge: l.conforme == null ? "" : `<span class="badge ${l.conforme ? "ok" : "ko"}">${l.conforme ? "✓ conforme" : "✗ hors objectif"} · Euro NCAP 2026 ≤ ${l.objectif_s} s</span>`,
      pied: "Départ du conducteur → verdict" }),
  ].join("");
}

// Détection par objet : barres horizontales, une par objet posé
function afficherParObjet(rows) {
  const el = $("#par-objet");
  $("#legend-objets").hidden = !rows.length;
  if (!rows.length) {
    el.innerHTML = `<p class="muted">Pas encore de données. Renseigne « Objet(s) posé(s) » dans le pilotage lors des essais
      S5 (objets de valeur) et S6 (objets anodins) : chaque objet aura ici son taux de détection.</p>`;
    return;
  }
  const GROUPES = [
    { cat: "valeur", titre: "Objets de valeur", note: "doivent être retrouvés : plus haut = mieux" },
    { cat: "anodin", titre: "Objets anodins", note: "ne devraient pas déclencher d'alerte : plus bas = mieux" },
    { cat: "vivant", titre: "Présences", note: "" },
  ];
  const ligne = (a) => {
    const anodin = a.categorie === "anodin";
    const principal = anodin ? a.taux_signale : a.taux;
    const faible = a.n < 5 ? '<span class="faible" title="Moins de 5 essais : à confirmer">peu d\'essais</span>' : "";
    const valeur = anodin
      ? `<b>${pct(a.taux_signale)}</b><span>signalé à tort</span>`
      : a.identifiable
        ? `<b>${pct(a.taux)}</b><span>identifié · ${pct(a.taux_signale)} signalé</span>`
        : `<b>${pct(a.taux_signale)}</b><span>signalé</span>`;
    return `<div class="obj-row${anodin ? " anodin" : ""}">
      <div class="obj-nom"><span>${esc(a.objet)}</span><small>${pluriel(a.n, "essai")} ${faible}</small></div>
      <div class="obj-barre" aria-hidden="true">
        <span class="sig" style="width:${Math.round((a.taux_signale || 0) * 100)}%"></span>
        ${anodin || !a.identifiable ? "" : `<span class="id" style="width:${Math.round((principal || 0) * 100)}%"></span>`}
      </div>
      <div class="obj-val">${valeur}</div>
    </div>`;
  };
  el.innerHTML = GROUPES.map((g) => {
    const rs = rows.filter((a) => a.categorie === g.cat);
    if (!rs.length) return "";
    return `<div class="obj-groupe"><h3>${g.titre}${g.note ? ` <span class="muted">· ${g.note}</span>` : ""}</h3>
      ${rs.map(ligne).join("")}</div>`;
  }).join("");
}

// Barres horizontales A1 (et A2 si thermique mesurée) par scénario
function afficherGraphique(rows) {
  const el = $("#chart");
  $("#legend-a2").hidden = !THERMIQUE_MESUREE;
  if (!rows.length) { el.innerHTML = '<p class="muted">Pas encore de données.</p>'; return; }
  const approches = THERMIQUE_MESUREE ? [["A1", "var(--a1)"], ["A2", "var(--a2)"]] : [["A1", "var(--a1)"]];
  const noms = Object.fromEntries(CONFIG.scenarios.map((s) => [s.code, s.nom]));
  const W = el.clientWidth || 900, etroit = W < 560; // écran étroit : libellé au-dessus des barres
  const gauche = etroit ? 0 : Math.min(300, W * 0.34), droite = 48, haut = etroit ? 18 : 0;
  const barH = 14, gap = 3, rowH = haut + approches.length * (barH + gap) - gap + 18, H = rows.length * rowH + 26;
  const x = (v) => gauche + (W - gauche - droite) * v;
  let svg = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Résultats par scénario"><g class="grid">`;
  for (const t of [0, 0.25, 0.5, 0.75, 1]) svg += `<line x1="${x(t)}" x2="${x(t)}" y1="0" y2="${H - 22}"/><text x="${x(t)}" y="${H - 6}" text-anchor="middle">${t * 100} %</text>`;
  svg += "</g>";
  rows.forEach((r, i) => {
    const y0 = i * rowH + 6;
    const lib = `${r.scenario} · ${noms[r.scenario] || ""}`;
    svg += `<g class="row" data-i="${i}"><rect class="bg" x="0" y="${y0 - 4}" width="${W}" height="${rowH - 4}" rx="6" fill="transparent"/>`;
    const court = esc(lib.length > 44 ? lib.slice(0, 43) + "…" : lib);
    svg += etroit ? `<text x="0" y="${y0 + 10}">${court}</text>`
      : `<text x="${gauche - 12}" y="${y0 + (rowH - 18) / 2 + 4}" text-anchor="end">${court}</text>`;
    approches.forEach(([a, c], k) => {
      const y = y0 + haut + k * (barH + gap), v = r[a];
      if (v == null) { svg += `<text x="${x(0) + 4}" y="${y + barH - 2}" style="fill:var(--muted)">${a} : pas de mesure</text>`; return; }
      const w = Math.max(x(v) - x(0), 2);
      svg += `<path d="M${x(0)},${y} h${Math.max(w - 4, 0)} a4,4 0 0 1 4,4 v${barH - 8} a4,4 0 0 1 -4,4 h${-Math.max(w - 4, 0)} z" fill="${c}"/>`;
      svg += `<text class="val" x="${x(0) + w + 6}" y="${y + barH - 2}">${Math.round(v * 100)} %</text>`;
    });
    svg += `<rect class="hit" x="0" y="${y0 - 4}" width="${W}" height="${rowH - 4}"/></g>`;
  });
  el.innerHTML = svg + "</svg>";
  const tip = $("#tooltip");
  el.querySelectorAll("g.row").forEach((g) => {
    const r = rows[+g.dataset.i];
    const metr = r.verite === "vivant" ? "Rappel" : "Bonne non-alerte";
    g.onmousemove = (ev) => {
      tip.hidden = false;
      tip.innerHTML = `<b>${esc(r.scenario)} · ${esc(noms[r.scenario] || "")}</b><br>${metr}<br>
        A1 : ${pct(r.A1)} <span style="opacity:.7">(${r.A1_n} essais)</span>` +
        (THERMIQUE_MESUREE ? `<br>A2 : ${pct(r.A2)} <span style="opacity:.7">(${r.A2_n} essais)</span>` : "");
      tip.style.left = Math.min(ev.clientX + 14, innerWidth - 290) + "px";
      tip.style.top = ev.clientY + 14 + "px";
    };
    g.onmouseleave = () => { tip.hidden = true; };
  });
}

const NIVEAU = { critique: '<span class="tag crit">critique</span>', objet: '<span class="tag obj">objet</span>' };

function afficherTable() {
  const rows = ESSAIS.filter((e) => FILTRE === "tous" || (FILTRE === "auto") === (e.mode === "auto"));
  $("#nb-essais").textContent = `· ${rows.length}${FILTRE === "tous" ? "" : " / " + ESSAIS.length}`;
  const tb = $("#table tbody");
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="14" class="muted">${ESSAIS.length ? "Aucun essai dans ce mode." : "Aucun essai enregistré."}</td></tr>`;
    return;
  }
  tb.innerHTML = rows.map((e) => {
    const det = [...liste(e.classes_vivant), ...liste(e.objets)];
    return `<tr>
    <td>${esc(e.horodatage.slice(11, 16))}<div class="muted small">${esc(e.horodatage.slice(0, 10))}</div></td>
    <td><span class="mode-${e.mode === "auto" ? "auto" : "manuel"}">${e.mode === "auto" ? "auto" : "manuel"}</span></td>
    <td><b>${esc(e.scenario)}</b><div class="muted small">${esc(e.variante)}</div></td>
    <td>${LABEL_VERITE[e.verite] || esc(e.verite)}</td>
    <td>${esc(liste(e.objets_poses).join(", ")) || '<span class="no">—</span>'}</td>
    <td>${esc(det.join(", ")) || '<span class="no">—</span>'}</td>
    <td>${NIVEAU[e.niveau_alerte] || '<span class="no">—</span>'}</td>
    <td>${tag(e.A1)}</td><td class="col-a2">${tag(e.A2)}</td>
    <td class="num">${e.reference_utilisee ? esc(e.zones_nouvelles || 0) : '<span class="no">n/a</span>'}</td>
    <td class="num">${sec(e.latence_s)}</td>
    <td class="num">${e.mode === "auto" ? sec(e.latence_alerte_s) : '<span class="no">—</span>'}</td>
    <td>${e.image ? `<img class="mini" src="/images/${esc(e.id)}_rgb.jpg" onerror="this.remove()" alt="Essai ${esc(e.id)}">` : '<span class="no">—</span>'}</td>
    <td><button class="del" type="button" data-id="${esc(e.id)}" aria-label="Supprimer l'essai ${esc(e.id)}" title="Supprimer cet essai">×</button></td>
  </tr>`;
  }).join("");
}

$("#f-filtre").onclick = (ev) => {
  const b = ev.target.closest("[data-f]");
  if (!b) return;
  FILTRE = b.dataset.f;
  for (const x of $("#f-filtre").children) {
    x.classList.toggle("on", x === b);
    x.setAttribute("aria-pressed", x === b);
  }
  afficherTable();
};

$("#table").addEventListener("click", async (ev) => {
  const b = ev.target.closest(".del");
  if (b && confirm("Supprimer cet essai du journal ?")) {
    b.textContent = "…";
    await fetch(`/api/essais/${encodeURIComponent(b.dataset.id)}`, { method: "DELETE" });
    chargerEssais();
  }
});

// Agrandir une image
document.addEventListener("click", (ev) => {
  const img = ev.target.closest(".verdict-img, .mini");
  const lb = $("#lightbox");
  if (img) { $("img", lb).src = img.src; $("img", lb).alt = img.alt; lb.hidden = false; }
  else if (ev.target.closest("#lightbox")) lb.hidden = true;
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("#lightbox").hidden = true; });

let _rz;
window.addEventListener("resize", () => { clearTimeout(_rz); _rz = setTimeout(chargerEssais, 250); });

// ---------------------------------------------------------------- démarrage
(async () => {
  CONFIG = await (await fetch("/api/config")).json();
  const e = await (await fetch("/api/etat")).json();
  construireCameras(e);
  $("#surv-demo").hidden = !e.demo;
  construireFormulaire();
  await rafraichirEtat();
  setInterval(rafraichirEtat, 2000);
  await chargerEssais();
  if (ESSAIS.length) afficherVerdict(ESSAIS[0]); // dernier essai : le verdict reste visible après un rechargement
})();
