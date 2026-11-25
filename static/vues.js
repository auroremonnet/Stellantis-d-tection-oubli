/* Vues Démo, Capteurs et Résultats. La vue Essais garde app.js et surveillance.js. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "—" : Math.round(v * 100) + " %");
const json = async (url, options) => {
  const r = await fetch(url, options);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.erreur || `Erreur ${r.status}`);
  return d;
};
const post = (url, corps) => json(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps || {}) });
const liste = (v) => (Array.isArray(v) ? v : String(v || "").split(",").map((x) => x.trim()).filter(Boolean));

function pill(el, etat, texte) { if (el) { el.className = "pill " + etat; el.innerHTML = `<i></i>${esc(texte)}`; } }
function chip(el, etat, texte) { if (el) { el.className = "chip " + etat; el.textContent = texte; } }

function flux(img, sid, onState = () => {}) {
  const suivant = (delai) => setTimeout(() => { if (img.dataset.fige !== "1") img.src = `/snapshot/${sid}?t=${Date.now()}`; else suivant(500); }, delai);
  img.onload = () => { onState(true); suivant(150); };
  img.onerror = () => { onState(false); suivant(2000); };
  suivant(0);
}

function tuilesCameras(conteneur, rgb) {
  if (conteneur.dataset.sig === rgb.map((c) => c.id).join()) return;
  conteneur.dataset.sig = rgb.map((c) => c.id).join();
  conteneur.innerHTML = rgb.map((c) => `<div class="cam-tile" id="tile-${c.id}">
    <img alt="${esc(c.label)}"><span class="cam-label"><span class="dot" id="dot-${c.id}"></span>${esc(c.label)}</span>
    <div class="cam-off" id="off-${c.id}" hidden>Hors ligne</div></div>`).join("");
  for (const c of rgb) flux($(`#tile-${c.id} img`), c.id, (ok) => { const off = $(`#off-${c.id}`); if (off) off.hidden = ok; });
}

let ETAT = null;
const ECOUTEURS = [];
async function rafraichirEtat() {
  try {
    const e = ETAT = await json("/api/etat");
    $("#badge-demo").hidden = !e.demo;
    const n = e.rgb.filter((c) => c.ok).length;
    pill($("#st-rgb"), n === e.rgb.length ? "ok" : n ? "wait" : "ko", `Caméras ${n}/${e.rgb.length}`);
    pill($("#st-th"), !e.thermique ? "" : e.thermique.ok ? "ok" : "ko", !e.thermique ? "Thermique désactivée" : e.thermique.ok ? "Thermique" : "Thermique hors ligne");
    const au = e.audio, auOk = au.mesure.audio_statut === "ok";
    pill($("#st-audio"), !au.active ? "" : au.erreur ? "ko" : auOk ? "ok" : "wait", !au.active ? "Micro désactivé" : au.erreur ? "Micro en erreur" : auOk ? "Micro en écoute" : "Micro en chargement");
    const al = e.alertes;
    pill($("#st-notif"), !al.actif ? "" : !al.configure || al.erreur ? "ko" : "ok",
      !al.actif ? "Notifications coupées" : !al.configure ? "Téléphone non configuré" : al.erreur ? "Notification en erreur" : "Téléphone prêt");
    $("#st-notif").title = al.erreur || "";
    for (const c of e.rgb) { const d = $(`#dot-${c.id}`); if (d) d.className = "dot " + (c.ok ? (c.probleme ? "wait" : "ok") : "ko"); }
    ECOUTEURS.forEach((f) => f(e));
  } catch { /* serveur arrêté */ }
}

const SONS = [["pleurs", "Pleurs"], ["aboiement", "Aboiement"], ["miaulement", "Miaulement"]];
function scoresMicro(ul, mesure) {
  ul.innerHTML = SONS.map(([cle, nom]) => {
    const s = mesure ? mesure[`${cle}_score`] : null;
    const v = s == null || s === "" ? null : Number(s);
    return `<li><span>${nom}</span><div class="mini-barre"><i style="width:${v == null ? 0 : Math.round(v * 100)}%"></i></div><b>${v == null ? "—" : Math.round(v * 100) + " %"}</b></li>`;
  }).join("");
}

/* ============================== Démo ============================== */
function vueDemo() {
  const ORDRE = ["veille", "occupe", "sortie", "analyse", "alerte"];
  const CIBLE = 15;
  let surv = null, envoisDepart = null;

  const libelles = (r) => {
    const el = [];
    if (r.vivant_rgb) el.push(`présence vue par les caméras${liste(r.classes_vivant).length ? ` (${liste(r.classes_vivant).join(", ")})` : ""}`);
    if (r.vivant_thermique) el.push("source de chaleur");
    if (liste(r.sons_audio).length) el.push(`son reconnu : ${liste(r.sons_audio).join(", ")}`);
    if (liste(r.objets).length) el.push(`objets : ${liste(r.objets).join(", ")}`);
    return el;
  };

  function verdict(s) {
    const r = s.dernier_resultat, box = $("#d-verdict");
    let cls = "", sur = "Surveillance armée", titre = "", detail = "", chrono = null, texteChrono = "";
    if (s.erreur) { cls = "crit"; titre = "Erreur"; detail = s.erreur; }
    else if (!s.actif) { sur = "Surveillance désarmée"; titre = "Prêt pour la démonstration"; detail = "Armez la surveillance : l'habitacle vide sert de référence, puis le système suit le conducteur."; }
    else if (s.etat === "occupe") { titre = "Conducteur à bord"; detail = "Aucune alerte tant qu'un adulte est dans le véhicule."; }
    else if (s.etat === "sortie") { titre = "Le conducteur est sorti"; detail = "On lui laisse le temps de revenir avant de vérifier l'habitacle."; chrono = s.compte_a_rebours_s; texteChrono = "avant la vérification"; }
    else if (s.etat === "analyse") { cls = "encours"; titre = "Analyse de l'habitacle"; detail = "Caméras, thermique et micro sont interrogés en même temps."; }
    else if (s.etat === "alerte") {
      const critique = s.niveau_alerte === "critique";
      cls = critique ? "crit" : "obj";
      sur = critique ? "Alerte critique" : "Alerte";
      titre = critique ? "Présence détectée dans le véhicule" : "Objet de valeur oublié";
      detail = r ? libelles(r).join(" · ") : "";
      chrono = s.latence_alerte_s; texteChrono = `après le départ du conducteur · cible ${CIBLE} s`;
    } else if (r) { cls = "ok"; titre = "Rien à signaler"; detail = "Dernière analyse : habitacle sans risque. Aucune notification envoyée."; chrono = r.latence_alerte_s ?? null; texteChrono = `pour décider · cible ${CIBLE} s`; }
    else { titre = "Véhicule en veille"; detail = "En attente du conducteur."; }
    box.className = "card d-verdict " + cls;
    $("#d-sur").textContent = sur; $("#d-titre").textContent = titre; $("#d-detail").textContent = detail;
    $("#d-chrono").hidden = chrono == null;
    if (chrono != null) {
      const v = Number(chrono), decompte = s.etat === "sortie";
      $("#d-delai").textContent = v.toFixed(1).replace(".", ",");
      $("#d-chrono-txt").textContent = texteChrono;
      $(".d-jauge").hidden = decompte;
      $("#d-jauge-val").style.width = Math.min(100, (v / (CIBLE * 4 / 3)) * 100) + "%";
      $("#d-jauge-val").className = v <= CIBLE ? "ok" : "ko";
      $("#d-jauge-cible").textContent = `${CIBLE} s`;
    }
    $("#d-armer").hidden = s.actif; $("#d-desarmer").hidden = !s.actif;
    $("#d-verrou").hidden = !s.actif || !["veille", "occupe", "sortie"].includes(s.etat) || (ETAT && ETAT.demo);
    $("#d-acquitter").hidden = s.etat !== "alerte";
    $("#d-simu").hidden = !(ETAT && ETAT.demo);
    $$("#d-simu button").forEach((b) => { b.disabled = !s.actif; });
    $("#d-oubli").disabled = s.actif;
  }

  function etapes(s) {
    let i = ORDRE.indexOf(s.etat);
    const fini = s.actif && s.etat === "veille" && s.dernier_resultat;
    if (fini) i = 4;
    const niveau = s.etat === "alerte" ? (s.niveau_alerte === "critique" ? "crit" : "obj") : fini ? "ok" : "";
    $$("#d-etapes li").forEach((li, k) => { li.className = !s.actif ? "" : (k === i ? "on " + niveau : k < i ? "fait" : ""); });
  }

  function preuves(s) {
    const montrer = s.dernier_resultat && (s.etat === "alerte" || (s.etat === "veille" && s.actif));
    const r = montrer ? s.dernier_resultat : null;
    const e = ETAT;
    // caméras : image annotée de l'analyse, sinon le direct
    const vue = $("#p-rgb-vue");
    if (r && vue.dataset.essai !== r.id) {
      vue.dataset.essai = r.id; vue.dataset.sig = "";
      vue.className = "preuve-vue";
      vue.innerHTML = `<img class="preuve-img" alt="Images analysées" src="/images/${encodeURIComponent(r.id)}_rgb.jpg">`;
      $("img", vue).onerror = () => { vue.dataset.essai = "x"; vue.className = "preuve-vue cam-grid"; if (e) tuilesCameras(vue, e.rgb); };
    } else if (!r && e && (vue.dataset.essai || !vue.dataset.sig)) { vue.dataset.essai = ""; vue.className = "preuve-vue cam-grid"; vue.dataset.sig = ""; tuilesCameras(vue, e.rgb); }
    const enLigne = e ? e.rgb.filter((c) => c.ok).length : 0;
    if (!r) { chip($("#p-rgb-chip"), enLigne ? "" : "ko", enLigne ? "En direct" : "Hors ligne"); $("#p-rgb-txt").textContent = e ? `${enLigne} caméra${enLigne > 1 ? "s" : ""} sur ${e.rgb.length} en ligne.` : ""; }
    else {
      const objets = liste(r.objets), aveugles = liste(r.cameras_aveugles);
      chip($("#p-rgb-chip"), r.vivant_rgb ? "crit" : objets.length ? "obj" : "ok", r.vivant_rgb ? "Présence vue" : objets.length ? "Objet vu" : "Rien vu");
      $("#p-rgb-txt").textContent = [r.vivant_rgb && `Présence sur ${liste(r.cameras_vivant).join(", ") || "une caméra"}${liste(r.classes_vivant).length ? ` : ${liste(r.classes_vivant).join(", ")}` : ""}.`,
        objets.length && `Objets : ${objets.join(", ")}.`, !r.vivant_rgb && !objets.length && "Aucun objet nouveau, aucune présence.",
        aveugles.length && `Trop sombre pour ${aveugles.join(", ")}.`].filter(Boolean).join(" ");
    }
    // thermique
    const th = e && e.thermique;
    $("#p-th-off").hidden = !!(th && th.ok); if (!th) $("#p-th-off").textContent = "Désactivée";
    if (!th || !th.ok) { chip($("#p-th-chip"), "ko", th ? "Hors ligne" : "Désactivée"); $("#p-th-txt").textContent = "Capteur indisponible : la décision repose sur les caméras et le micro."; }
    else if (!r) { chip($("#p-th-chip"), "", "En direct"); $("#p-th-txt").textContent = th.ecart_max == null ? `Méthode : ${th.methode}.` : `Écart le plus fort : ${th.ecart_max} ${th.unite} · seuil ${th.seuil}.`; }
    else {
      chip($("#p-th-chip"), r.vivant_thermique ? "crit" : "ok", r.vivant_thermique ? "Source de chaleur" : "Rien de chaud");
      $("#p-th-txt").textContent = r.vivant_thermique ? `${r.pixels_chauds} pixels plus chauds que l'habitacle vide.` : "Aucune zone plus chaude que la référence.";
    }
    // micro
    const au = e && e.audio, mesure = r || (au && au.mesure);
    scoresMicro($("#p-mic-scores"), mesure);
    $("#p-mic-niveau").style.width = au && au.niveau_db != null ? Math.max(0, Math.min(100, ((au.niveau_db + 60) / 60) * 100)) + "%" : "0";
    const statut = mesure ? mesure.audio_statut : "";
    if (statut !== "ok") { chip($("#p-mic-chip"), statut === "erreur" ? "ko" : "", statut === "erreur" ? "Indisponible" : statut === "desactive" ? "Désactivé" : "En chargement"); $("#p-mic-txt").textContent = statut === "erreur" ? "Micro indisponible : la décision repose sur les caméras et la thermique." : ""; }
    else if (!r) { chip($("#p-mic-chip"), "", "En écoute"); $("#p-mic-txt").textContent = mesure.son_general ? `Son ambiant : ${mesure.son_general}.` : "Aucun son ciblé."; }
    else { const sons = liste(r.sons_audio); chip($("#p-mic-chip"), sons.length ? "crit" : "ok", sons.length ? "Son reconnu" : "Rien entendu"); $("#p-mic-txt").textContent = sons.length ? `Reconnu : ${sons.join(", ")}.` : "Ni pleurs, ni aboiement, ni miaulement."; }
    // téléphone
    const al = e && e.alertes;
    if (al && envoisDepart == null) envoisDepart = al.envois;
    const bulle = $("#p-notif-bulle"), a = r && r.alerte;
    if (a && s.etat === "alerte") { bulle.className = "tel-bulle " + (s.niveau_alerte === "critique" ? "crit" : "obj"); bulle.innerHTML = `<b>${esc(a.titre)}</b>${esc(a.message)}<span>Je m'en occupe</span>`; }
    else { bulle.className = "tel-bulle vide"; bulle.textContent = "Aucune notification"; }
    if (al) {
      const envoyee = a && s.etat === "alerte" && al.envois > envoisDepart && !al.erreur;
      chip($("#p-notif-chip"), !al.actif ? "" : !al.configure || al.erreur ? "ko" : envoyee ? "crit" : "ok",
        !al.actif ? (e.demo ? "Simulée" : "Coupées") : !al.configure ? "Non configuré" : al.erreur ? "Échec d'envoi" : envoyee ? "Envoyée" : "Prêt");
      $("#p-notif-txt").textContent = !al.actif ? (e.demo ? "Aucun envoi en mode démo : la notification affichée est celle qui partirait." : "Notifications désactivées dans la configuration.")
        : !al.configure ? "Le topic ntfy n'est pas renseigné sur ce PC : rien ne part vers le téléphone."
        : al.erreur ? `Dernier envoi refusé : ${al.erreur}` : envoyee ? `Reçue sur le téléphone${s.rappels ? ` · ${s.rappels} rappel${s.rappels > 1 ? "s" : ""}` : ""}.`
        : `${al.envois} notification${al.envois > 1 ? "s" : ""} envoyée${al.envois > 1 ? "s" : ""} depuis le lancement.`;
    }
  }

  async function suivre() {
    try {
      const s = surv = await json("/api/surveillance");
      verdict(s); etapes(s); preuves(s);
      $("#d-histo").innerHTML = (s.historique || []).slice(0, 8).map((h) => `<li><span class="muted">${esc(h.heure)}</span> ${esc(h.detail)}</li>`).join("") || '<li class="muted">Rien pour l\'instant.</li>';
    } catch { /* serveur arrêté */ }
  }
  const action = async (bouton, f) => {
    bouton.disabled = true; $("#d-erreur").hidden = true;
    try { await f(); await suivre(); } catch (err) { $("#d-erreur").textContent = err.message; $("#d-erreur").hidden = false; }
    bouton.disabled = false;
  };
  $("#d-armer").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/armer", ETAT && ETAT.demo ? { verite: $("#d-oubli").value } : {}));
  $("#d-desarmer").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/desarmer"));
  $("#d-verrou").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/verrouiller"));
  $("#d-acquitter").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/acquitter"));
  $("#d-simu").onclick = (ev) => { const b = ev.target.closest("button"); if (b) action(b, () => post("/api/surveillance/demo", { occupant: b.dataset.occupant === "1" })); };
  flux($("#p-th-img"), "thermal");
  ECOUTEURS.push(() => { if (surv) { verdict(surv); preuves(surv); } });
  suivre(); setInterval(suivre, 500);
}

/* ============================== Capteurs ============================== */
function vueCapteurs() {
  const choisir = (nom) => {
    $$(".onglets button").forEach((b) => b.classList.toggle("on", b.dataset.onglet === nom));
    $$(".capteur").forEach((s) => { s.hidden = s.dataset.capteur !== nom; });
    history.replaceState(null, "", "#" + nom);
  };
  $$(".onglets button").forEach((b) => { b.onclick = () => choisir(b.dataset.onglet); });
  if (["rgb", "thermique", "micro"].includes(location.hash.slice(1))) choisir(location.hash.slice(1));
  flux($("#c-th-img"), "thermal", (ok) => { $("#c-th-off").hidden = ok; });

  const dl = (el, paires) => { el.innerHTML = paires.filter((p) => p[1] != null && p[1] !== "").map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join(""); };
  const niveaux = [];
  function courbe() {
    const c = $("#c-mic-courbe"), g = c.getContext("2d"), w = c.width, h = c.height;
    g.clearRect(0, 0, w, h);
    g.strokeStyle = "#e4e6ec"; g.lineWidth = 1;
    for (const db of [-60, -40, -20, 0]) { const y = h - ((db + 60) / 60) * (h - 16) - 8; g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
    if (!niveaux.length) return;
    g.strokeStyle = "#243782"; g.lineWidth = 2; g.beginPath();
    niveaux.forEach((v, i) => { const x = (i / 89) * w, y = h - ((Math.max(-60, Math.min(0, v)) + 60) / 60) * (h - 16) - 8; if (i) g.lineTo(x, y); else g.moveTo(x, y); });
    g.stroke();
  }
  ECOUTEURS.push((e) => {
    tuilesCameras($("#c-rgb-vue"), e.rgb);
    const n = e.rgb.filter((c) => c.ok).length;
    $("#c-rgb-etat").textContent = `${n} sur ${e.rgb.length} en ligne · référence ${e.reference && e.reference.horodatage ? "capturée" : "non capturée"}`;
    const th = e.thermique;
    $("#c-th-etat").textContent = !th ? "désactivée" : th.ok ? `${th.mode} · méthode ${th.methode}` : "hors ligne";
    dl($("#c-th-mesure"), th && th.ok ? [["Résolution", th.resolution], ["Unité", th.unite], ["Écart le plus fort", th.ecart_max == null ? "pas de référence" : `${th.ecart_max}`], ["Seuil d'écart", th.seuil], ["Pixels chauds", th.pixels_chauds]] : []);
    const au = e.audio, m = au.mesure;
    $("#c-mic-etat").textContent = !au.active ? "désactivé" : au.erreur ? `en erreur : ${au.erreur}` : au.micro || m.audio_statut;
    scoresMicro($("#c-mic-scores"), m);
    $("#c-mic-son").textContent = m.audio_statut === "ok" ? (m.son_general ? `Son ambiant reconnu : ${m.son_general}` : "Aucun son identifié avec assez de certitude.") : "";
    if (au.niveau_db != null) { niveaux.push(au.niveau_db); if (niveaux.length > 90) niveaux.shift(); }
    courbe();
  });

  const ligne = (t, texteVide) => (t.n ? `<b>${pct(t.valeur)}</b><span>${t.k} sur ${t.n} · entre ${pct(t.bas)} et ${pct(t.haut)}</span>` : `<b>—</b><span>${texteVide}</span>`);
  const bloc = (c, extra = "") => `
    <div class="res-ligne"><h4>Présences détectées</h4>${ligne(c.rappel, "aucun essai enfant ou animal avec ce capteur")}</div>
    <div class="res-ligne"><h4>Fausses présences</h4>${ligne(c.fausses_presences, "aucun essai sans présence avec ce capteur")}</div>
    <div class="res-ligne"><h4>Seul à avoir détecté</h4><b>${c.rappel.n ? c.seul_a_detecter : "—"}</b><span>présences que les deux autres capteurs ont ratées</span></div>${extra}`;
  Promise.all([json("/api/resultats"), json("/api/config")]).then(([res, cfg]) => {
    const c = res.capteurs, rg = cfg.reglages, d = cfg.detection;
    const objets = c.rgb.objets_nommes.map((o) => `${esc(o.libelle)} (${o.essais})`).join(", ");
    $("#c-rgb-res").innerHTML = bloc(c.rgb, `<div class="res-ligne"><h4>Objets de valeur signalés</h4>${ligne(c.rgb.objets, "aucun essai objet")}</div>${objets ? `<p class="small muted">Objets nommés : ${objets}</p>` : ""}`);
    $("#c-th-res").innerHTML = bloc(c.thermique);
    $("#c-mic-res").innerHTML = bloc(c.micro);
    dl($("#c-rgb-reglages"), [["Moteur", d.moteur], ["Confiance pour garder un objet", rg.detection.seuil_objet], ["Confiance si deux modèles d'accord", rg.detection.seuil_accord], ["Images par essai", cfg.images_par_essai], ["Caméra jugée aveugle sous", rg.lumiere.seuil_noir]]);
    dl($("#c-th-reglages"), [["Méthode", rg.thermique.methode], ["Écart minimal (valeurs brutes)", rg.thermique.delta_comptes], ["Écart minimal (°C, vraie caméra radiométrique)", rg.thermique.delta_c], ["Pixels chauds minimum", rg.thermique.pixels_chauds_min]]);
    dl($("#c-mic-reglages"), [["Seuil de reconnaissance", rg.audio.seuil], ["Durée écoutée", rg.audio.duree_s && rg.audio.duree_s + " s"], ["Une analyse toutes les", rg.audio.intervalle_s && rg.audio.intervalle_s + " s"]]);
  }).catch(() => {});
}

/* ============================== Résultats ============================== */
function vueResultats() {
  const date = (d) => (d ? d.split("-").reverse().join("/") : "");
  const etat = (a) => (a == null ? "na" : a ? "ok" : "ko");
  // objectif atteint sur trop peu d'essais : l'intervalle de confiance descend encore sous la cible
  const fragile = (c, o) => c.atteint === true && c.bas != null && (
    (c.cle === "presence" && c.bas < o.rappel_vivant) || (c.cle === "objet" && c.bas < o.rappel_objet) || (c.cle === "fausses" && c.haut > o.fausses_alertes));
  const verdict = (c, o) => (c.atteint == null ? "Pas encore mesuré" : !c.atteint ? "Objectif manqué" : fragile(c, o) ? "Atteint, à confirmer" : "Objectif atteint");
  const cellule = (t) => (t && t.n ? `<b>${pct(t.valeur)}</b> <span class="muted">${t.k}/${t.n}</span>` : '<span class="muted">—</span>');
  const VERITE = { vivant: "Vivant", objet: "Objet de valeur", vide: "Rien à signaler" };

  function critere(c, o) {
    let valeur, sous;
    if (c.cle === "delai") { valeur = c.valeur == null ? "—" : `${String(c.valeur).replace(".", ",")} s`; sous = c.n ? `moyenne sur ${c.n} alerte${c.n > 1 ? "s" : ""} · pire cas ${String(c.pire).replace(".", ",")} s` : "aucune alerte automatique enregistrée"; }
    else if (c.cle === "thermique") { valeur = c.essais ? `${c.k} sur ${c.n}` : "—"; sous = !c.essais ? "aucun essai avec la thermique" : c.n ? "présences ratées par les caméras" : `les caméras n'ont rien raté sur ${c.essais} essais`; }
    else { valeur = pct(c.valeur); sous = c.n ? `${c.k} sur ${c.n} essais · entre ${pct(c.bas)} et ${pct(c.haut)}` : "aucun essai de ce type"; }
    return `<article class="card critere ${fragile(c, o) ? "fragile" : etat(c.atteint)}"><h3>${esc(c.libelle)}</h3><p class="critere-val">${valeur}</p><p class="small">${sous}</p>
      <p class="critere-cible"><span>Objectif : ${esc(c.cible)}</span><em>${verdict(c, o)}</em></p><p class="small muted">${esc(fragile(c, o) ? "Trop peu d'essais pour l'affirmer : l'intervalle descend encore sous l'objectif." : c.detail)}</p></article>`;
  }

  ECOUTEURS.push((e) => {
    const o = $("#r-origine");
    o.className = "origine " + (e.demo ? "simule" : "mesure");
    o.textContent = e.demo ? "Données de démonstration" : "Mesuré en voiture";
    $("#r-titre").textContent = e.demo ? "Résultats du mode démo" : "Résultats mesurés sur le banc";
  });
  json("/api/resultats").then((r) => {
    const p = r.provenance;
    $("#r-provenance").textContent = r.essais
      ? `${r.essais} essais du journal, du ${date(p.du)} au ${date(p.au)} · ${p.jour} de jour, ${p.nuit} de nuit · ${p.automatiques} en surveillance automatique, ${p.manuels} lancés à la main.`
      : "Le journal est vide : lancez une série d'essais depuis la vue Essais.";
    $("#r-criteres").innerHTML = r.criteres.map((c) => critere(c, r.objectifs)).join("");
    $("#r-approches").innerHTML = r.approches.map((a, i) => { const t = a.rappel; return `<div class="barre"><span class="barre-nom">${esc(a.nom)}</span>
      <div class="barre-piste">${t.n ? `<i class="a${i + 1}" style="width:${t.valeur * 100}%"></i><u style="left:${t.bas * 100}%;width:${(t.haut - t.bas) * 100}%"></u>` : ""}</div>
      <span class="barre-val">${t.n ? `<b>${pct(t.valeur)}</b> ${t.k}/${t.n}` : "pas d'essai"}</span></div>`; }).join("");
    const [jour, nuit] = r.par_lumiere;
    const cr = (bloc, cle) => bloc.criteres.find((c) => c.cle === cle);
    $("#r-lumiere").innerHTML = `<thead><tr><th>Critère</th><th>Jour <span class="muted">${jour.essais} essais</span></th><th>Nuit <span class="muted">${nuit.essais} essais</span></th></tr></thead><tbody>${
      [["presence", "Présences détectées"], ["objet", "Objets signalés"], ["fausses", "Fausses alertes"]].map(([cle, nom]) => `<tr><td>${nom}</td><td>${cellule(cr(jour, cle))}</td><td>${cellule(cr(nuit, cle))}</td></tr>`).join("")
    }<tr><td>Caméras seules, présences</td><td>${cellule(jour.approches[0].rappel)}</td><td>${cellule(nuit.approches[0].rappel)}</td></tr>
     <tr><td>Avec la thermique, présences</td><td>${cellule(jour.approches[1].rappel)}</td><td>${cellule(nuit.approches[1].rappel)}</td></tr></tbody>`;
    const cible = r.par_scenario.length ? r.par_scenario[0].cible : 10;
    $("#r-cible").textContent = `objectif : ${cible} répétitions par scénario, de jour et de nuit`;
    $("#r-scenarios").innerHTML = `<thead><tr><th>Scénario</th><th>Attendu</th><th>Réussite</th><th>Jour</th><th>Nuit</th><th>Répétitions</th></tr></thead><tbody>${
      r.par_scenario.map((s) => `<tr><td><b>${esc(s.code)}</b> ${esc(s.nom === s.code ? "" : s.nom)}</td><td>${VERITE[s.verite] || ""}</td><td>${cellule(s)}</td><td>${cellule(s.jour)}</td><td>${cellule(s.nuit)}</td>
        <td><div class="rep"><i style="width:${Math.min(100, (s.n / s.cible) * 100)}%"></i></div><span class="muted small">${s.n}/${s.cible}</span></td></tr>`).join("")}</tbody>`;
    $("#r-nb-echecs").textContent = r.essais ? `${r.nb_echecs} sur ${r.essais} essais` : "";
    $("#r-echecs").innerHTML = r.echecs.length ? r.echecs.map((e) => `<article class="echec"><a href="/images/${encodeURIComponent(e.id)}_rgb.jpg" target="_blank" rel="noopener"><img loading="lazy" alt="Essai ${esc(e.id)}" src="/images/${encodeURIComponent(e.id)}_rgb.jpg" onerror="this.closest('a').classList.add('sans-image')"></a>
      <div><h4>${esc(e.scenario)} · ${esc(e.variante || "")}</h4><p><span class="muted">Attendu :</span> ${esc(e.attendu)}</p><p><span class="muted">Obtenu :</span> ${esc(e.obtenu)}</p>
      ${e.commentaire ? `<p class="small">${esc(e.commentaire)}</p>` : ""}<p class="small muted">${esc((e.horodatage || "").replace("T", " "))}</p></div></article>`).join("")
      : `<p class="muted">${r.essais ? "Aucun essai raté dans le journal." : "Aucun essai enregistré."}</p>`;
  }).catch((err) => { $("#r-provenance").textContent = `Lecture du journal impossible : ${err.message}`; });
}

document.addEventListener("DOMContentLoaded", () => {
  ({ demo: vueDemo, capteurs: vueCapteurs, resultats: vueResultats }[document.body.dataset.vue] || (() => {}))();
  rafraichirEtat(); setInterval(rafraichirEtat, document.body.dataset.vue === "resultats" ? 5000 : 1000);
});
