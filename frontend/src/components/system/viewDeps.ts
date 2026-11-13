import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { ProjectResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import type { ModalState } from "./modalState";

/** Values the workspace shares with section views; each view picks what it renders with (OPT424-038). */
export type WorkspaceViewDeps = {
  t: (key: TranslationKey) => string;
  format: (key: TranslationKey, params: Record<string, string | number>) => string;
  canCreateSystemManagement: boolean;
  canEditSystemManagement: boolean;
  canDeleteSystemManagement: boolean;
  modal: ModalState | null;
  setModal: (next: SetStateAction<ModalState | null>) => void;
  discardModal: ModalState | null;
  closeModal: () => void;
  modalBlocked: boolean;
  submitting: boolean;
  sectionReady: (section: string) => boolean;
  renderSectionReadNotice: (section: string, title?: string, announce?: boolean) => ReactNode;
  renderListPager: (section: string, page: number, size: number, total: number | null, previous: () => void, next: (() => void) | null, changeSize: (size: number) => void) => ReactNode;
  renderProjectSearch: () => ReactNode;
  activeProjects: ProjectResponse[];
  projectNameById: Map<string, string>;
  clientNextCursor: string | null;
  setClientNextCursor: Dispatch<SetStateAction<string | null>>;
};
