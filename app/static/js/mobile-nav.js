/**
 * Mobile nav: hamburger toggle, outside-click / backdrop close, close on link navigate.
 * Expects #mobileMenu and .mobile-menu-toggle (matches base.css).
 */
(function () {
  function menuEl() {
    return document.getElementById("mobileMenu");
  }

  function setOpen(open) {
    var m = menuEl();
    if (!m) return;
    m.classList.toggle("open", open);
    document.body.classList.toggle("mobile-nav-open", open);
  }

  function closeMenu() {
    setOpen(false);
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

      var navLink =
        e.target.closest &&
        e.target.closest("#mobileMenu a[href]");
      if (
        navLink &&
        navLink.getAttribute("href") &&
        navLink.getAttribute("href") !== "#" &&
        !navLink.hasAttribute("download")
      ) {
        closeMenu();
        return;
      }

      if (!mobileMenu.contains(e.target) && !menuToggle.contains(e.target)) {
        closeMenu();
      }
    },
    false,
  );

  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMenu();
  });
})();
