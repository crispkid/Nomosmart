const VISIBLE_ATTRIBUTES = new Set([
  "alt",
  "aria-description",
  "aria-label",
  "data-tooltip",
  "placeholder",
  "title",
  "tooltip"
]);

const FIXED_LOCALE_METHODS = new Set([
  "toLocaleDateString",
  "toLocaleString",
  "toLocaleTimeString"
]);

const ALLOWLIST_CATEGORIES = new Set([
  "externalBrand",
  "protocol",
  "stableField",
  "technicalId"
]);

function normalized(value) {
  return String(value).replace(/\s+/g, " ").trim();
}

function withoutBoundaryPunctuation(value) {
  return value.replace(/^[\s·|/,:;()[\]{}–—-]+|[\s·|/,:;()[\]{}–—-]+$/gu, "");
}

function hasVisibleLanguage(value) {
  return /\p{L}/u.test(value);
}

function literalValues(node) {
  if (!node) return [];
  if (node.type === "Literal" && typeof node.value === "string") return [node.value];
  if (node.type === "TemplateLiteral") {
    return node.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw);
  }
  if (node.type === "ConditionalExpression") {
    return [...literalValues(node.consequent), ...literalValues(node.alternate)];
  }
  if (node.type === "LogicalExpression" || (node.type === "BinaryExpression" && node.operator === "+")) {
    return [...literalValues(node.left), ...literalValues(node.right)];
  }
  if (node.type === "ArrayExpression") {
    return node.elements.flatMap((element) => literalValues(element));
  }
  return [];
}

function directLiteralValue(node) {
  if (!node) return null;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateLiteral" && node.expressions.length === 0) {
    return node.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join("");
  }
  return null;
}

function compileAllowlist(value) {
  const allowed = new Set();
  let invalid = false;
  if (!value || typeof value !== "object" || Array.isArray(value)) return { allowed, invalid };
  for (const [category, entries] of Object.entries(value)) {
    if (!ALLOWLIST_CATEGORIES.has(category) || !Array.isArray(entries)) {
      invalid = true;
      continue;
    }
    for (const entry of entries) {
      if (
        typeof entry !== "string" ||
        entry !== normalized(entry) ||
        !entry ||
        entry.includes("*") ||
        entry.startsWith("/") ||
        entry.endsWith("/")
      ) {
        invalid = true;
        continue;
      }
      allowed.add(entry);
    }
  }
  return { allowed, invalid };
}

function attributeName(node) {
  if (!node || node.type !== "JSXIdentifier") return null;
  return node.name.toLowerCase();
}

function memberPropertyName(node) {
  if (!node || node.type !== "MemberExpression") return null;
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") return node.property.value;
  return null;
}

function rootIdentifierName(node) {
  let current = node;
  while (current?.type === "MemberExpression") current = current.object;
  return current?.type === "Identifier" ? current.name : null;
}

function containsUnsafeRuntimeMessage(node) {
  if (!node) return false;
  if (node.type === "MemberExpression") {
    const property = memberPropertyName(node);
    const root = rootIdentifierName(node);
    if (["error_message", "error_summary", "block_reasons"].includes(property)) return true;
    if (property === "message" && ["error", "caught", "reason", "notification"].includes(root)) return true;
    return containsUnsafeRuntimeMessage(node.object);
  }
  if (node.type === "CallExpression") {
    if (node.callee.type === "Identifier" && ["localize", "localizeKnown", "operationalCodeMessage", "operationalErrorMessage"].includes(node.callee.name)) return false;
    return containsUnsafeRuntimeMessage(node.callee) || node.arguments.some((argument) => argument.type !== "SpreadElement" && containsUnsafeRuntimeMessage(argument));
  }
  if (node.type === "ConditionalExpression") return containsUnsafeRuntimeMessage(node.test) || containsUnsafeRuntimeMessage(node.consequent) || containsUnsafeRuntimeMessage(node.alternate);
  if (node.type === "LogicalExpression" || node.type === "BinaryExpression") return containsUnsafeRuntimeMessage(node.left) || containsUnsafeRuntimeMessage(node.right);
  return false;
}

const rule = {
  meta: {
    type: "problem",
    docs: {
      description: "Require visible JSX copy and locale formatting to use the runtime i18n contract"
    },
    schema: [
      {
        type: "object",
        properties: {
          allowlist: {
            type: "object",
            properties: {
              externalBrand: { type: "array", items: { type: "string" }, uniqueItems: true },
              protocol: { type: "array", items: { type: "string" }, uniqueItems: true },
              stableField: { type: "array", items: { type: "string" }, uniqueItems: true },
              technicalId: { type: "array", items: { type: "string" }, uniqueItems: true }
            },
            additionalProperties: false
          }
        },
        additionalProperties: false
      }
    ],
    messages: {
      fixedLocale: "Use the active runtime locale instead of hard-coded locale {{locale}}.",
      invalidAllowlist: "The visible-text allowlist must contain reviewed exact literals in typed categories.",
      visibleAttribute: "Move visible {{attribute}} copy {{value}} into the i18n locale contract.",
      runtimeMessage: "Map runtime Backend/exception messages through the operational i18n resolver before rendering.",
      visibleText: "Move visible copy {{value}} into the i18n locale contract."
    }
  },
  create(context) {
    const { allowed, invalid } = compileAllowlist(context.options[0]?.allowlist);

    function reportVisible(node, value, attribute = null) {
      const text = normalized(value);
      if (
        !text ||
        !hasVisibleLanguage(text) ||
        allowed.has(text) ||
        allowed.has(withoutBoundaryPunctuation(text))
      ) {
        return;
      }
      context.report({
        node,
        messageId: attribute ? "visibleAttribute" : "visibleText",
        data: {
          attribute: attribute ?? "",
          value: JSON.stringify(text)
        }
      });
    }

    return {
      Program(node) {
        if (invalid) context.report({ node, messageId: "invalidAllowlist" });
      },
      JSXAttribute(node) {
        const name = attributeName(node.name);
        if (!name || !VISIBLE_ATTRIBUTES.has(name)) return;
        if (node.value?.type === "Literal") {
          reportVisible(node.value, node.value.value, name);
          return;
        }
        if (node.value?.type === "JSXExpressionContainer") {
          for (const value of literalValues(node.value.expression)) {
            reportVisible(node.value.expression, value, name);
          }
        }
      },
      JSXExpressionContainer(node) {
        if (node.parent?.type === "JSXAttribute") return;
        if (containsUnsafeRuntimeMessage(node.expression)) context.report({ node: node.expression, messageId: "runtimeMessage" });
        for (const value of literalValues(node.expression)) {
          reportVisible(node.expression, value);
        }
      },
      JSXText(node) {
        reportVisible(node, node.value);
      },
      CallExpression(node) {
        if (
          node.callee.type !== "MemberExpression" ||
          node.callee.computed ||
          node.callee.property.type !== "Identifier" ||
          !FIXED_LOCALE_METHODS.has(node.callee.property.name)
        ) {
          return;
        }
        const locale = directLiteralValue(node.arguments[0]);
        if (locale?.trim()) {
          context.report({
            node: node.arguments[0],
            messageId: "fixedLocale",
            data: { locale: JSON.stringify(locale) }
          });
        }
      }
    };
  }
};

export default rule;
