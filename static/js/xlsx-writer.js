/**
 * Minimal, dependency-free .xlsx (OOXML) writer.
 *
 * Builds a single-sheet Excel workbook entirely in the browser using the
 * ZIP "store" (no compression) method, so no external library or CDN is
 * required. Values that look numeric are written as real Excel numbers;
 * everything else is written as inline text.
 */
(function (global) {
    "use strict";

    // ---- CRC32 -------------------------------------------------------
    const CRC_TABLE = (function () {
        const table = new Uint32Array(256);
        for (let n = 0; n < 256; n++) {
            let c = n;
            for (let k = 0; k < 8; k++) {
                c = c & 1 ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
            }
            table[n] = c >>> 0;
        }
        return table;
    })();

    function crc32(bytes) {
        let crc = 0xffffffff;
        for (let i = 0; i < bytes.length; i++) {
            crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
        }
        return (crc ^ 0xffffffff) >>> 0;
    }

    // ---- Small byte-buffer writer ------------------------------------
    class ByteWriter {
        constructor() {
            this.chunks = [];
            this.length = 0;
        }
        u16(v) {
            const b = new Uint8Array(2);
            new DataView(b.buffer).setUint16(0, v, true);
            this._push(b);
        }
        u32(v) {
            const b = new Uint8Array(4);
            new DataView(b.buffer).setUint32(0, v, true);
            this._push(b);
        }
        bytes(b) {
            this._push(b instanceof Uint8Array ? b : new Uint8Array(b));
        }
        _push(b) {
            this.chunks.push(b);
            this.length += b.length;
        }
        toUint8Array() {
            const out = new Uint8Array(this.length);
            let offset = 0;
            for (const c of this.chunks) {
                out.set(c, offset);
                offset += c.length;
            }
            return out;
        }
    }

    const utf8 = (str) => new TextEncoder().encode(str);

    // ---- ZIP (store method, no compression) ---------------------------
    function buildZip(files) {
        const w = new ByteWriter();
        const central = [];

        for (const { name, data } of files) {
            const nameBytes = utf8(name);
            const crc = crc32(data);
            const offset = w.length;

            w.u32(0x04034b50); // local file header signature
            w.u16(20);         // version needed
            w.u16(0);          // flags
            w.u16(0);          // method: store
            w.u16(0);          // mod time
            w.u16(0x21);       // mod date (Jan 1 1980 - arbitrary valid date)
            w.u32(crc);
            w.u32(data.length); // compressed size
            w.u32(data.length); // uncompressed size
            w.u16(nameBytes.length);
            w.u16(0);           // extra field length
            w.bytes(nameBytes);
            w.bytes(data);

            central.push({ nameBytes, crc, size: data.length, offset });
        }

        const cdStart = w.length;
        for (const e of central) {
            w.u32(0x02014b50); // central directory header signature
            w.u16(20);         // version made by
            w.u16(20);         // version needed
            w.u16(0);          // flags
            w.u16(0);          // method
            w.u16(0);          // mod time
            w.u16(0x21);       // mod date
            w.u32(e.crc);
            w.u32(e.size);
            w.u32(e.size);
            w.u16(e.nameBytes.length);
            w.u16(0);          // extra length
            w.u16(0);          // comment length
            w.u16(0);          // disk number start
            w.u16(0);          // internal attrs
            w.u32(0);          // external attrs
            w.u32(e.offset);
            w.bytes(e.nameBytes);
        }
        const cdEnd = w.length;

        w.u32(0x06054b50); // end of central directory signature
        w.u16(0);          // disk number
        w.u16(0);          // disk with central directory
        w.u16(central.length);
        w.u16(central.length);
        w.u32(cdEnd - cdStart);
        w.u32(cdStart);
        w.u16(0);          // comment length

        return w.toUint8Array();
    }

    // ---- OOXML (spreadsheet XML) parts --------------------------------
    function escapeXml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function colName(idx) {
        let name = "";
        idx += 1;
        while (idx > 0) {
            const rem = (idx - 1) % 26;
            name = String.fromCharCode(65 + rem) + name;
            idx = Math.floor((idx - 1) / 26);
        }
        return name;
    }

    // Treat a value as a real number only if it round-trips cleanly
    // (avoids turning things like phone numbers, "007", or IDs with
    // leading zeros into numbers and losing the leading zero).
    function isPlainNumber(str) {
        if (str === "" || str === null || str === undefined) return false;
        if (!/^-?\d+(\.\d+)?$/.test(str)) return false;
        if (str.length > 1 && str.startsWith("0") && !str.startsWith("0.")) return false;
        return true;
    }

    function buildSheetXml(headers, rows) {
        const allRows = [headers, ...rows];
        const rowXml = allRows.map((row, rIdx) => {
            const cells = row.map((val, cIdx) => {
                const ref = colName(cIdx) + (rIdx + 1);
                const str = val === null || val === undefined ? "" : String(val);
                if (isPlainNumber(str)) {
                    return `<c r="${ref}"><v>${escapeXml(str)}</v></c>`;
                }
                return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(str)}</t></is></c>`;
            }).join("");
            return `<row r="${rIdx + 1}">${cells}</row>`;
        }).join("");

        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + `<sheetData>${rowXml}</sheetData></worksheet>`;
    }

    function buildWorkbook(headers, rows, sheetName) {
        const contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            + '<Default Extension="xml" ContentType="application/xml"/>'
            + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            + '</Types>';

        const rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            + '</Relationships>';

        const workbookXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            + `<sheets><sheet name="${escapeXml(sheetName)}" sheetId="1" r:id="rId1"/></sheets></workbook>`;

        const workbookRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            + '</Relationships>';

        const sheetXml = buildSheetXml(headers, rows);

        return buildZip([
            { name: "[Content_Types].xml", data: utf8(contentTypes) },
            { name: "_rels/.rels", data: utf8(rootRels) },
            { name: "xl/workbook.xml", data: utf8(workbookXml) },
            { name: "xl/_rels/workbook.xml.rels", data: utf8(workbookRels) },
            { name: "xl/worksheets/sheet1.xml", data: utf8(sheetXml) },
        ]);
    }

    /**
     * Generates and downloads an .xlsx file.
     * @param {string} filename
     * @param {string[]} headers
     * @param {Array<Array<string|number>>} rows
     * @param {string} [sheetName]
     */
    function downloadXlsx(filename, headers, rows, sheetName) {
        const bytes = buildWorkbook(headers, rows, sheetName || "Sheet1");
        const blob = new Blob([bytes], {
            type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    global.downloadXlsx = downloadXlsx;
})(window);
