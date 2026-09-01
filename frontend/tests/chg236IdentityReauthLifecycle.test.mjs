import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("CHG-236 keeps i18n callbacks stable after CHG-238 retires popup lifecycle", async () => {
  const [i18nClient, workspace] = await Promise.all([
    readFile(new URL("../src/lib/i18nClient.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(i18nClient, /import \{ useCallback, useSyncExternalStore \} from "react"/);
  assert.match(i18nClient, /const t = useCallback\([\s\S]*?\[locale\],[\s\S]*?\);/);
  assert.match(i18nClient, /const format = useCallback\([\s\S]*?\[locale\],[\s\S]*?\);/);

  assert.match(workspace, /window\.addEventListener\("pageshow", handlePageShow\)/);
  assert.match(workspace, /return \(\) => window\.removeEventListener\("pageshow", handlePageShow\)/);
  assert.match(workspace, /identityReauthResultProcessedRef/);
  assert.match(workspace, /processIdentityReauthResult/);
  assert.doesNotMatch(workspace, /handlePopupMessage|identityReauthPopupRef|window\.open|postMessage/);
});
