/**
 * Mobile nav (base.css @media max-width 768px).
 * Only run "close" logic while #mobileMenu is open — otherwise document clicks
 * (e.g. desktop .nav-links) would call setOpen(false) → ensureBackdrop() and
 * mutate the DOM during navigation, cancelling the request in many browsers.
 */
(function () {
  function menuEl() {
    return document.getElementById("mobileMenu");
  }

  function ensureBackdrop() {
    var id = "mobileNavBackdrop";
    var el = document.getElementById(id);
    if (el) return el;
    el = document.createElement("div");
    el.id = id;
    el.className = "mobile-nav-backdrop";
    el.setAttribute("aria-hidden", "true");
    el.tabIndex = -1;
    var nav = document.querySelector("nav");
    if (nav && nav.parentNode) {
      nav.parentNode.insertBefore(el, nav.nextSibling);
    } else {
      document.body.insertBefore(el, document.body.firstChild);
    }
    el.addEventListener("click", function () {
      closeMenu();
    });
    return el;
  }

  function closeMenu() {
    setOpen(false);
  }

  function setOpen(open) {
    var m = menuEl();
    if (!m) return;
    var bd = ensureBackdrop();
    m.classList.toggle("open", open);
    bd.classList.toggle("open", open);
    document.documentElement.classList.toggle("mobile-nav-open", open);
    document.body.classList.toggle("mobile-nav-open", open);
  }

  window.toggleMobileMenu = function () {
    var m = menuEl();
    if (!m) return;
    setOpen(!m.classList.contains("open"));
  };

  document.addEventListener(
    "click",
    function (e) {
      var mobileMenu = menuEl();
      var menuToggle = document.querySelector(".mobile-menu-toggle");
      if (!mobileMenu || !menuToggle) return;

      if (!mobileMenu.classList.contains("open")) {
        return;
      }

      var navLink =
        e.target.closest &&
        e.target.closest("#mobileMenu a[href]");
      if (
        navLink &&
        navLink.getAttribute("href") &&
        navLink.getAttribute("href") !== "#" &&
        !navLink.hasAttribute("download")
      ) {
        return;
      }

      if (!mobileMenu.contains(e.target) && !menuToggle.contains(e.target)) {
        closeMenu();
      }
    },
    false,
  );

  window.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var m = menuEl();
    if (m && m.classList.contains("open")) closeMenu();
  });
})();
