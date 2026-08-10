/**
 * Lightweight toast notifications. Reads any flashed messages the server
 * rendered into #flashData (see base.html) and displays them, then also
 * exposes showToast() for any future client-side use.
 */
function showToast(message, category) {
    let container = document.getElementById("toastContainer");
    if (!container) {
        container = document.createElement("div");
        container.id = "toastContainer";
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = "toast" + (category === "error" ? " toast-error" : "");

    const icon = category === "error"
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';

    toast.innerHTML = icon + '<span></span>';
    toast.querySelector("span").textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("toast-out");
        toast.addEventListener("animationend", () => toast.remove());
    }, 3500);
}

document.addEventListener("DOMContentLoaded", () => {
    const flashData = document.getElementById("flashData");
    if (!flashData) return;
    Array.from(flashData.children).forEach((el) => {
        showToast(el.textContent, el.dataset.category);
    });
});
