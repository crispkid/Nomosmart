import { AppShell } from "@/components/AppShell";
import SystemManagementWorkspace from "@/components/SystemManagementWorkspace";
import { t } from "@/lib/i18n";
import { parseIdentityReauthResult, parseSystemTab } from "@/lib/systemRouteState";

type SystemPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SystemPage({ searchParams }: SystemPageProps) {
  const query = await searchParams;
  const initialTab = parseSystemTab(query.tab);
  const initialReauthResult = parseIdentityReauthResult(query.reauth);
  const invalidReauthResult = query.reauth !== undefined && initialReauthResult === null;
  return (
    <AppShell title={t("system")}>
      <SystemManagementWorkspace
        initialReauthResult={initialReauthResult}
        initialTab={initialTab}
        invalidReauthResult={invalidReauthResult}
      />
    </AppShell>
  );
}
