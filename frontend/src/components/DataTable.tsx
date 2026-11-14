import type { Key, ReactNode } from "react";

/** One column of a {@link DataTable} (OPT424-032, D424-19). */
export type DataTableColumn<T> = {
  key: string;
  /** Visible header text; omit for an action column and give `headerLabel` instead. */
  header?: ReactNode;
  /** Accessible name for a header without visible text. */
  headerLabel?: string;
  /** Class applied to both the header cell and every body cell of this column. */
  className?: string;
  /** Render the body cell as `th scope="row"` (the row's identifying value). */
  rowHeader?: boolean;
  cell: (row: T, index: number) => ReactNode;
};

type DataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => Key;
  rowClassName?: (row: T) => string | undefined;
  onRowClick?: (row: T) => void;
  /** Extra class on the scrolling wrapper, e.g. a page-specific width rule. */
  wrapClassName?: string;
  /** Content kept inside the wrapper after the table. */
  children?: ReactNode;
};

/**
 * Shared operational data table: renders the existing
 * `system-table-wrap` + `system-table` markup, so pages keep their look while
 * the header/body structure is defined once. Empty, loading and paging states
 * stay with the page that owns the data.
 */
export function DataTable<T>({ columns, rows, rowKey, rowClassName, onRowClick, wrapClassName, children }: DataTableProps<T>) {
  return <div className={wrapClassName ? `system-table-wrap ${wrapClassName}` : "system-table-wrap"}>
    <table className="system-table">
      <thead><tr>{columns.map((column) => <th aria-label={column.headerLabel} className={column.className} key={column.key}>{column.header}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr className={rowClassName?.(row) || undefined} key={rowKey(row, index)} onClick={onRowClick ? () => onRowClick(row) : undefined}>
        {columns.map((column) => column.rowHeader
          ? <th className={column.className} key={column.key} scope="row">{column.cell(row, index)}</th>
          : <td className={column.className} key={column.key}>{column.cell(row, index)}</td>)}
      </tr>)}</tbody>
    </table>
    {children}
  </div>;
}
