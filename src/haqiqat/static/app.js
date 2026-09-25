// Remembers the reader's language and region of interest in this browser only.
// Nothing is sent anywhere; the site works fully without this script.
(function () {
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  document.querySelectorAll("[data-lang]").forEach(function (a) {
    a.addEventListener("click", function () { set("haqiqat.lang", a.dataset.lang); });
  });
  document.querySelectorAll("[data-region]").forEach(function (a) {
    a.addEventListener("click", function () { set("haqiqat.region", a.dataset.region); });
  });

  // On the landing page, go straight to the remembered language.
  if (document.body.classList.contains("landing")) {
    var lang = get("haqiqat.lang");
    if (lang) {
      var link = document.querySelector('.choose a[data-lang="' + lang + '"]');
      if (link) { window.location.replace(link.getAttribute("href")); }
    }
  }
})();
