// CARE · surveillance automatique (simulation de l'oubli de bout en bout)
// S'appuie sur app.js : $, esc, sec, chargerEssais, ESSAIS, afficherVerdict, verrouillerPilotage, erreur.
(() => {
  const ORDRE = ["veille", "occupe", "sortie", "analyse", "alerte"];
  const ICONES = { veille: "○", occupe: "●", sortie: "→", analyse: "◎", alerte: "!", inactif: "■", rappel: "↻" };
  const LABEL_VERITE = { vivant: "vivant", objet: "objet de valeur", vide: "rien à signaler" };
  let actif = null, dernierId = null, enCours = false;

  const post = async (url, corps) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps || {}) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    return d;
  };

  function statut(s) {
    const r = s.dernier_resultat, a = r && r.alerte;
    const ctx = s.contexte || {};
    const essai = ctx.scenario
      ? `<span class="surv-ctx">${esc(ctx.scenario)} · ${esc(ctx.variante)} · ${esc(LABEL_VERITE[ctx.verite] || "sans vérité terrain (non journalisé)")}</span>` : "";
    let cls = "", html = "";
    if (s.erreur) { cls = "crit"; html = `<strong>Erreur</strong>${esc(s.erreur)}`; }
    else if (s.etat === "veille") html = "<strong>Habitacle vide enregistré</strong>En attente du conducteur.";
    else if (s.etat === "occupe") html = "<strong>Conducteur à bord</strong>Il pose ses affaires, puis descend.";
    else if (s.etat === "sortie") html = `<strong>Plus personne à bord</strong>analyse dans <span class="chrono">${sec(s.compte_a_rebours_s ?? 0)}</span>`;
    else if (s.etat === "analyse") html = "<strong>Analyse de l'habitacle…</strong>toutes caméras, référence comprise";
    else if (s.etat === "alerte") {
      cls = s.niveau_alerte === "critique" ? "crit" : "obj";
      html = `<strong>${esc(a?.titre || "Alerte en cours")}</strong>${s.rappels ? `${s.rappels} rappel${s.rappels > 1 ? "s" : ""} · ` : ""}le retour du conducteur lève l'alerte.`;
    }
    const el = $("#surv-statut");
    el.className = "surv-statut " + cls;
    el.innerHTML = html + essai;
  }

  function etapes(s) {
    const i = ORDRE.indexOf(s.etat);
    const niveau = s.niveau_alerte === "critique" ? "crit" : s.niveau_alerte ? "obj" : "";
    $("#surv-etapes").querySelectorAll("li").forEach((li, k) => {
      li.className = (k === i ? "on " + (s.etat === "alerte" ? niveau : "") : "") + (i > k ? " fait" : "");
      if (k === i) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
  }

  // Résultat de la surveillance → même forme qu'une ligne du journal pour le bandeau verdict
  const commeEssai = (r, ctx) => ({ ...ctx, ...r, mode: "auto", niveau_alerte: r.alerte?.niveau ?? null });

  function nouveauVerdict(s) {
    const r = s.dernier_resultat;
    const id = r && r.id;
    if (!id || id === dernierId) return;
    dernierId = id;
    afficherVerdict(commeEssai(r, s.contexte || {}));          // tout de suite, sans attendre le journal
    // puis la ligne du journal (évaluation A1/A2) dès qu'elle est écrite
    const relire = (essais) => chargerEssais().then(() => {
      const e = ESSAIS.find((x) => x.id === id);
      if (e) afficherVerdict(e);
      else if (essais > 1) setTimeout(() => relire(essais - 1), 1200);
    });
    setTimeout(() => relire(3), 400);
  }

  function afficher(s) {
    const etaitActif = actif;
    actif = s.actif;
    if (actif !== etaitActif) verrouillerPilotage(actif);
    $("#surv").hidden = !actif;
    if (actif) {
      etapes(s);
      statut(s);
      $("#btn-verrou").hidden = !["veille", "occupe", "sortie"].includes(s.etat);
    }
    $("#surv-histo").innerHTML = (s.historique || []).slice(0, 15).map((e) =>
      `<li><time>${esc(e.heure)}</time><span>${ICONES[e.type] || "·"} ${esc(e.detail)}</span></li>`).join("");
    nouveauVerdict(s);
  }

  async function rafraichir() {
    if (enCours) return;
    enCours = true;
    try { afficher(await (await fetch("/api/surveillance")).json()); }
    catch { /* serveur arrêté */ }
    finally { enCours = false; }
  }

  async function action(btn, fn) {
    btn.disabled = true;
    erreur("");
    try { afficher(await fn()); }
    catch (e) { erreur(e.message); }
    finally { btn.disabled = false; }
  }

  window.CARE_SURV = {
    armer(ctx) {
      const btn = $("#btn-principal");
      attente(btn, true, "Capture de la référence…");
      return post("/api/surveillance/armer", ctx)
        .then((s) => { $("#f-commentaire").value = ""; attente(btn, false); verrouillerPilotage(s.actif); afficher(s); })
        .catch((e) => { attente(btn, false); verrouillerPilotage(false); erreur(e.message); });
    },
  };
  $("#btn-desarmer").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/desarmer"));
  $("#btn-verrou").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/verrouiller"));
  $("#surv-demo").onclick = (ev) => {
    const b = ev.target.closest("button[data-occupant]");
    if (b) action(b, () => post("/api/surveillance/demo", { occupant: b.dataset.occupant === "1" }));
  };

  // Rythme : rapide quand la surveillance tourne (compte à rebours), lent sinon
  (function boucle() {
    rafraichir().finally(() => setTimeout(boucle, actif ? 400 : 2000));
  })();
})();
