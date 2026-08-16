/**
 * Place-order modal, shared across every page that can trigger it
 * (Inventory, Low Stock). The modal markup itself lives once in
 * base.html so every page gets it without duplicating HTML/JS.
 *
 * This file is loaded in <head>, before the modal HTML exists in the
 * DOM, so anything that touches an element is deferred to
 * DOMContentLoaded. The open/close/validate functions themselves are
 * safe to define at top level since they're only ever invoked later,
 * via onclick handlers, by which point the DOM is ready.
 */

function openOrderModal(button)
{
    const id = button.dataset.id;
    const name = button.dataset.name;
    document.getElementById("orderModalItemName").textContent = "For: " + name;
    document.getElementById("orderForm").action = "/inventory/order/" + id;
    document.getElementById("orderQuantity").value = "";
    document.getElementById("orderExpectedDate").value = "";
    document.getElementById("orderNotes").value = "";
    document.getElementById("orderQuantity").classList.remove("has-error");
    document.getElementById("orderQuantityError").textContent = "";
    document.getElementById("orderFormError").style.display = "none";
    document.getElementById("orderModal").style.display = "block";
}

function closeOrderModal()
{
    document.getElementById("orderModal").style.display = "none";
}

function validateOrderForm()
{
    const qtyStr = document.getElementById("orderQuantity").value.trim();
    const qtyNum = qtyStr === "" ? NaN : Number(qtyStr);
    const input = document.getElementById("orderQuantity");
    const errEl = document.getElementById("orderQuantityError");

    let message = "";
    if (Number.isNaN(qtyNum) || !Number.isInteger(qtyNum)) {
        message = "Quantity must be a whole number.";
    } else if (qtyNum <= 0) {
        message = "Quantity must be greater than zero.";
    } else if (qtyNum > 999999999) {
        message = "Quantity can't exceed 999999999.";
    }

    input.classList.toggle("has-error", !!message);
    errEl.textContent = message;
    return !message;
}

document.addEventListener("DOMContentLoaded", () => {
    const modal = document.getElementById("orderModal");
    if (!modal) return;

    let orderModalMouseDownOnBackdrop = false;

    modal.addEventListener("mousedown", function(event) {
        orderModalMouseDownOnBackdrop = (event.target === this);
    });

    modal.addEventListener("click", function(event) {
        if (event.target === this && orderModalMouseDownOnBackdrop) closeOrderModal();
    });

    document.getElementById("orderQuantity").addEventListener("input", validateOrderForm);

    document.getElementById("orderForm").addEventListener("submit", function(event) {
        event.preventDefault();

        if (!validateOrderForm()) return;

        const form = event.target;
        const saveBtn = document.getElementById("orderSaveBtn");
        const errorBanner = document.getElementById("orderFormError");
        errorBanner.style.display = "none";

        saveBtn.disabled = true;
        saveBtn.textContent = "Placing order...";

        fetch(form.action, {
            method: "POST",
            body: new FormData(form),
        })
            .then(res => res.text().then(text => ({ ok: res.ok, text })))
            .then(({ ok, text }) => {
                if (!ok) {
                    errorBanner.textContent = text || "Failed to place order. Please try again.";
                    errorBanner.style.display = "block";
                    saveBtn.disabled = false;
                    saveBtn.textContent = "Place Order";
                    return;
                }
                window.location.reload();
            })
            .catch(() => {
                errorBanner.textContent = "Couldn't reach the server. Please try again.";
                errorBanner.style.display = "block";
                saveBtn.disabled = false;
                saveBtn.textContent = "Place Order";
            });
    });
});
