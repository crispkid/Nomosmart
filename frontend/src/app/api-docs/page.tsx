"use client";

import {
  AlertTriangle,
  BookOpenText,
  Braces,
  CheckCircle2,
  ClipboardList,
  FileJson,
  KeyRound,
  MessageSquareText,
  Radio,
  Route,
  ShieldCheck,
  ThumbsUp,
  type LucideIcon
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { AppShell, Panel } from "@/components/AppShell";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

type DocSection = {
  id: string;
  icon: LucideIcon;
  label: TranslationKey;
  title: TranslationKey;
  description: TranslationKey;
  endpoint?: string;
  method?: string;
  bullets: TranslationKey[];
  code?: string;
  variant?: "bullet" | "checklist" | "ordered";
};

const jsonQuestionExample = `POST /api/public/v1/projects/<project_id>/chat
Authorization: Bearer <api_key>
Idempotency-Key: <unique_request_key>
Content-Type: application/json

{
  "question": "How does this policy apply to onboarding?",
  "end_user": {
    "employee_id": "E12345",
    "employee_name": "Alex Chen",
    "department": "Legal"
  },
  "scope": {
    "document_ids": ["<document_id>"]
  },
  "top_k": 5
}`;

const jsonAnswerExample = `{
  "response_id": "<response_id>",
  "status": "answered",
  "answer": "...",
  "citations": [
    {
      "document_id": "<document_id>",
      "document_version_id": "<document_version_id>",
      "chunk_id": "<chunk_id>",
      "score": 0.8123
    }
  ],
  "request_id": "<request_id>"
}`;

const sseExample = `POST /api/public/v1/projects/<project_id>/chat/stream
X-NomoSmart-API-Key: <api_key>
Idempotency-Key: <unique_request_key>
Accept: text/event-stream

event: metadata
data: {"response_id":"<response_id>","request_id":"<request_id>"}

event: delta
data: {"text":"..."}

event: citations
data: {"citations":[...]}

event: usage
data: {"input_tokens":120,"output_tokens":48}

event: done
data: {"status":"answered"}`;

const feedbackExample = `POST /api/public/v1/chat/responses/<response_id>/feedback
Authorization: Bearer <api_key>
Idempotency-Key: <unique_request_key>
Content-Type: application/json

{
  "feedback": "good",
  "comment": "Optional integration note",
  "end_user": {
    "employee_id": "E12345"
  }
}`;

const errorExample = `{
  "error": {
    "code": "integration_project_scope_denied",
    "message": "API key cannot access this project",
    "request_id": "<request_id>"
  }
}`;

const sections: DocSection[] = [
  {
    id: "overview",
    icon: BookOpenText,
    label: "apiDocsNavOverview",
    title: "apiDocsOverviewTitle",
    description: "apiDocsOverviewDescription",
    bullets: ["apiDocsOverviewPurpose", "apiDocsOverviewBoundary", "apiDocsOverviewNoMutation"],
    variant: "checklist"
  },
  {
    id: "application",
    icon: ClipboardList,
    label: "apiDocsNavApplication",
    title: "apiDocsApplicationTitle",
    description: "apiDocsApplicationDescription",
    bullets: [
      "apiDocsApplicationSystemName",
      "apiDocsApplicationPurpose",
      "apiDocsApplicationOwner",
      "apiDocsApplicationScope",
      "apiDocsApplicationRate",
      "apiDocsApplicationLifecycle"
    ],
    variant: "checklist"
  },
  {
    id: "flow",
    icon: Route,
    label: "apiDocsNavFlow",
    title: "apiDocsFlowTitle",
    description: "apiDocsFlowDescription",
    bullets: [
      "apiDocsFlowRequestKey",
      "apiDocsFlowProject",
      "apiDocsFlowIdentity",
      "apiDocsFlowApiMode",
      "apiDocsFlowPersist",
      "apiDocsFlowFeedback"
    ],
    variant: "ordered"
  },
  {
    id: "auth",
    icon: KeyRound,
    label: "apiDocsNavAuth",
    title: "apiDocsAuthTitle",
    description: "apiDocsAuthDescription",
    bullets: ["apiDocsAuthBearer", "apiDocsAuthHeader", "apiDocsAuthLifecycle", "apiDocsIdempotency"],
    code: `Authorization: Bearer <api_key>
X-NomoSmart-API-Key: <api_key>`
  },
  {
    id: "json",
    icon: FileJson,
    label: "apiDocsNavJson",
    title: "apiDocsJsonTitle",
    description: "apiDocsJsonDescription",
    method: "POST",
    endpoint: "/api/public/v1/projects/<project_id>/chat",
    bullets: ["apiDocsJsonProjectScope", "apiDocsJsonEndUser", "apiDocsJsonDocumentScope"],
    code: `${jsonQuestionExample}\n\n${jsonAnswerExample}`
  },
  {
    id: "sse",
    icon: Radio,
    label: "apiDocsNavSse",
    title: "apiDocsSseTitle",
    description: "apiDocsSseDescription",
    method: "POST",
    endpoint: "/api/public/v1/projects/<project_id>/chat/stream",
    bullets: ["apiDocsSseParity", "apiDocsSseEvents", "apiDocsSseTerminal"],
    code: sseExample
  },
  {
    id: "feedback",
    icon: ThumbsUp,
    label: "apiDocsNavFeedback",
    title: "apiDocsFeedbackTitle",
    description: "apiDocsFeedbackDescription",
    method: "POST",
    endpoint: "/api/public/v1/chat/responses/<response_id>/feedback",
    bullets: ["apiDocsFeedbackAppendOnly", "apiDocsFeedbackLatest", "apiDocsFeedbackIdentity"],
    code: feedbackExample
  },
  {
    id: "errors",
    icon: AlertTriangle,
    label: "apiDocsNavErrors",
    title: "apiDocsErrorsTitle",
    description: "apiDocsErrorsDescription",
    bullets: ["apiDocsError401", "apiDocsError403", "apiDocsError409", "apiDocsError429"],
    code: errorExample
  },
  {
    id: "safety",
    icon: ShieldCheck,
    label: "apiDocsNavSafety",
    title: "apiDocsSafetyTitle",
    description: "apiDocsSafetyDescription",
    bullets: ["apiDocsSafetyPublishedOnly", "apiDocsSafetyNoUpload", "apiDocsSafetyAudit", "apiDocsSafetySecrets", "apiDocsRetention"]
  }
];

const quickCards: Array<{ icon: LucideIcon; title: TranslationKey; body: TranslationKey }> = [
  { icon: MessageSquareText, title: "apiDocsQuickCapabilityTitle", body: "apiDocsQuickCapabilityBody" },
  { icon: ShieldCheck, title: "apiDocsQuickBoundaryTitle", body: "apiDocsQuickBoundaryBody" },
  { icon: KeyRound, title: "apiDocsQuickKeyTitle", body: "apiDocsQuickKeyBody" },
  { icon: Braces, title: "apiDocsQuickFeedbackTitle", body: "apiDocsQuickFeedbackBody" }
];

const desktopLayoutQuery = "(min-width: 1101px)";
const reducedMotionQuery = "(prefers-reduced-motion: reduce)";

function sectionIdFromHash(hash: string) {
  if (!hash.startsWith("#")) return null;
  try {
    const id = decodeURIComponent(hash.slice(1));
    return sections.some((section) => section.id === id) ? id : null;
  } catch {
    return null;
  }
}

export default function ApiDocumentationPage() {
  const { t } = useI18n();
  const [activeSection, setActiveSection] = useState(sections[0].id);
  const sectionPaneRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const scrollFrameRef = useRef<number | null>(null);
  const programmaticSectionRef = useRef<string | null>(null);
  const programmaticResetRef = useRef<number | null>(null);

  const clearProgrammaticScroll = useCallback(() => {
    programmaticSectionRef.current = null;
    if (programmaticResetRef.current !== null) {
      window.clearTimeout(programmaticResetRef.current);
      programmaticResetRef.current = null;
    }
  }, []);

  const scrollToSection = useCallback((id: string, addHistory: boolean, immediate = false) => {
    const target = sectionRefs.current[id];
    if (!target) return;
    const reduceMotion = window.matchMedia(reducedMotionQuery).matches;
    const behavior: ScrollBehavior = immediate || reduceMotion ? "auto" : "smooth";
    clearProgrammaticScroll();
    programmaticSectionRef.current = id;
    programmaticResetRef.current = window.setTimeout(() => {
      if (programmaticSectionRef.current === id) programmaticSectionRef.current = null;
      programmaticResetRef.current = null;
    }, behavior === "smooth" ? 2500 : 100);
    if (addHistory && window.location.hash !== `#${id}`) {
      window.history.pushState(null, "", `#${id}`);
    }
    setActiveSection(id);
    if (window.matchMedia(desktopLayoutQuery).matches && sectionPaneRef.current) {
      sectionPaneRef.current.scrollTo({ top: target.offsetTop, behavior });
      return;
    }
    target.scrollIntoView({ behavior, block: "start" });
  }, [clearProgrammaticScroll]);

  const syncActiveSection = useCallback(() => {
    if (programmaticSectionRef.current) {
      setActiveSection(programmaticSectionRef.current);
      return;
    }
    const pane = sectionPaneRef.current;
    let currentId = sections[0].id;
    if (window.matchMedia(desktopLayoutQuery).matches && pane) {
      const activationLine = pane.scrollTop + 24;
      for (const section of sections) {
        const target = sectionRefs.current[section.id];
        if (target && target.offsetTop <= activationLine) currentId = section.id;
      }
      if (pane.scrollHeight - pane.scrollTop - pane.clientHeight <= 2) {
        currentId = sections.at(-1)?.id ?? currentId;
      }
    } else {
      const contentTop = 92;
      let largestVisibleArea = 0;
      for (const section of sections) {
        const target = sectionRefs.current[section.id];
        if (!target) continue;
        const rect = target.getBoundingClientRect();
        const visibleArea = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, contentTop));
        if (visibleArea > largestVisibleArea) {
          largestVisibleArea = visibleArea;
          currentId = section.id;
        }
      }
    }
    setActiveSection((current) => current === currentId ? current : currentId);
  }, []);

  const scheduleActiveSync = useCallback(() => {
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      syncActiveSection();
    });
  }, [syncActiveSection]);

  useEffect(() => {
    const restoreHashSection = () => {
      const id = sectionIdFromHash(window.location.hash);
      if (id) window.requestAnimationFrame(() => scrollToSection(id, false, true));
    };
    restoreHashSection();
    window.addEventListener("hashchange", restoreHashSection);
    window.addEventListener("popstate", restoreHashSection);
    window.addEventListener("resize", scheduleActiveSync);
    window.addEventListener("scroll", scheduleActiveSync, { passive: true });
    window.addEventListener("wheel", clearProgrammaticScroll, { passive: true });
    window.addEventListener("touchstart", clearProgrammaticScroll, { passive: true });
    window.addEventListener("keydown", clearProgrammaticScroll);
    return () => {
      window.removeEventListener("hashchange", restoreHashSection);
      window.removeEventListener("popstate", restoreHashSection);
      window.removeEventListener("resize", scheduleActiveSync);
      window.removeEventListener("scroll", scheduleActiveSync);
      window.removeEventListener("wheel", clearProgrammaticScroll);
      window.removeEventListener("touchstart", clearProgrammaticScroll);
      window.removeEventListener("keydown", clearProgrammaticScroll);
      if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
      clearProgrammaticScroll();
    };
  }, [clearProgrammaticScroll, scheduleActiveSync, scrollToSection]);

  function handleSectionClick(event: MouseEvent<HTMLAnchorElement>, id: string) {
    event.preventDefault();
    scrollToSection(id, true);
  }

  return (
    <AppShell title={t("apiDocs")}>
      <section className="api-docs-hero">
        <div className="api-docs-hero-copy">
          <span className="api-docs-kicker">{t("apiDocsAudienceLabel")}</span>
          <h2>{t("apiDocsGuideTitle")}</h2>
          <p>{t("apiDocsIntro")}</p>
          <div className="api-docs-hero-badges" aria-label={t("apiDocsQuickSummary")}>
            <span>{t("apiDocsHeroBadgeReadOnly")}</span>
            <span>{t("apiDocsHeroBadgePublished")}</span>
            <span>{t("apiDocsHeroBadgeBackend")}</span>
          </div>
        </div>
        <aside className="api-docs-key-card">
          <KeyRound size={20} />
          <strong>{t("apiDocsKeyRequestTitle")}</strong>
          <p>{t("apiDocsAdminNote")}</p>
        </aside>
      </section>

      <section className="api-docs-quick-grid" aria-label={t("apiDocsQuickSummary")}>
        {quickCards.map((item) => {
          const Icon = item.icon;
          return (
            <article key={item.title}>
              <Icon size={18} />
              <div>
                <strong>{t(item.title)}</strong>
                <p>{t(item.body)}</p>
              </div>
            </article>
          );
        })}
      </section>

      <div className="api-docs-layout">
        <nav className="api-docs-nav" aria-label={t("apiDocsSectionNav")}>
          {sections.map((section) => {
            const Icon = section.icon;
            return (
              <a aria-current={activeSection === section.id ? "location" : undefined} href={`#${section.id}`} key={section.id} onClick={(event) => handleSectionClick(event, section.id)}>
                <Icon size={16} />
                <span>{t(section.label)}</span>
              </a>
            );
          })}
        </nav>

        <div className="api-docs-sections" onScroll={scheduleActiveSync} ref={sectionPaneRef}>
          {sections.map((section) => {
            const Icon = section.icon;
            return (
              <div className="api-docs-section-card" id={section.id} key={section.id} ref={(node) => { sectionRefs.current[section.id] = node; }}>
                <Panel title={t(section.title)}>
                  <section className="api-docs-section">
                  <header>
                    <span><Icon size={20} /></span>
                    <div>
                      <p>{t(section.description)}</p>
                      {section.endpoint ? (
                        <div className="api-docs-endpoint-line">
                          {section.method ? <strong>{section.method}</strong> : null}
                          <code>{section.endpoint}</code>
                        </div>
                      ) : null}
                    </div>
                  </header>
                  {section.variant === "ordered" ? (
                    <ol className="api-docs-list api-docs-list-ordered">
                      {section.bullets.map((bullet) => <li key={bullet}>{t(bullet)}</li>)}
                    </ol>
                  ) : (
                    <ul className={`api-docs-list ${section.variant === "checklist" ? "api-docs-list-check" : ""}`}>
                      {section.bullets.map((bullet) => (
                        <li key={bullet}>
                          {section.variant === "checklist" ? <CheckCircle2 size={14} /> : null}
                          <span>{t(bullet)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {section.code ? <pre><code>{section.code}</code></pre> : null}
                  </section>
                </Panel>
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
