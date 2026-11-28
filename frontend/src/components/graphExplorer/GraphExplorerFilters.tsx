"use client";

// CHG-495 M23: left filter panel of the knowledge graph (node types, chunk content types, relations, depth).
// Zoom-based level of detail stays; the filters only narrow what is drawn.
import { useI18n } from "@/lib/i18nClient";
import { DropdownSelect } from "@/components/DropdownSelect";
import {
  type GraphExplorerContentType, type GraphExplorerEdge, type GraphExplorerNode, type GraphExplorerNodeKind, type GraphFilters, type GraphRelation,
  contentTypeLabelKeys, graphContentTypes, graphFiltersActive, graphKindTotalsKey, graphNodeKinds, graphRelations, GraphNodeIcon, nodeTypeKey, relationFilterLabelKeys
} from "./graphExplorerModel";

type GraphExplorerFiltersProps = {
  edges: GraphExplorerEdge[];
  filters: GraphFilters;
  id: string;
  nodes: GraphExplorerNode[];
  onChange: (filters: GraphFilters) => void;
  open: boolean;
  typeTotals?: Record<string, number>;
};

function toggled<T>(values: T[], value: T) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function GraphExplorerFilters({ edges, filters, id, nodes, onChange, open, typeTotals }: GraphExplorerFiltersProps) {
  const { format, t } = useI18n();
  const kindCounts = new Map<GraphExplorerNodeKind, number>();
  const contentCounts = new Map<GraphExplorerContentType, number>();
  for (const node of nodes) {
    kindCounts.set(node.kind, (kindCounts.get(node.kind) ?? 0) + 1);
    if (node.kind === "chunk") contentCounts.set(node.contentType ?? "text", (contentCounts.get(node.contentType ?? "text") ?? 0) + 1);
  }
  const relations = graphRelations.filter((relation) => edges.some((edge) => edge.relation === relation));
  const kinds = graphNodeKinds.filter((kind) => kindCounts.has(kind));
  const contentTypes = graphContentTypes.filter((type) => contentCounts.has(type));

  function countLabel(kind: GraphExplorerNodeKind) {
    const loaded = kindCounts.get(kind) ?? 0;
    const totalKey = graphKindTotalsKey[kind];
    const total = totalKey ? typeTotals?.[totalKey] : undefined;
    return typeof total === "number" && total > loaded ? format("graphFilterLoadedOfTotal", { loaded, total }) : String(loaded);
  }

  return (
    <aside aria-label={t("graphFiltersTitle")} className={`graph-explorer-filters${open ? " is-open" : ""}`} id={id}>
      <div className="graph-explorer-filters-head">
        <strong>{t("graphFiltersTitle")}</strong>
        <button className="text-link" disabled={!graphFiltersActive(filters)} onClick={() => onChange({ depth: "all", hiddenContentTypes: [], hiddenKinds: [], hiddenRelations: [] })} type="button">{t("graphFiltersShowAll")}</button>
      </div>
      {kinds.length ? (
        <fieldset>
          <legend>{t("graphFilterNodeTypes")}</legend>
          {kinds.map((kind) => (
            <label className="graph-filter-option" key={kind}>
              <input checked={!filters.hiddenKinds.includes(kind)} onChange={() => onChange({ ...filters, hiddenKinds: toggled(filters.hiddenKinds, kind) })} type="checkbox" />
              <span aria-hidden="true" className={`graph-filter-swatch swatch-${kind}`}><GraphNodeIcon kind={kind} /></span>
              <span className="graph-filter-label">{t(nodeTypeKey(kind))}</span>
              <span className="graph-filter-count">{countLabel(kind)}</span>
            </label>
          ))}
          {contentTypes.length ? (
            <div aria-label={t("graphExplorerContentType")} className="graph-filter-subgroup" role="group">
              {contentTypes.map((type) => (
                <label className="graph-filter-option" key={type}>
                  <input checked={!filters.hiddenContentTypes.includes(type)} disabled={filters.hiddenKinds.includes("chunk")} onChange={() => onChange({ ...filters, hiddenContentTypes: toggled(filters.hiddenContentTypes, type) })} type="checkbox" />
                  <span aria-hidden="true" className="graph-filter-content-icon"><GraphNodeIcon contentType={type} kind="chunk" /></span>
                  <span className="graph-filter-label">{t(contentTypeLabelKeys[type])}</span>
                  <span className="graph-filter-count">{contentCounts.get(type) ?? 0}</span>
                </label>
              ))}
            </div>
          ) : null}
        </fieldset>
      ) : null}
      {relations.length ? (
        <fieldset>
          <legend>{t("graphFilterRelations")}</legend>
          {relations.map((relation: GraphRelation) => (
            <label className="graph-filter-option" key={relation}>
              <input checked={!filters.hiddenRelations.includes(relation)} onChange={() => onChange({ ...filters, hiddenRelations: toggled(filters.hiddenRelations, relation) })} type="checkbox" />
              <span aria-hidden="true" className={`graph-filter-line line-${relation}`} />
              <span className="graph-filter-label">{t(relationFilterLabelKeys[relation])}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      <label className="graph-filter-depth">
        <span>{t("graphFilterDepth")}</span>
        <DropdownSelect onChange={(event) => onChange({ ...filters, depth: event.target.value === "all" ? "all" : Number(event.target.value) === 1 ? 1 : 2 })} value={String(filters.depth)}>
          <option value="all">{t("graphFilterDepthAll")}</option>
          <option value="1">{t("graphFilterDepthOne")}</option>
          <option value="2">{t("graphFilterDepthTwo")}</option>
        </DropdownSelect>
        <small>{t("graphFilterDepthHelp")}</small>
      </label>
    </aside>
  );
}
