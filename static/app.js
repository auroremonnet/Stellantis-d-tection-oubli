// CARE · dashboard de test
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "—" : Math.round(v * 100) + " %");

let CONFIG = null;
let ESSAIS = [];
let verite = null;
const LABEL_VERITE = { vivant: "Vivant", objet: "Objet de valeur", vide: "Rien à signaler" };
const DECISION = {
  CRITIQUE: { ico: "!", txt: "Présence vivante détectée" },
  ALERTE: { ico: "i", txt: "Objet de valeur oublié" },
  RAS: { ico: "✓", txt: "Habitacle sans risque" },
};

// ---------------------------------------------------------------- caméras
function flux(img, sid, onState) {
  let actif = true;
  const suivant = (delai) => setTimeout(() => { img.src = `/snapshot/${sid}?t=${Date.now()}`; }, delai);
  img.onload = () => { onState(true); if (actif) suivant(120); };
  img.onerror = () => { onState(false); if (actif) suivant(2000); };
  suivant(0);
}

function construireCameras(rgb) {
  const grid = $("#cam-grid");
  grid.innerHTML = rgb.map((c) => `
    <div class="cam-tile" id="tile-${c.id}">
      <img id="img-${c.id}" alt="${esc(c.label)}">
      <span class="cam-label"><i class="dot" id="dot-${c.id}"></i>${esc(c.label)}</span>
      <span class="cam-off" id="off-${c.id}">Connexion…</span>
    </div>`).join("");
  for (const c of rgb) flux($(`#img-${c.id}`), c.id, (ok) => { $(`#off-${c.id}`).hidden = ok; });
  flux($("#img-thermal"), "thermal", (ok) => { $("#off-thermal").hidden = ok; });
}

function pill(el, etat, texte) {
  el.className = "pill " + etat;
  el.innerHTML = `<i></i>${texte}`;
}

async function rafraichirEtat() {
  try {
    const e = await (await fetch("/api/etat")).json();
    $("#badge-demo").hidden = !e.demo;
    const moteur = e.modele.moteur === "yoloe" ? "YOLOE (prompts)" : "COCO";
    pill($("#st-modele"), e.modele.pret ? "ok" : e.modele.erreur ? "ko" : "wait",
      e.modele.pret ? `${moteur} · ${e.modele.nom}` : e.modele.erreur ? "Modèle en erreur" : "Chargement du modèle…");
    $("#st-modele").title = e.modele.erreur || "";
    const n = e.rgb.filter((c) => c.ok).length;
    pill($("#st-rgb"), n === e.rgb.length ? "ok" : n ? "wait" : "ko", `Caméras ${n}/${e.rgb.length}`);
    afficherReference(e.reference, e.demo);
    for (const c of e.rgb) {
      const d = $(`#dot-${c.id}`);
      if (d) d.className = "dot " + (c.ok ? "ok" : "ko");
      const off = $(`#off-${c.id}`);
      if (off && !c.ok) off.textContent = c.erreur ? `Hors ligne · ${c.erreur}` : "Hors ligne";
    }
    const th = e.thermique;
    if (!th) {
      pill($("#st-th"), "", "Thermique désactivée");
      $("#off-thermal").textContent = "Désactivée dans config.json";
    } else {
      pill($("#st-th"), th.ok ? "ok" : "ko", th.ok ? "Thermique" : "Thermique hors ligne");
      $("#dot-thermal").className = "dot " + (th.ok ? "ok" : "ko");
      $("#th-mode").textContent = th.ok ? th.mode : "—";
      $("#th-px").textContent = th.pixels_chauds ?? "—";
      $("#th-tmax").textContent = th.tmax == null ? "n/d" : th.tmax + " °C";
    }
    $("#btn-lancer").dataset.pret = e.modele.pret ? "1" : "";
  } catch { /* serveur arrêté */ }
}

// ---------------------------------------------------------------- référence habitacle vide
let REF_SIG = null;
function afficherReference(r, demo) {
  const etat = $("#ref-etat"), del = $("#btn-ref-del"), btn = $("#btn-ref");
  if (demo) { etat.textContent = "indisponible en démo"; btn.disabled = true; return; }
  const sig = JSON.stringify(r);
  if (sig === REF_SIG) return;
  REF_SIG = sig;
  if (!r || !r.active) {
    etat.innerHTML = '<span class="ref-warn">aucune · objets fixes non filtrés</span>';
    del.hidden = true;
    $("#ref-thumbs").innerHTML = "";
    return;
  }
  const fixes = Object.values(r.detections_fixes || {}).reduce((a, b) => a + b, 0);
  etat.textContent = `${(r.horodatage || "").slice(11, 16)} · ${r.cameras.length} cam · ${fixes} détection${fixes > 1 ? "s" : ""} fixe${fixes > 1 ? "s" : ""} ignorée${fixes > 1 ? "s" : ""}`;
  del.hidden = false;
  $("#ref-thumbs").innerHTML = r.cameras.map((sid) => `<figure><img class="mini" src="/reference/${esc(sid)}.jpg?t=${Date.now()}" alt="">
    <figcaption>${esc(sid)} · ${r.detections_fixes?.[sid] ?? 0} fixe${(r.detections_fixes?.[sid] ?? 0) > 1 ? "s" : ""}</figcaption></figure>`).join("");
}

$("#btn-ref").onclick = async () => {
  const btn = $("#btn-ref");
  btn.disabled = true; btn.textContent = "Capture…";
  try {
    const r = await fetch("/api/reference", { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    REF_SIG = null; afficherReference(d, false);
  } catch (e) { alerte(e.message); }
  finally { btn.disabled = false; btn.textContent = "Capturer la référence"; }
};
$("#btn-ref-del").onclick = async () => {
  const d = await (await fetch("/api/reference", { method: "DELETE" })).json();
  REF_SIG = null; afficherReference(d, false);
};

// ---------------------------------------------------------------- formulaire
function construireFormulaire() {
  const sel = $("#f-scenario");
  sel.innerHTML = CONFIG.scenarios.map((s) => `<option value="${esc(s.code)}">${esc(s.code)} · ${esc(s.nom)}</option>`).join("");
  $("#f-variante").innerHTML = CONFIG.variantes.map((v) => `<option>${esc(v)}</option>`).join("");
  const majVerite = () => {
    const s = CONFIG.scenarios.find((x) => x.code === sel.value);
    choisirVerite(s?.verite);
    majCompteur();
  };
  sel.onchange = majVerite;
  $("#f-variante").onchange = majCompteur;
  $("#f-verite").onclick = (ev) => { if (ev.target.dataset.v) choisirVerite(ev.target.dataset.v); };
  majVerite();
  $("#form-essai").onsubmit = lancer;
}

function choisirVerite(v) {
  verite = v || null;
  for (const b of $("#f-verite").children) b.classList.toggle("on", b.dataset.v === verite);
}

function majCompteur() {
  const sc = $("#f-scenario").value, va = $("#f-variante").value;
  const n = ESSAIS.filter((e) => e.scenario === sc && e.variante === va).length;
  const cible = CONFIG.repetitions_cible;
  $("#compteur").textContent = `Répétition ${n + 1}${cible ? " / " + cible : ""}`;
}

async function lancer(ev) {
  ev.preventDefault();
  if (!verite) return alerte("Choisis la vérité terrain.");
  const btn = $("#btn-lancer");
  if (!btn.dataset.pret) return alerte("Le modèle n'est pas encore chargé.");
  btn.disabled = true; $(".spinner", btn).hidden = false; $(".txt", btn).textContent = "Analyse en cours…";
  try {
    const r = await fetch("/api/essais", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: $("#f-scenario").value, variante: $("#f-variante").value, verite, commentaire: $("#f-commentaire").value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    afficherResultat(d);
    $("#f-commentaire").value = "";
    await chargerEssais();
  } catch (e) { alerte(e.message); }
  finally { btn.disabled = false; $(".spinner", btn).hidden = true; $(".txt", btn).textContent = "Lancer l'analyse"; }
}

function alerte(msg) {
  $("#result-body").className = "";
  $("#result-body").innerHTML = `<div class="decision CRITIQUE"><div class="ico">!</div><div><strong>Impossible</strong><span>${esc(msg)}</span></div></div>`;
}

// ---------------------------------------------------------------- résultat
function afficherResultat(e) {
  const dec = e.decision_A2 || e.decision_A1;
  const D = DECISION[dec];
  const th = e.vivant_thermique;
  document.querySelectorAll(".cam-tile.hit").forEach((t) => t.classList.remove("hit"));
  (e.cameras_vivant || "").split(", ").filter(Boolean).forEach((id) => $(`#tile-${id}`)?.classList.add("hit"));
  setTimeout(() => document.querySelectorAll(".cam-tile.hit").forEach((t) => t.classList.remove("hit")), 6000);
  $("#result-body").className = "";
  $("#result-body").innerHTML = `
    <div class="decision ${dec}"><div class="ico">${D.ico}</div>
      <div><strong>${dec}</strong><span>${D.txt}${e.A2 ? " · décision A2" : " · décision A1"}</span></div></div>
    <dl class="kv">
      <dt>Scénario</dt><dd>${esc(e.scenario)} · ${esc(e.variante)} · vérité <b>${LABEL_VERITE[e.verite]}</b></dd>
      <dt>RGB</dt><dd>${e.vivant_rgb ? `<span class="yes">vivant</span> (${esc(e.classes_vivant)})` : '<span class="no">rien de vivant</span>'}</dd>
      <dt>Thermique</dt><dd>${th == null ? '<span class="no">non utilisée</span>' : th ? `<span class="yes">chaud</span> · ${e.pixels_chauds} px${e.tmax ? " · " + e.tmax + " °C" : ""}` : `<span class="no">rien</span> · ${e.pixels_chauds} px`}</dd>
      <dt>Objets</dt><dd>${esc(e.objets) || '<span class="no">aucun</span>'}</dd>
      <dt>Référence</dt><dd>${e.reference_utilisee
        ? `${e.zones_nouvelles || 0} zone${e.zones_nouvelles > 1 ? "s" : ""} nouvelle${e.zones_nouvelles > 1 ? "s" : ""}${e.lumiere_changee ? ' · <span class="ref-warn">lumière changée, zones ignorées</span>' : ""}`
        : '<span class="no">non utilisée</span>'}</dd>
      <dt>Évaluation</dt><dd>A1 ${tag(e.A1)} &nbsp; A2 ${tag(e.A2)}</dd>
      <dt>Latence</dt><dd>${e.latence_s} s</dd>
    </dl>
    <div class="thumbs">
      <img src="/images/${e.id}_rgb.jpg" onerror="this.remove()" alt="RGB annoté">
      ${th == null ? "" : `<img src="/images/${e.id}_th.jpg" onerror="this.remove()" alt="Thermique">`}
    </div>`;
}

const tag = (r) => (r ? `<span class="tag ${r}">${r}</span>` : '<span class="tag na">—</span>');

// ---------------------------------------------------------------- données
async function chargerEssais() {
  const d = await (await fetch("/api/essais")).json();
  ESSAIS = d.essais;
  afficherKpis(d.metriques);
  afficherGraphique(d.metriques.scenarios);
  afficherTable();
  majCompteur();
}

function carteApproche(cle, nom, couleur, m) {
  return `<div class="card kpi"><div class="bar" style="background:${couleur}"></div>
    <h3>${cle} · ${nom}</h3>
    <div class="hero">${pct(m.rappel)}<small>rappel vivant</small></div>
    <div class="muted small">${m.n} essai${m.n > 1 ? "s" : ""} évalué${m.n > 1 ? "s" : ""}</div>
    <div class="stats">
      <div><b>${m.FN}</b><span>Oublis (FN)</span></div>
      <div><b>${pct(m.taux_fp)}</b><span>Fausses alertes</span></div>
      <div><b>${pct(m.precision)}</b><span>Précision</span></div>
      <div><b>${m.latence == null ? "—" : m.latence + " s"}</b><span>Latence moy.</span></div>
    </div></div>`;
}

function afficherKpis(m) {
  const a1 = m.approches.A1, a2 = m.approches.A2;
  let delta = "—", sens = "";
  if (a1.rappel != null && a2.rappel != null) {
    const d = Math.round((a2.rappel - a1.rappel) * 100);
    delta = (d > 0 ? "+" : "") + d + " pts";
    sens = d > 0 ? "La fusion détecte davantage de présences vivantes." : d < 0 ? "La fusion fait moins bien que le RGB seul." : "Aucun écart pour l'instant.";
  }
  $("#kpis").innerHTML =
    carteApproche("A1", "RGB seul", "var(--a1)", a1) +
    carteApproche("A2", "RGB + thermique", "var(--a2)", a2) +
    `<div class="card kpi"><h3>Hypothèse : A2 &gt; A1</h3>
      <div class="delta">${delta}</div><div class="muted small">écart de rappel A2 − A1</div>
      <p class="small" style="margin:10px 0 0">${sens || "Lance des essais sur les scénarios « vivant » pour comparer."}</p>
      <div class="stats" style="grid-template-columns:1fr 1fr">
        <div><b>${m.total}</b><span>Essais au total</span></div>
        <div><b>${pct(m.objets)}</b><span>Objets de valeur détectés</span></div>
      </div></div>`;
}

// Barres horizontales groupées A1 / A2 par scénario
function afficherGraphique(rows) {
  const el = $("#chart");
  if (!rows.length) { el.innerHTML = '<p class="muted">Pas encore de données.</p>'; return; }
  const noms = Object.fromEntries(CONFIG.scenarios.map((s) => [s.code, s.nom]));
  const W = el.clientWidth || 900, gauche = Math.min(300, W * 0.34), droite = 60;
  const barH = 14, gap = 3, rowH = barH * 2 + gap + 18, H = rows.length * rowH + 26;
  const x = (v) => gauche + (W - gauche - droite) * v;
  let svg = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Résultats par scénario"><g class="grid">`;
  for (const t of [0, 0.25, 0.5, 0.75, 1]) svg += `<line x1="${x(t)}" x2="${x(t)}" y1="0" y2="${H - 22}"/><text x="${x(t)}" y="${H - 6}" text-anchor="middle">${t * 100} %</text>`;
  svg += "</g>";
  rows.forEach((r, i) => {
    const y0 = i * rowH + 6;
    const lib = `${r.scenario} · ${noms[r.scenario] || ""}`;
    svg += `<g class="row" data-i="${i}"><rect class="bg" x="0" y="${y0 - 4}" width="${W}" height="${rowH - 4}" rx="6" fill="transparent"/>`;
    svg += `<text x="${gauche - 12}" y="${y0 + barH + 4}" text-anchor="end">${esc(lib.length > 44 ? lib.slice(0, 43) + "…" : lib)}</text>`;
    [["A1", "var(--a1)"], ["A2", "var(--a2)"]].forEach(([a, c], k) => {
      const y = y0 + k * (barH + gap), v = r[a];
      if (v == null) { svg += `<text x="${x(0) + 4}" y="${y + barH - 2}" class="muted" style="fill:var(--muted)">${a} : pas de mesure</text>`; return; }
      const w = Math.max(x(v) - x(0), 2);
      svg += `<path d="M${x(0)},${y} h${w - 4} a4,4 0 0 1 4,4 v${barH - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z" fill="${c}"/>`;
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
        A1 : ${pct(r.A1)} <span style="opacity:.7">(${r.A1_n} essais)</span><br>
        A2 : ${pct(r.A2)} <span style="opacity:.7">(${r.A2_n} essais)</span>`;
      tip.style.left = Math.min(ev.clientX + 14, innerWidth - 290) + "px";
      tip.style.top = ev.clientY + 14 + "px";
    };
    g.onmouseleave = () => { tip.hidden = true; };
  });
}

function afficherTable() {
  $("#nb-essais").textContent = `${ESSAIS.length} essai${ESSAIS.length > 1 ? "s" : ""}`;
  const tb = $("#table tbody");
  if (!ESSAIS.length) { tb.innerHTML = `<tr><td colspan="13" class="muted">Aucun essai enregistré.</td></tr>`; return; }
  tb.innerHTML = ESSAIS.map((e) => `<tr>
    <td>${esc(e.horodatage.slice(11, 19))}<div class="muted small">${esc(e.horodatage.slice(0, 10))}</div></td>
    <td><b>${esc(e.scenario)}</b></td>
    <td>${esc(e.variante)}</td>
    <td>${LABEL_VERITE[e.verite] || esc(e.verite)}</td>
    <td>${e.vivant_rgb ? '<span class="yes">vivant</span>' : '<span class="no">—</span>'}</td>
    <td>${e.vivant_thermique == null ? '<span class="no">n/a</span>' : e.vivant_thermique ? '<span class="yes">chaud</span>' : '<span class="no">—</span>'}</td>
    <td>${tag(e.A1)}</td><td>${tag(e.A2)}</td>
    <td>${esc(e.objets) || '<span class="no">—</span>'}</td>
    <td class="num">${e.reference_utilisee ? esc(e.zones_nouvelles || 0) : '<span class="no">n/a</span>'}</td>
    <td class="num">${esc(e.latence_s)} s</td>
    <td><img class="mini" src="/images/${e.id}_rgb.jpg" onerror="this.remove()" alt=""><img class="mini" src="/images/${e.id}_th.jpg" onerror="this.remove()" alt=""></td>
    <td><button class="del" data-id="${esc(e.id)}" title="Supprimer cet essai">×</button></td>
  </tr>`).join("");
}

$("#table").addEventListener("click", async (ev) => {
  const b = ev.target.closest(".del");
  if (b) {
    b.textContent = "…";
    await fetch(`/api/essais/${b.dataset.id}`, { method: "DELETE" });
    chargerEssais();
  }
});

// Agrandir une image
document.addEventListener("click", (ev) => {
  const img = ev.target.closest(".thumbs img, .mini");
  const lb = $("#lightbox");
  if (img) { $("img", lb).src = img.src; lb.hidden = false; }
  else if (ev.target.closest("#lightbox")) lb.hidden = true;
});

let _rz;
window.addEventListener("resize", () => { clearTimeout(_rz); _rz = setTimeout(chargerEssais, 250); });

// ---------------------------------------------------------------- démarrage
(async () => {
  CONFIG = await (await fetch("/api/config")).json();
  const e = await (await fetch("/api/etat")).json();
  construireCameras(e.rgb);
  $("#cams-sub").textContent = `${e.rgb.length} caméra${e.rgb.length > 1 ? "s" : ""} RGB · vue plongeante`;
  construireFormulaire();
  await rafraichirEtat();
  setInterval(rafraichirEtat, 2000);
  await chargerEssais();
})();
