/*
 * signature.js - the signature pad in Account Settings.
 *
 * Draws with pointer events, so mouse, finger and stylus all work. Ink is
 * always dark on a transparent background so the saved PNG looks like ink
 * on paper wherever it's shown later. On save, the drawing is cropped to
 * the area actually signed (plus a margin) so it doesn't carry a large
 * empty border, then posted as a PNG data URL.
 */
(function () {
    const editor = document.getElementById("signatureEditor");
    const canvas = document.getElementById("signaturePad");
    if (!editor || !canvas) return;

    const ctx = canvas.getContext("2d");
    const saveBtn = document.getElementById("signatureSaveBtn");
    const clearBtn = document.getElementById("signatureClearBtn");
    const cancelBtn = document.getElementById("signatureCancelBtn");
    const redrawBtn = document.getElementById("signatureRedrawBtn");
    const current = document.getElementById("signatureCurrent");
    const placeholder = document.getElementById("signaturePlaceholder");
    const errorBox = document.getElementById("signatureError");
    const csrf = document.getElementById("signatureCsrf");

    const INK = "#111827";
    const LINE_WIDTH = 2.4;
    const MARGIN = 12;          // CSS px kept around the signature when cropping
    const MIN_W = 60, MIN_H = 30;

    let drawing = false;
    let hasInk = false;
    let last = null;
    let bounds = null;          // {minX, minY, maxX, maxY} in CSS px
    let ratio = 1;

    function resize() {
        // Match the canvas's pixel buffer to its on-screen size (and the
        // screen's pixel density) so lines are crisp, not blurry.
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        ratio = Math.max(window.devicePixelRatio || 1, 1);
        canvas.width = Math.round(rect.width * ratio);
        canvas.height = Math.round(rect.height * ratio);
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.strokeStyle = INK;
        ctx.fillStyle = INK;
        ctx.lineWidth = LINE_WIDTH;
        clearPad();   // resizing wipes the buffer, so start clean
    }

    function clearPad() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        hasInk = false;
        bounds = null;
        last = null;
        updateState();
    }

    function updateState() {
        saveBtn.disabled = !hasInk;
        if (placeholder) placeholder.classList.toggle("is-hidden", hasInk);
    }

    function point(e) {
        const rect = canvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function grow(p) {
        if (!bounds) bounds = { minX: p.x, minY: p.y, maxX: p.x, maxY: p.y };
        bounds.minX = Math.min(bounds.minX, p.x);
        bounds.minY = Math.min(bounds.minY, p.y);
        bounds.maxX = Math.max(bounds.maxX, p.x);
        bounds.maxY = Math.max(bounds.maxY, p.y);
    }

    canvas.addEventListener("pointerdown", (e) => {
        if (e.button !== undefined && e.button > 0) return;   // left button / touch / pen only
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        drawing = true;
        last = point(e);
        grow(last);
        // A dot, so a single tap still leaves a mark (dots on i's).
        ctx.beginPath();
        ctx.arc(last.x, last.y, LINE_WIDTH / 2, 0, Math.PI * 2);
        ctx.fill();
        hasInk = true;
        updateState();
    });

    canvas.addEventListener("pointermove", (e) => {
        if (!drawing) return;
        e.preventDefault();
        const p = point(e);
        // Smooth the stroke by curving through the midpoint between samples.
        const mid = { x: (last.x + p.x) / 2, y: (last.y + p.y) / 2 };
        ctx.beginPath();
        ctx.moveTo(last.midX ?? last.x, last.midY ?? last.y);
        ctx.quadraticCurveTo(last.x, last.y, mid.x, mid.y);
        ctx.stroke();
        grow(p);
        last = { x: p.x, y: p.y, midX: mid.x, midY: mid.y };
    });

    function endStroke() {
        drawing = false;
        last = null;
    }
    canvas.addEventListener("pointerup", endStroke);
    canvas.addEventListener("pointercancel", endStroke);
    canvas.addEventListener("pointerleave", (e) => {
        // With pointer capture this only fires once the stroke has ended,
        // but guard anyway for browsers without capture support.
        if (!canvas.hasPointerCapture || !canvas.hasPointerCapture(e.pointerId)) endStroke();
    });

    function croppedDataUrl() {
        const cssW = canvas.width / ratio;
        const cssH = canvas.height / ratio;
        let x0 = Math.max(0, bounds.minX - MARGIN);
        let y0 = Math.max(0, bounds.minY - MARGIN);
        let x1 = Math.min(cssW, bounds.maxX + MARGIN);
        let y1 = Math.min(cssH, bounds.maxY + MARGIN);
        // Keep a minimum size so a very short mark still makes a usable image.
        if (x1 - x0 < MIN_W) { const c = (x0 + x1) / 2; x0 = Math.max(0, c - MIN_W / 2); x1 = Math.min(cssW, x0 + MIN_W); }
        if (y1 - y0 < MIN_H) { const c = (y0 + y1) / 2; y0 = Math.max(0, c - MIN_H / 2); y1 = Math.min(cssH, y0 + MIN_H); }

        const sx = Math.round(x0 * ratio), sy = Math.round(y0 * ratio);
        const sw = Math.max(1, Math.round((x1 - x0) * ratio));
        const sh = Math.max(1, Math.round((y1 - y0) * ratio));

        const out = document.createElement("canvas");
        out.width = sw;
        out.height = sh;
        out.getContext("2d").drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);
        return out.toDataURL("image/png");
    }

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.style.display = "block";
    }

    saveBtn.addEventListener("click", async () => {
        if (!hasInk || !bounds) return;
        errorBox.style.display = "none";
        saveBtn.disabled = true;
        const original = saveBtn.textContent;
        saveBtn.textContent = "Saving...";

        const body = new FormData();
        body.append("csrf_token", csrf ? csrf.value : "");
        body.append("signature_data", croppedDataUrl());

        try {
            const res = await fetch(editor.dataset.saveUrl, { method: "POST", body, credentials: "same-origin" });
            if (!res.ok) {
                const text = await res.text();
                showError(typeof cleanErrorText === "function"
                    ? cleanErrorText(text, "Couldn't save your signature. Please try again.")
                    : "Couldn't save your signature. Please try again.");
                saveBtn.disabled = false;
                saveBtn.textContent = original;
                return;
            }
            window.location.hash = "signature";
            window.location.reload();
        } catch (err) {
            showError("Couldn't reach the server. Check your connection and try again.");
            saveBtn.disabled = false;
            saveBtn.textContent = original;
        }
    });

    clearBtn.addEventListener("click", clearPad);

    if (redrawBtn) {
        redrawBtn.addEventListener("click", () => {
            current.hidden = true;
            editor.hidden = false;
            resize();   // the canvas had no size while hidden
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
            editor.hidden = true;
            current.hidden = false;
            errorBox.style.display = "none";
        });
    }

    // Re-fit on window resize only if nothing is drawn yet, so a resize
    // (e.g. rotating a tablet) never silently wipes a signature in progress.
    window.addEventListener("resize", () => { if (!hasInk && !editor.hidden) resize(); });

    if (!editor.hidden) resize();
})();
