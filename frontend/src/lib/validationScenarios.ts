// CHG-436 MTVAL436-001/002/007/010: multi-turn scenarios in CSV validation (shared by both chat test pages).

export type ScenarioFields = { conversation_key?: string | null; turn?: number | null; selected_document_ids?: string[] | null };
type Formatter = (key: "validationScenarioPairRequired" | "validationScenarioTurnInvalid" | "validationScenarioDuplicateTurn" | "validationScenarioTurnsNotConsecutive" | "validationScenarioTooManyTurns" | "validationScenarioScopeDiffers", values: Record<string, string | number>) => string;

export const SCENARIO_MAX_TURNS = 20;
export const SCENARIO_COLUMNS = ["conversation_key", "turn"] as const;

/** Read conversation_key and turn from one CSV data row; `rowNumber` is the 1-based data row. */
export function scenarioFields(headers: string[], row: string[], rowNumber: number, format: Formatter): Pick<ScenarioFields, "conversation_key" | "turn"> {
  const keyIndex = headers.indexOf("conversation_key");
  const turnIndex = headers.indexOf("turn");
  const key = keyIndex >= 0 ? (row[keyIndex] ?? "").trim() : "";
  const turnText = turnIndex >= 0 ? (row[turnIndex] ?? "").trim() : "";
  if (!key && !turnText) return {};
  if (!key || !turnText) throw new Error(format("validationScenarioPairRequired", { rows: rowNumber }));
  const turn = Number(turnText);
  if (!Number.isInteger(turn) || turn < 1) throw new Error(format("validationScenarioTurnInvalid", { rows: rowNumber, key }));
  if (key.length > 100) throw new Error(format("validationScenarioPairRequired", { rows: rowNumber }));
  return { conversation_key: key, turn };
}

/** Same rules as the backend: turns 1..n without gaps or duplicates, at most 20, one document scope. */
export function checkScenarios(questions: ScenarioFields[], format: Formatter, rowNumbers?: number[], maxTurns = SCENARIO_MAX_TURNS) {
  const groups = new Map<string, { row: number; question: ScenarioFields }[]>();
  questions.forEach((question, index) => {
    if (!question.conversation_key) return;
    groups.set(question.conversation_key, [...(groups.get(question.conversation_key) ?? []), { row: rowNumbers?.[index] ?? index + 1, question }]);
  });
  for (const [key, members] of groups) {
    const rows = members.map((member) => member.row).join(", ");
    const turns = members.map((member) => member.question.turn ?? 0);
    if (new Set(turns).size !== turns.length) throw new Error(format("validationScenarioDuplicateTurn", { key, rows }));
    if ([...turns].sort((a, b) => a - b).some((turn, index) => turn !== index + 1)) throw new Error(format("validationScenarioTurnsNotConsecutive", { key, rows }));
    if (members.length > maxTurns) throw new Error(format("validationScenarioTooManyTurns", { key, rows, max: maxTurns }));
    const scopes = new Set(members.map((member) => [...(member.question.selected_document_ids ?? [])].sort().join(";")));
    if (scopes.size > 1) throw new Error(format("validationScenarioScopeDiffers", { key, rows }));
  }
}

/** Upload preview: how many single questions and how many scenarios (with their turn counts). */
export function scenarioPreview(questions: ScenarioFields[]) {
  const scenarios = new Map<string, number>();
  let singles = 0;
  for (const question of questions) {
    if (question.conversation_key) scenarios.set(question.conversation_key, (scenarios.get(question.conversation_key) ?? 0) + 1);
    else singles += 1;
  }
  return { singles, scenarios: [...scenarios.entries()].map(([key, turns]) => ({ key, turns })) };
}
