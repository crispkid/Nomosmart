import { WorkspaceChrome } from "@/components/AppShell";

// OPT424-035: one workspace chrome (navigation, notifications, account menu) for every signed-in
// workspace page, kept mounted across navigation. Pages render only their heading via AppShell.
export default function WorkspaceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <WorkspaceChrome>{children}</WorkspaceChrome>;
}
