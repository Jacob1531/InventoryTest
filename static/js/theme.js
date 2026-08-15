/**
 * Dark mode toggle, persisted in localStorage. The initial theme is applied
 * by an inline snippet in base.html (before this file loads) so there's no
 * flash of the wrong theme on page load; this file only wires up the
 * toggle switch on the account settings page and keeps it in sync.
 */
function setTheme(isDark) {
    if (isDark) {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("theme", "dark");
    } else {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("theme", "light");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("themeToggle");
    if (!toggle) return;
    toggle.checked = document.documentElement.getAttribute("data-theme") === "dark";
    toggle.addEventListener("change", () => setTheme(toggle.checked));
});
