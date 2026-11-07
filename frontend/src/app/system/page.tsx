import SystemManagementShell from "@/components/SystemManagementShell";
import SystemManagementWorkspace from "@/components/SystemManagementWorkspace";
import { parseSystemTab } from "@/lib/systemRouteState";

type SystemPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SystemPage({ searchParams }: SystemPageProps) {
  const query = await searchParams;
  const initialTab = parseSystemTab(query.tab);
  return (
    <SystemManagementShell>
      <SystemManagementWorkspace
        initialTab={initialTab}
      />
    </SystemManagementShell>
  );
}
