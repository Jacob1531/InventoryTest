/**
 * Exports an HTML table to an .xlsx file, respecting:
 *  - any client-side filtering already applied (rows hidden via display:none
 *    are skipped)
 *  - live values of any <input>/<select> cells (e.g. threshold fields),
 *    rather than their original server-rendered value
 *  - columns marked with class="no-export" on the <th> (action columns,
 *    buttons, etc. are skipped)
 */
function exportTableToExcel(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const allHeaderCells = Array.from(table.querySelectorAll("thead th"));
    const headerIndexes = allHeaderCells
        .map((th, i) => (th.classList.contains("no-export") ? -1 : i))
        .filter((i) => i >= 0);
    const headers = headerIndexes.map((i) => allHeaderCells[i].textContent.trim());

    const visibleRows = Array.from(table.querySelectorAll("tbody tr")).filter((row) => {
        return window.getComputedStyle(row).display !== "none";
    });

    const rows = visibleRows.map((row) => {
        const cells = Array.from(row.children);
        return headerIndexes.map((i) => {
            const cell = cells[i];
            if (!cell) return "";
            const input = cell.querySelector("input:not([type=hidden]), select");
            if (input) return input.value;
            return cell.textContent.trim();
        });
    });

    downloadXlsx(filename, headers, rows);
}

/**
 * Exports the inventory card grid to .xlsx, one row per item, in whatever
 * order the cards currently appear in (so it respects the alphabetical
 * sort toggle when applied).
 */
function exportInventoryToExcel(gridId, filename) {
    const grid = document.getElementById(gridId);
    if (!grid) return;

    const headers = ["Name", "Category", "Quantity", "Price"];
    const cards = Array.from(grid.querySelectorAll(".item-card")).filter((card) => {
        return window.getComputedStyle(card).display !== "none";
    });

    const rows = cards.map((card) => {
        const btn = card.querySelector(".edit-btn");
        return [
            btn.dataset.name || "",
            btn.dataset.category || "",
            btn.dataset.quantity || "",
            btn.dataset.price || "",
        ];
    });

    downloadXlsx(filename, headers, rows);
}
