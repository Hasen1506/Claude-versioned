import { tmpdir } from "node:os";
import { join } from "node:path";

// the folder the main test server reads scheduled imports from (SCP_IMPORT_DIR), one folder per company inside it
export const importDir = join(tmpdir(), "scp-e2e-imports");
