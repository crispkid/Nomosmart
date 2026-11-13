import SystemManagementShell from "@/components/SystemManagementShell";
import SystemManagementWorkspace from "@/components/SystemManagementWorkspace";
import { parseSettingsPosition } from "@/lib/systemRouteState";

type SystemPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SystemPage({ searchParams }: SystemPageProps) {
  const query = await searchParams;
  const initialPosition = parseSettingsPosition(query);
  return (
    <SystemManagementShell>
      <SystemManagementWorkspace
        initialPosition={initialPosition}
      />
    </SystemManagementShell>
  );
}
