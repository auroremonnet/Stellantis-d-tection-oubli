// CARE · page de suivi (téléphone) : état de la surveillance, dernière alerte, acquittement.
// Page autonome : elle ne charge ni app.js ni surveillance.js (le dashboard complet est
// inutilisable sur un écran de téléphone, et on veut une page qui charge vite en 4G).
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const PERIODE_ETAT_MS = 1000;      // état : une fois par seconde (compte à rebours lisible)
  const PERIODE_EVTS_MS = 3000;      // journal : plus lent, il ne bouge qu'aux transitions
  const OBJECTIF_NCAP_S = 15;        // Euro NCAP 2026 : avertissement < 15 s après verrouillage

  const LIBELLES = {
    inactif: "Surveillance désarmée",
    veille: "Habitacle sous surveillance",
    occupe: "Conducteur à bord",
    sortie: "Départ du conducteur",
    analyse: "Analyse de l'habitacle…",
    alerte: "Alerte",
  };
  const DETAILS = {
    inactif: "Le banc n'observe pas l'habitacle.",
    veille: "Rien à signaler.",
    occupe: "Quelqu'un est au volant : aucune analyse en cours.",
    sortie: "Analyse automatique au bout du compte à rebours.",
    analyse: "Toutes les caméras, référence comprise.",
  };
  const ICONES = {
    veille: "○", occupe: "●", sortie: "→", analyse: "◎",
    alerte: "!", rappel: "↻", acquittement: "✓", inactif: "■",
  };

  let dernierEtat = null, enCours = false, image = null;

  // ---- état courant -------------------------------------------------------
  function afficherEtat(s) {
    const alerte = (s.dernier_resultat || {}).alerte;
    const critique = s.etat === "alerte" && alerte && alerte.niveau === "critique";
    const bloc = $("#suivi-etat");
    bloc.dataset.etat = s.etat === "alerte" && !critique ? "alerte-objet" : s.etat;

    $("#suivi-libelle").textContent = s.erreur ? "Banc en erreur" : (LIBELLES[s.etat] || s.etat);
    $("#suivi-detail").textContent = s.erreur || DETAILS[s.etat]
      || (critique ? "Présence détectée dans le véhicule." : "Objet oublié dans le véhicule.");

    const rebours = s.compte_a_rebours_s;
    $("#suivi-chrono").hidden = rebours == null;
    if (rebours != null) $("#suivi-chrono").textContent = rebours.toFixed(1) + " s";

    const ctx = s.contexte || {};
    $("#suivi-contexte").textContent = !s.actif ? "Surveillance désarmée"
      : "Armée" + (ctx.scenario ? " · " + ctx.scenario : "")
        + (ctx.variante ? " · " + ctx.variante : "");

    afficherAlerte(s, alerte);
  }

  // ---- dernière alerte ----------------------------------------------------
  function afficherAlerte(s, alerte) {
    const carte = $("#suivi-alerte");
    carte.hidden = !alerte;
    if (!alerte) { $("#suivi-retour").hidden = true; return; }

    $("#alerte-titre").textContent = alerte.titre;
    $("#alerte-message").textContent = alerte.message;

    // L'heure de l'alerte vient de l'historique de la machine (plus récent en premier)
    const evt = (s.historique || []).find((e) => e.type === "alerte");
    const latence = s.latence_alerte_s;
    const bouts = [];
    if (evt) bouts.push(evt.heure);
    if (latence != null) {
      bouts.push(`verdict en ${latence.toFixed(1)} s`
        + (latence <= OBJECTIF_NCAP_S ? " (objectif Euro NCAP tenu)" : " (au-delà des 15 s Euro NCAP)"));
    }
    if (s.rappels) bouts.push(`${s.rappels} rappel${s.rappels > 1 ? "s" : ""}`);
    $("#alerte-meta").textContent = bouts.join(" · ");

    // Image annotée de l'analyse : masquée tant qu'elle n'est pas chargée (mosaïque absente,
    // analyse sans image…), et rechargée seulement quand l'essai change.
    const id = (s.dernier_resultat || {}).id;
    const img = $("#alerte-image");
    if (id && id !== image) {
      image = id;
      img.hidden = true;
      img.onload = () => { img.hidden = false; };
      img.onerror = () => { img.hidden = true; };
      img.src = `/images/${encodeURIComponent(id)}_rgb.jpg`;
    }

    // Le bouton n'a de sens que tant que l'alerte est en cours
    $("#btn-acquitter").hidden = s.etat !== "alerte";
  }

  // ---- journal ------------------------------------------------------------
  function afficherEvenements(evts) {
    const liste = evts.slice().reverse();   // plus récent en premier
    $("#suivi-histo").innerHTML = liste.map((e) =>
      `<li class="evt-${esc(e.type)}"><time>${esc(e.heure)}</time>` +
      `<span>${ICONES[e.type] || "·"} ${esc(e.detail || e.type)}</span></li>`).join("");
    $("#suivi-histo-vide").hidden = liste.length > 0;
    $("#suivi-maj").textContent = new Date().toLocaleTimeString("fr-FR");
  }

  // ---- acquittement -------------------------------------------------------
  function retour(texte, erreur) {
    const el = $("#suivi-retour");
    el.textContent = texte;
    el.classList.toggle("ko", !!erreur);
    el.hidden = false;
  }

  $("#btn-acquitter").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      const r = await fetch("/api/surveillance/acquitter", { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        retour("Alerte levée : les rappels sont arrêtés.");
        afficherEtat(d);
        rafraichirEvenements();
      } else {
        retour(d.erreur || "Acquittement impossible.", true);   // 409 : plus d'alerte en cours
      }
    } catch {
      retour("Banc injoignable : es-tu sur le même réseau Wi-Fi ?", true);
    } finally {
      btn.disabled = false;
    }
  };

  // ---- boucles ------------------------------------------------------------
  async function rafraichirEtat() {
    if (enCours) return;
    enCours = true;
    try {
      const s = await (await fetch("/api/surveillance")).json();
      document.body.classList.remove("hors-ligne");
      afficherEtat(s);
      if (s.etat !== dernierEtat) { dernierEtat = s.etat; rafraichirEvenements(); }
    } catch {
      document.body.classList.add("hors-ligne");      // banc arrêté ou hors du réseau
    } finally {
      enCours = false;
    }
  }

  async function rafraichirEvenements() {
    try {
      const d = await (await fetch("/api/evenements?n=20")).json();
      afficherEvenements(d.evenements || []);
    } catch { /* le journal est accessoire */ }
  }

  fetch("/api/etat").then((r) => r.json())
    .then((e) => { $("#suivi-demo").hidden = !e.demo; }).catch(() => {});

  (function boucleEtat() {
    rafraichirEtat().finally(() => setTimeout(boucleEtat, PERIODE_ETAT_MS));
  })();
  (function boucleEvts() {
    rafraichirEvenements().finally(() => setTimeout(boucleEvts, PERIODE_EVTS_MS));
  })();
})();
