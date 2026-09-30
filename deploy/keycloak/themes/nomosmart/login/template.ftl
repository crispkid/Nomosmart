<#import "field.ftl" as field>
<#import "footer.ftl" as loginFooter>

<#macro username>
  <#assign label>
    <#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if>
  </#assign>
  <@field.group name="username" label=label>
    <div class="${properties.kcInputGroup}">
      <div class="${properties.kcInputGroupItemClass} ${properties.kcFill}">
        <span class="${properties.kcInputClass} ${properties.kcFormReadOnlyClass}">
          <input id="kc-attempted-username" value="${auth.attemptedUsername}" readonly>
        </span>
      </div>
      <div class="${properties.kcInputGroupItemClass}">
        <button id="reset-login" class="${properties.kcFormPasswordVisibilityButtonClass} kc-login-tooltip" type="button"
                aria-label="${msg('restartLoginTooltip')}" onclick="location.href='${url.loginRestartFlowUrl}'">
          <i class="fa-sync-alt fas" aria-hidden="true"></i>
          <span class="kc-tooltip-text">${msg("restartLoginTooltip")}</span>
        </button>
      </div>
    </div>
  </@field.group>
</#macro>

<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html lang="<#if realm.internationalizationEnabled>${locale.currentLanguageTag}<#else>zh-TW</#if>"
      dir="<#if realm.internationalizationEnabled>${(locale.rtl)?then('rtl','ltr')}<#else>ltr</#if>"
      class="${properties.kcHtmlClass!}">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>${msg("nomosmartBrowserTitle")}</title>
  <link rel="icon" href="${url.resourcesPath}/img/favicon.ico">
  <#if properties.stylesCommon?has_content>
    <#list properties.stylesCommon?split(' ') as style>
      <link href="${url.resourcesCommonPath}/${style}" rel="stylesheet">
    </#list>
  </#if>
  <#if properties.styles?has_content>
    <#list properties.styles?split(' ') as style>
      <link href="${url.resourcesPath}/${style}" rel="stylesheet">
    </#list>
  </#if>
  <script type="importmap">
    {"imports":{"rfc4648":"${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"}}
  </script>
  <#if properties.scripts?has_content>
    <#list properties.scripts?split(' ') as script>
      <script src="${url.resourcesPath}/${script}" type="text/javascript"></script>
    </#list>
  </#if>
  <#if scripts??>
    <#list scripts as script>
      <script src="${script}" type="text/javascript"></script>
    </#list>
  </#if>
  <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
  <script type="module">
    import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";
    startSessionPolling("${url.ssoLoginInOtherTabsUrl?no_esc}");
  </script>
</head>
<body id="keycloak-bg" class="${properties.kcBodyClass!} ${bodyClass}" data-submitting-label="${msg('nomosmartSubmitting')}">
  <div class="nomosmart-auth ${properties.kcLogin!}">
    <div class="nomosmart-auth-shell ${properties.kcLoginContainer!}">
      <aside id="kc-header" class="nomosmart-auth-context" aria-labelledby="nomosmart-context-title">
        <div id="kc-header-wrapper" class="nomosmart-brand">
          <span class="nomosmart-brand-mark" aria-hidden="true">N</span>
          <span class="nomosmart-brand-copy">
            <strong>NomoSmart</strong>
            <small>${msg("nomosmartBrandTagline")}</small>
          </span>
        </div>

        <div class="nomosmart-auth-context-copy">
          <span class="nomosmart-context-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.6 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.6 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z"></path>
              <path d="m9 12 2 2 4-4"></path>
            </svg>
          </span>
          <p class="nomosmart-eyebrow">${msg("nomosmartAuthEyebrow")}</p>
          <h2 id="nomosmart-context-title">${msg("nomosmartAuthTitle")}</h2>
          <p class="nomosmart-context-description">${msg("nomosmartAuthDescription")}</p>
        </div>

        <div class="nomosmart-trust-note">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="16" r="1"></circle>
            <rect x="3" y="10" width="18" height="12" rx="2"></rect>
            <path d="M7 10V7a5 5 0 0 1 10 0v3"></path>
          </svg>
          <span>${msg("nomosmartAuthTrust")}</span>
        </div>
      </aside>

      <main class="nomosmart-auth-workspace ${properties.kcLoginMain!}">
        <div class="nomosmart-auth-toolbar">
          <#if realm.internationalizationEnabled && locale.supported?size gt 1>
            <label class="nomosmart-language" for="login-select-toggle">
              <span>${msg("nomosmartLanguageLabel")}</span>
              <span class="nomosmart-language-control">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="10"></circle>
                  <path d="M2 12h20"></path>
                  <path d="M12 2a15.3 15.3 0 0 1 0 20"></path>
                  <path d="M12 2a15.3 15.3 0 0 0 0 20"></path>
                </svg>
                <select aria-label="${msg('languages')}" id="login-select-toggle"
                        onchange="if (this.value) window.location.href=this.value">
                  <#list locale.supported?sort_by("label") as l>
                    <option value="${l.url}" ${(l.languageTag == locale.currentLanguageTag)?then('selected','')}>
                      <#if l.languageTag == "zh-TW">${msg("nomosmartLocaleZhTw")}<#else>${msg("nomosmartLocaleEn")}</#if>
                    </option>
                  </#list>
                </select>
              </span>
            </label>
          </#if>
        </div>

        <header class="nomosmart-auth-header ${properties.kcLoginMainHeader!}">
          <h1 class="${properties.kcLoginMainTitle!}" id="kc-page-title"><#nested "header"></h1>
        </header>

        <div class="nomosmart-auth-body ${properties.kcLoginMainBody!}">
          <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
            <#if displayRequiredFields>
              <div class="${properties.kcContentWrapperClass!}">
                <div class="${properties.kcLabelWrapperClass!} subtitle">
                  <span class="${properties.kcInputHelperTextItemTextClass!}">
                    <span class="${properties.kcInputRequiredClass!}">*</span> ${msg("requiredFields")}
                  </span>
                </div>
              </div>
            </#if>
          <#else>
            <#if displayRequiredFields>
              <div class="${properties.kcContentWrapperClass!}">
                <div class="${properties.kcLabelWrapperClass!} subtitle">
                  <span class="${properties.kcInputHelperTextItemTextClass!}">
                    <span class="${properties.kcInputRequiredClass!}">*</span> ${msg("requiredFields")}
                  </span>
                </div>
                <div class="${properties.kcFormClass} ${properties.kcContentWrapperClass}">
                  <#nested "show-username">
                  <@username />
                </div>
              </div>
            <#else>
              <div class="${properties.kcFormClass} ${properties.kcContentWrapperClass}">
                <#nested "show-username">
                <@username />
              </div>
            </#if>
          </#if>

          <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
            <div class="nomosmart-auth-alert ${properties.kcAlertClass!} pf-m-${(message.type = 'error')?then('danger', message.type)}"
                 role="${(message.type = 'error')?then('alert','status')}"
                 aria-live="${(message.type = 'error')?then('assertive','polite')}">
              <div class="${properties.kcAlertIconClass!}" aria-hidden="true">
                <#if message.type = 'success'><span class="${properties.kcFeedbackSuccessIcon!}"></span></#if>
                <#if message.type = 'warning'><span class="${properties.kcFeedbackWarningIcon!}"></span></#if>
                <#if message.type = 'error'><span class="${properties.kcFeedbackErrorIcon!}"></span></#if>
                <#if message.type = 'info'><span class="${properties.kcFeedbackInfoIcon!}"></span></#if>
              </div>
              <span class="${properties.kcAlertTitleClass!} kc-feedback-text">${kcSanitize(message.summary)?no_esc}</span>
            </div>
          </#if>

          <#nested "form">

          <#if auth?has_content && auth.showTryAnotherWayLink()>
            <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post" novalidate="novalidate">
              <input type="hidden" name="tryAnotherWay" value="on">
              <button id="try-another-way" type="submit"
                      class="${properties.kcButtonSecondaryClass} ${properties.kcButtonBlockClass} ${properties.kcMarginTopClass}">
                ${kcSanitize(msg("doTryAnotherWay"))?no_esc}
              </button>
            </form>
          </#if>

          <#if displayInfo>
            <div id="kc-info" class="${properties.kcSignUpClass!}">
              <div id="kc-info-wrapper" class="${properties.kcInfoAreaWrapperClass!}">
                <#nested "info">
              </div>
            </div>
          </#if>

          <div class="nomosmart-social-providers">
            <#nested "socialProviders">
          </div>
        </div>

        <footer class="nomosmart-auth-footer">
          <@loginFooter.content/>
          <span>${msg("nomosmartSecurityFooter")}</span>
        </footer>
      </main>
    </div>
  </div>
</body>
</html>
</#macro>
