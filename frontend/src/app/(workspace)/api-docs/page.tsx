"use client";

import {
  AlertTriangle,
  BookOpenText,
  Braces,
  CheckCircle2,
  ClipboardList,
  FileJson,
  Gauge,
  KeyRound,
  MessageSquareText,
  MessagesSquare,
  Radio,
  Route,
  ShieldCheck,
  Terminal,
  ThumbsUp,
  type LucideIcon
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { AppShell, Panel } from "@/components/AppShell";
import { ApiCodeExample } from "@/components/ApiCodeExample";
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

const quickstartExample = `curl -sS https://<nomosmart_host>/api/public/v1/responses \\
  -H "Authorization: Bearer <api_key>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "nomosmart:project/<project_id>",
    "input": "What is the annual leave policy?",
    "nomosmart:end_user": { "employee_id": "E12345" }
  }'

# Response (fields trimmed)
{
  "id": "resp_<response_id>",
  "status": "completed",
  "output": [{ "type": "message", "content": [{ "type": "output_text", "text": "... [1]", "annotations": [...] }] }],
  "nomosmart:answer_status": "answered",
  "nomosmart:request_id": "<request_id>"
}`;

const jsonQuestionExample = `POST /api/public/v1/responses
Authorization: Bearer <api_key>
Idempotency-Key: <unique_request_key>
Content-Type: application/json

{
  "model": "nomosmart:project/<project_id>",
  "input": "How does this policy apply to onboarding?",
  "nomosmart:end_user": {
    "employee_id": "E12345",
    "employee_name": "Alex Chen",
    "department": "Legal"
  },
  "nomosmart:scope": {
    "document_ids": ["<document_id>"]
  },
  "nomosmart:top_k": 5,
  "nomosmart:top_p": 0.8
}`;

const jsonAnswerExample = `{
  "id": "resp_<response_id>",
  "object": "response",
  "created_at": 1763300000,
  "status": "completed",
  "model": "nomosmart:project/<project_id>",
  "previous_response_id": null,
  "output": [{
    "type": "message",
    "role": "assistant",
    "status": "completed",
    "content": [{
      "type": "output_text",
      "text": "... [1]",
      "annotations": [{
        "type": "url_citation",
        "url": "https://<nomosmart_host>/project/<project_id>/knowledge/<document_id>",
        "title": "<document_title>",
        "start_index": 4,
        "end_index": 7,
        "nomosmart:citation": {
          "document_id": "<document_id>",
          "document_version_id": "<document_version_id>",
          "chunk_id": "<chunk_id>",
          "excerpt": "...",
          "score": 0.8123
        }
      }]
    }]
  }],
  "usage": { "input_tokens": 120, "output_tokens": 48, "total_tokens": 168, ... },
  "nomosmart:answer_status": "answered",
  "nomosmart:request_id": "<request_id>",
  "nomosmart:selected_document_ids": ["<document_id>"],
  "nomosmart:context": { "turns_used": 0, "truncated": false, "rewritten_query": null, "rewrite_status": "not_needed" },
  ...
}`;

const sseExample = `POST /api/public/v1/responses
Authorization: Bearer <api_key>
Idempotency-Key: <unique_request_key>
Accept: text/event-stream

{ "model": "nomosmart:project/<project_id>", "input": "...", "stream": true,
  "nomosmart:end_user": { "employee_id": "E12345" } }

event: response.created
data: {"type":"response.created","sequence_number":1,"response":{"id":"resp_<response_id>","status":"in_progress",...}}

event: response.in_progress
data: {"type":"response.in_progress","sequence_number":2,"response":{...}}

event: response.output_item.added
data: {"type":"response.output_item.added","sequence_number":3,"output_index":0,"item":{...}}

event: response.content_part.added
data: {"type":"response.content_part.added","sequence_number":4,"item_id":"msg_<id>","part":{...}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","sequence_number":5,"item_id":"msg_<id>","delta":"..."}

(more response.output_text.delta events)

event: response.output_text.annotation.added
data: {"type":"response.output_text.annotation.added","sequence_number":9,"annotation_index":0,"annotation":{"type":"url_citation",...}}

event: response.output_text.done
data: {"type":"response.output_text.done","sequence_number":10,"text":"... [1]",...}

event: response.content_part.done
data: {"type":"response.content_part.done","sequence_number":11,...}

event: response.output_item.done
data: {"type":"response.output_item.done","sequence_number":12,...}

event: response.completed
data: {"type":"response.completed","sequence_number":13,"response":{"id":"resp_<response_id>","status":"completed",...}}

# On failure, instead of the remaining events:
event: error
data: {"type":"error","sequence_number":7,"error":{"type":"model_error","code":"...","message":"...","param":null},"nomosmart:request_id":"<request_id>"}

event: response.failed
data: {"type":"response.failed","sequence_number":8,"response":{"status":"failed",...}}`;

const multiTurnExample = `POST /api/public/v1/responses
Authorization: Bearer <api_key>
Content-Type: application/json

{
  "model": "nomosmart:project/<project_id>",
  "input": "What about managers?",
  "previous_response_id": "resp_<previous_response_id>",
  "truncation": "auto",
  "nomosmart:end_user": { "employee_id": "E12345" }
}

{
  "id": "resp_<response_id>",
  "previous_response_id": "resp_<previous_response_id>",
  "nomosmart:context": {
    "turns_used": 1,
    "truncated": false,
    "rewritten_query": "How early must managers request leave?",
    "rewrite_status": "rewritten"
  },
  ...
}`;

const sdkExample = `from openai import OpenAI

client = OpenAI(base_url="https://<nomosmart_host>/api/public/v1", api_key="<api_key>")
response = client.responses.create(
    model="nomosmart:project/<project_id>",
    input="How does this policy apply to onboarding?",
    extra_body={"nomosmart:end_user": {"employee_id": "E12345"}},
)
print(response.output_text)`;

const feedbackExample = `POST /api/public/v1/responses/resp_<response_id>/feedback
Authorization: Bearer <api_key>
Idempotency-Key: <unique_request_key>
Content-Type: application/json

{
  "feedback": "good",
  "comment": "Optional integration note",
  "end_user": {
    "employee_id": "E12345"
  }
}

# Response
{
  "feedback_event_id": "<feedback_event_id>",
  "response_id": "resp_<response_id>",
  "latest_feedback": "good",
  "comment": "Optional integration note",
  "created_at": "2026-11-16T08:00:00Z"
}`;

const errorExample = `{
  "error": {
    "type": "permission_error",
    "code": "integration_project_scope_denied",
    "message": "API key cannot access this project",
    "param": null
  },
  "nomosmart:request_id": "<request_id>"
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
    id: "quickstart",
    icon: Terminal,
    label: "apiDocsNavQuickstart",
    title: "apiDocsQuickstartTitle",
    description: "apiDocsQuickstartDescription",
    method: "POST",
    endpoint: "/api/public/v1/responses",
    bullets: ["apiDocsQuickstartStepKey", "apiDocsQuickstartStepRun", "apiDocsQuickstartStepRead"],
    code: quickstartExample,
    variant: "ordered"
  },
  {
    id: "json",
    icon: FileJson,
    label: "apiDocsNavJson",
    title: "apiDocsJsonTitle",
    description: "apiDocsJsonDescription",
    method: "POST",
    endpoint: "/api/public/v1/responses",
    bullets: ["apiDocsJsonProjectScope", "apiDocsJsonEndUser", "apiDocsJsonDocumentScope", "apiDocsJsonNoAnswer"],
    code: `${jsonQuestionExample}\n\n${jsonAnswerExample}`
  },
  {
    id: "sse",
    icon: Radio,
    label: "apiDocsNavSse",
    title: "apiDocsSseTitle",
    description: "apiDocsSseDescription",
    method: "POST",
    endpoint: "/api/public/v1/responses",
    bullets: ["apiDocsSseParity", "apiDocsSseEvents", "apiDocsSseUnknown", "apiDocsSseTerminal", "apiDocsSseInterrupt"],
    code: sseExample
  },
  {
    id: "multiturn",
    icon: MessagesSquare,
    label: "apiDocsNavMultiTurn",
    title: "apiDocsMultiTurnTitle",
    description: "apiDocsMultiTurnDescription",
    method: "POST",
    endpoint: "/api/public/v1/responses",
    bullets: ["apiDocsMultiTurnPrevious", "apiDocsMultiTurnIdentity", "apiDocsMultiTurnLimits", "apiDocsMultiTurnContext"],
    code: multiTurnExample
  },
  {
    id: "sdk",
    icon: Braces,
    label: "apiDocsNavSdk",
    title: "apiDocsSdkTitle",
    description: "apiDocsSdkDescription",
    bullets: ["apiDocsSdkBaseUrl", "apiDocsSdkExtensions", "apiDocsSdkUnsupported"],
    code: sdkExample
  },
  {
    id: "feedback",
    icon: ThumbsUp,
    label: "apiDocsNavFeedback",
    title: "apiDocsFeedbackTitle",
    description: "apiDocsFeedbackDescription",
    method: "POST",
    endpoint: "/api/public/v1/responses/resp_<response_id>/feedback",
    bullets: ["apiDocsFeedbackValues", "apiDocsFeedbackIdentity", "apiDocsFeedbackAppendOnly", "apiDocsFeedbackLatest"],
    code: feedbackExample
  },
  {
    id: "limits",
    icon: Gauge,
    label: "apiDocsNavLimits",
    title: "apiDocsLimitsTitle",
    description: "apiDocsLimitsDescription",
    bullets: [
      "apiDocsLimitsInput",
      "apiDocsLimitsTopK",
      "apiDocsLimitsTopP",
      "apiDocsLimitsMetadata",
      "apiDocsLimitsEndUser",
      "apiDocsLimitsIdempotency",
      "apiDocsLimitsRate",
      "apiDocsLimitsHistory"
    ]
  },
  {
    id: "errors",
    icon: AlertTriangle,
    label: "apiDocsNavErrors",
    title: "apiDocsErrorsTitle",
    description: "apiDocsErrorsDescription",
    bullets: [
      "apiDocsError400",
      "apiDocsError401",
      "apiDocsError403",
      "apiDocsError404",
      "apiDocsError409",
      "apiDocsError422",
      "apiDocsError429",
      "apiDocsError502",
      "apiDocsError503",
      "apiDocsErrorRetry"
    ],
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

const desktopLayoutQuery = "(min-width: 1025px)";
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
                  {section.code ? <ApiCodeExample code={section.code} title={t(section.title)} /> : null}
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
