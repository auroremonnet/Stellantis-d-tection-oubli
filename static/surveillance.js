// CARE · surveillance automatique (simulation de l'oubli de bout en bout)
// S'appuie sur app.js : $, esc, verite, chargerEssais, afficherResultat.
(() => {
  const ORDRE = ["veille", "occupe", "sortie", "analyse", "alerte"];
  const OBJECTIF_NCAP_S = 15; // Euro NCAP 2026 : avertissement < 15 s après verrouillage
  const ICONES = { veille: "○", occupe: "●", sortie: "→", analyse: "◎", alerte: "!", inactif: "■", rappel: "↻", acquittement: "✓" };
  let actif = false, dernierId = null, enCours = false, lienSuivi = "";

  const post = async (url, corps) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps || {}) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erreur || "Erreur serveur");
    return d;
  };

  function banniere(s) {
    const el = $("#surv-banniere");
    const r = s.dernier_resultat, a = r && r.alerte;
    const latence = s.latence_alerte_s;
    const ncap = latence == null ? "" :
      `<span class="badge-ncap ${latence <= OBJECTIF_NCAP_S ? "ok" : "ko"}">verdict en ${latence.toFixed(1)} s · objectif Euro NCAP ≤ ${OBJECTIF_NCAP_S} s</span>`;
    let cls = "", html = "";
    if (s.etat === "sortie") {
      html = `<strong>Plus personne à bord</strong>analyse dans <span class="chrono">${(s.compte_a_rebours_s ?? 0).toFixed(1)} s</span>`;
    } else if (s.etat === "analyse") {
      html = "<strong>Analyse de l'habitacle…</strong>toutes caméras, référence comprise";
    } else if (s.etat === "alerte" && a) {
      cls = a.niveau === "critique" ? "crit" : "obj";
      html = `<strong>${esc(a.titre)}</strong>${esc(a.message)}${s.rappels ? ` · ${s.rappels} rappel${s.rappels > 1 ? "s" : ""}` : ""}<br>${ncap}`;
    } else if (r && s.etat === "veille") {
      cls = "ok";
      html = `<strong>Rien à signaler</strong>dernière analyse : habitacle sans risque<br>${ncap}`;
    }
    if (s.erreur) { cls = "crit"; html = `<strong>Erreur</strong>${esc(s.erreur)}`; }
    el.className = "surv-banniere " + cls;
    el.innerHTML = html;
    el.hidden = !html;
  }

  function etapes(s) {
    const i = ORDRE.indexOf(s.etat);
    const niveau = s.niveau_alerte === "critique" ? "crit" : s.niveau_alerte ? "obj" : "";
    $("#surv-etapes").querySelectorAll("li").forEach((li, k) => {
      li.className = (k === i ? "on " + (s.etat === "alerte" ? niveau : "") : "") + (i > k ? " fait" : "");
    });
  }

  function afficher(s) {
    actif = s.actif;
    etapes(s);
    banniere(s);
    const ctx = s.contexte || {};
    $("#surv-sous").textContent = !actif ? "désarmée"
      : `armée${ctx.scenario ? " · " + ctx.scenario : ""}${ctx.verite ? "" : " · sans vérité terrain (non journalisée)"}`;
    $("#btn-armer").hidden = actif;
    $("#btn-desarmer").hidden = !actif;
    $("#btn-verrou").hidden = !actif || !["veille", "occupe", "sortie"].includes(s.etat);
    $("#surv-aide").hidden = actif;
    const lancer = $("#btn-lancer");
    if (lancer) lancer.disabled = actif;
    $("#surv-histo").innerHTML = (s.historique || []).slice(0, 12).map((e) =>
      `<li><time>${esc(e.heure)}</time><span>${ICONES[e.type] || "·"} ${esc(e.detail)}</span></li>`).join("");
    // Nouveau verdict : rafraîchir l'historique des essais et la carte « Dernier résultat »
    const id = s.dernier_resultat && s.dernier_resultat.id;
    if (id && id !== dernierId) {
      dernierId = id;
      if (typeof chargerEssais === "function") chargerEssais().then(() => {
        const e = (typeof ESSAIS !== "undefined" ? ESSAIS : []).find((x) => x.id === id);
        if (e && typeof afficherResultat === "function") afficherResultat(e);
      });
    }
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
    try { afficher(await fn()); }
    catch (e) { if (typeof alerte === "function") alerte(e.message); }
    finally { btn.disabled = false; }
  }

  $("#btn-armer").onclick = (ev) => action(ev.currentTarget, () => {
    const btn = ev.currentTarget;
    btn.textContent = "Capture de la référence…";
    return post("/api/surveillance/armer", {
      scenario: $("#f-scenario").value, variante: $("#f-variante").value,
      verite: typeof verite === "undefined" ? "" : verite || "",
      commentaire: $("#f-commentaire").value,
    }).finally(() => { btn.textContent = "Armer"; });
  });
  $("#btn-desarmer").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/desarmer"));
  $("#btn-verrou").onclick = (ev) => action(ev.currentTarget, () => post("/api/surveillance/verrouiller"));
  $("#surv-demo").onclick = (ev) => {
    const b = ev.target.closest("button[data-occupant]");
    if (b) action(b, () => post("/api/surveillance/demo", { occupant: b.dataset.occupant === "1" }));
  };

  // Page de suivi à scanner depuis le téléphone (l'URL vient de alertes.url_banc)
  $("#btn-suivi").onclick = () => {
    const panneau = $("#surv-qr");
    panneau.hidden = !panneau.hidden;
    if (panneau.hidden) return;
    const img = $("#surv-qr-img"), lien = $("#surv-qr-url");
    img.hidden = !lienSuivi;
    if (lienSuivi) img.src = "/suivi/qr.png";
    lien.textContent = lienSuivi;
    lien.href = lienSuivi || "#";
    $("#surv-qr-aide").textContent = lienSuivi
      ? "Scanner avec le téléphone, qui doit être sur le même réseau Wi-Fi que ce PC."
      : "Renseigner alertes.url_banc (ex. http://192.168.1.90:5000) dans config.local.json pour afficher le QR code.";
  };

  // Le bouton démo n'existe qu'en mode démo ; le lien de suivi vient de la config des alertes
  fetch("/api/etat").then((r) => r.json()).then((e) => {
    $("#surv-demo").hidden = !e.demo;
    lienSuivi = (e.alertes && e.alertes.suivi) || "";
  }).catch(() => {});

  // Rythme : rapide quand la surveillance tourne (compte à rebours), lent sinon
  (function boucle() {
    rafraichir().finally(() => setTimeout(boucle, actif ? 400 : 2000));
  })();
})();
