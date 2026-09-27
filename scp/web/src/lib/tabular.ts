// Spreadsheet in, spreadsheet out: CSV/TSV text (typed, pasted or from a file) and Excel .xlsx files, read without any
// library. An .xlsx file is a zip of XML parts; the browser's DecompressionStream inflates them.

export type Grid = string[][];

/** RFC 4180 CSV, or tab-separated text when the first line has more tabs than commas (a paste from Excel). */
export function parseDelimited(text: string): Grid {
  const t = text.replace(/^﻿/, "");
  const first = t.split(/\r?\n/, 1)[0] ?? "";
  const tabs = (first.match(/\t/g) ?? []).length, commas = (first.match(/,/g) ?? []).length, semis = (first.match(/;/g) ?? []).length;
  const sep = tabs > commas && tabs >= semis ? "\t" : semis > commas ? ";" : ",";
  const rows: Grid = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (q) {
      if (c === '"' && t[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"' && cell === "") q = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return trim(rows);
}

function trim(rows: Grid): Grid {
  const out = rows.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c !== ""));
  return out;
}

export function toCsv(rows: (string | number | null | undefined)[][]): string {
  const esc = (v: string | number | null | undefined) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return rows.map((r) => r.map(esc).join(",")).join("\r\n") + "\r\n";
}

/** Save text as a file (the browser's download). */
export function download(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob(["﻿" + text], { type: `${type};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ---- xlsx --------------------------------------------------------------------------------------------------------------
interface ZipEntry { name: string; method: number; size: number; offset: number }

function zipEntries(buf: ArrayBuffer): ZipEntry[] {
  const v = new DataView(buf);
  let eocd = -1;
  for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 65557); i--) {
    if (v.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("This is not an Excel (.xlsx) file.");
  const count = v.getUint16(eocd + 10, true);
  let p = v.getUint32(eocd + 16, true);
  const dec = new TextDecoder();
  const out: ZipEntry[] = [];
  for (let n = 0; n < count; n++) {
    if (v.getUint32(p, true) !== 0x02014b50) break;
    const method = v.getUint16(p + 10, true), size = v.getUint32(p + 20, true);
    const nameLen = v.getUint16(p + 28, true), extra = v.getUint16(p + 30, true), comment = v.getUint16(p + 32, true);
    const offset = v.getUint32(p + 42, true);
    out.push({ name: dec.decode(new Uint8Array(buf, p + 46, nameLen)), method, size, offset });
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

async function zipRead(buf: ArrayBuffer, e: ZipEntry): Promise<string> {
  const v = new DataView(buf);
  const nameLen = v.getUint16(e.offset + 26, true), extra = v.getUint16(e.offset + 28, true);
  const data = new Uint8Array(buf, e.offset + 30 + nameLen + extra, e.size);
  if (e.method === 0) return new TextDecoder().decode(data);
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return await new Response(stream).text();
}

const colIndex = (ref: string) => {
  let n = 0;
  for (const ch of ref.replace(/\d+/g, "")) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
};

/** The first worksheet of an .xlsx file as text cells. Dates come out as YYYY-MM-DD when the cell is formatted as a date. */
export async function readXlsx(buf: ArrayBuffer): Promise<Grid> {
  const entries = zipEntries(buf);
  const get = (name: string) => entries.find((e) => e.name === name);
  const parse = (s: string) => new DOMParser().parseFromString(s, "application/xml");
  const shared: string[] = [];
  const ss = get("xl/sharedStrings.xml");
  if (ss) for (const si of Array.from(parse(await zipRead(buf, ss)).getElementsByTagName("si")))
    shared.push(Array.from(si.getElementsByTagName("t")).map((t) => t.textContent ?? "").join(""));
  // which number formats are dates
  const dateStyles = new Set<number>();
  const st = get("xl/styles.xml");
  if (st) {
    const doc = parse(await zipRead(buf, st));
    const custom = new Map<number, string>();
    for (const f of Array.from(doc.getElementsByTagName("numFmt"))) custom.set(Number(f.getAttribute("numFmtId")), f.getAttribute("formatCode") ?? "");
    const xfs = doc.getElementsByTagName("cellXfs")[0];
    Array.from(xfs?.getElementsByTagName("xf") ?? []).forEach((xf, i) => {
      const id = Number(xf.getAttribute("numFmtId"));
      const code = custom.get(id) ?? "";
      if ((id >= 14 && id <= 22) || (id >= 45 && id <= 47) || /[dy]/i.test(code.replace(/\[[^\]]*\]|"[^"]*"/g, ""))) dateStyles.add(i);
    });
  }
  // first sheet in workbook order
  let sheetPath = "xl/worksheets/sheet1.xml";
  const wb = get("xl/workbook.xml"), rels = get("xl/_rels/workbook.xml.rels");
  if (wb && rels) {
    const first = parse(await zipRead(buf, wb)).getElementsByTagName("sheet")[0];
    const rid = first?.getAttribute("r:id") ?? first?.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
    const rel = Array.from(parse(await zipRead(buf, rels)).getElementsByTagName("Relationship")).find((r) => r.getAttribute("Id") === rid);
    const target = rel?.getAttribute("Target");
    if (target) sheetPath = target.startsWith("/") ? target.slice(1) : `xl/${target}`;
  }
  const sheet = get(sheetPath);
  if (!sheet) throw new Error("The workbook has no worksheet.");
  const doc = parse(await zipRead(buf, sheet));
  const rows: Grid = [];
  for (const r of Array.from(doc.getElementsByTagName("row"))) {
    const out: string[] = [];
    for (const c of Array.from(r.getElementsByTagName("c"))) {
      const ref = c.getAttribute("r") ?? "";
      const i = ref ? colIndex(ref) : out.length;
      const t = c.getAttribute("t"), s = Number(c.getAttribute("s") ?? -1);
      const raw = c.getElementsByTagName("v")[0]?.textContent ?? "";
      let val = raw;
      if (t === "s") val = shared[Number(raw)] ?? "";
      else if (t === "inlineStr") val = Array.from(c.getElementsByTagName("t")).map((x) => x.textContent ?? "").join("");
      else if (t === "b") val = raw === "1" ? "TRUE" : "FALSE";
      else if (raw !== "" && dateStyles.has(s)) val = excelDate(Number(raw));
      while (out.length < i) out.push("");
      out[i] = val;
    }
    rows.push(out);
  }
  return trim(rows);
}

/** Excel's serial day number (1900 system) → YYYY-MM-DD. */
export function excelDate(serial: number): string {
  const ms = Math.round((serial - 25569) * 86400 * 1000);
  return new Date(ms).toISOString().slice(0, 10);
}

/** Read a file the user chose: .xlsx through the zip reader, anything else as delimited text. */
export async function readFile(f: File): Promise<Grid> {
  if (/\.xlsx$/i.test(f.name)) return readXlsx(await f.arrayBuffer());
  if (/\.xls$/i.test(f.name)) throw new Error("Old .xls files can't be read. In Excel, use Save As → Excel Workbook (.xlsx) or CSV.");
  return parseDelimited(await f.text());
}
