// Spreadsheet-style entry for the app's number grids: paste a block copied from Excel / Google Sheets (tab-separated
// rows), fill a value to the right (Ctrl+R) and copy it down (Ctrl+D), as a planner does in a spreadsheet.

/** A pasted block: rows of cells, each a number, null for an empty cell, or NaN for text that is not a number. */
export function parseGrid(text: string): number[][] | null {
  const t = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (!t.includes("\t") && !t.includes("\n")) return null;          // one value: let the input paste it normally
  return t.split("\n").map((row) => row.split("\t").map(cell));
}

/** One cell as a spreadsheet shows it: "1,250" and "1 250" are 1250, "" is empty (NaN marks text that is not a number). */
export function cell(raw: string): number {
  const s = raw.trim().replace(/^"|"$/g, "").replace(/[,\s\u00a0]/g, "");
  if (s === "" || s === "-") return 0;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
}

/** The writes a block pasted at (row, col) makes, clipped to the grid; cells that are not numbers are skipped and counted. */
export function placeBlock(block: number[][], row: number, col: number, rows: number, cols: number) {
  const writes: { r: number; c: number; v: number }[] = [];
  let skipped = 0, clipped = 0;
  block.forEach((line, i) => line.forEach((v, j) => {
    const r = row + i, c = col + j;
    if (r >= rows || c >= cols) { clipped++; return; }
    if (Number.isNaN(v)) { skipped++; return; }
    writes.push({ r, c, v });
  }));
  return { writes, skipped, clipped };
}

/** Ctrl+R (fill right) or Ctrl+D (copy down) on a grid cell, else null. */
export function fillKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }): "right" | "down" | null {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return null;
  const k = e.key.toLowerCase();
  return k === "r" ? "right" : k === "d" ? "down" : null;
}

/** What a paste or fill did, in a sentence for the page. */
export function pasteNote(n: number, skipped: number, clipped: number): string {
  return `${n} cell${n === 1 ? "" : "s"} filled` + (skipped ? `; ${skipped} not a number, left as they were` : "")
    + (clipped ? `; ${clipped} beyond the grid left out` : "") + ". Undo takes it back in one step.";
}
