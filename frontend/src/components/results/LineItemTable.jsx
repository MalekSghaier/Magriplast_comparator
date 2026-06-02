import { useState } from "react";
import LineVerdictBadge from "./LineVerdictBadge";
import ConfidenceIndicator from "./ConfidenceIndicator";
import { LINE_VERDICT_STYLES } from "../../utils/verdictColors";
import { formatQty, formatCurrency } from "../../utils/formatters";
import { formatMismatchField } from "../../utils/mismatchFields";
import clsx from "clsx";
import { ChevronDown, ChevronUp, ShoppingCart, FileText } from "lucide-react";

// ── helpers ────────────────────────────────────────────────────────────────

function cellHighlight(field, mismatches = []) {
  return mismatches.includes(field) ? "bg-red-100 font-bold text-red-800" : "";
}

/** True when the line comes from FAC/BL only (no BC counterpart). */
function isExtraLine(line) {
  return line.verdict === "EXTRA";
}

/** True when the line comes from BC only (no FAC/BL counterpart). */
function isMissingLine(line) {
  return line.verdict === "MISSING";
}

// ── sub-components ─────────────────────────────────────────────────────────

/**
 * Shared empty-row placeholder shown when a document side has no data
 * for a given line (MISSING in FAC/BL, EXTRA in BC).
 */
function EmptyCell({ colSpan }) {
  return (
    <td colSpan={colSpan} className="px-4 py-3 text-center text-gray-300 italic text-xs select-none">
      —
    </td>
  );
}

// ── main component ─────────────────────────────────────────────────────────

export default function LineItemTable({ lineVerdicts }) {
  const [expandedRows, setExpandedRows] = useState(new Set());

  if (!lineVerdicts || lineVerdicts.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400 text-sm">
        Aucune ligne à afficher
      </div>
    );
  }

  const toggleRow = (idx) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  return (
    <div className="space-y-6">

      {/* ══════════════════════════════════════════════════════════════════
          TABLE 1 — BON DE COMMANDE
      ══════════════════════════════════════════════════════════════════ */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <ShoppingCart size={15} className="text-blue-600" />
          <h3 className="text-sm font-semibold text-blue-700 uppercase tracking-wide">
            Bon de Commande
          </h3>
        </div>

        <div className="overflow-x-auto rounded-lg border border-blue-200">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-blue-50 text-blue-700 text-xs uppercase tracking-wide">
                <th className="text-left px-4 py-3 font-semibold">
                  Réf / Désignation
                </th>
                <th className="text-right px-3 py-3 font-semibold border-l border-blue-100">
                  Qté
                </th>
                <th className="text-right px-3 py-3 font-semibold border-l border-blue-100">
                  Prix UN
                </th>
              </tr>
            </thead>
            <tbody>
              {lineVerdicts.map((line, idx) => {
                const style =
                  LINE_VERDICT_STYLES[line.verdict] ||
                  LINE_VERDICT_STYLES.PARTIAL_DATA;
                const extra = isExtraLine(line);

                return (
                  <tr
                    key={idx}
                    className={clsx(
                      "border-t border-gray-100 transition-colors",
                      extra ? "bg-gray-50" : style.bg
                    )}
                  >
                    {extra ? (
                      <EmptyCell colSpan={3} />
                    ) : (
                      <>
                        {/* Réf + désignation */}
                        <td className="px-4 py-3">
                          <p className="font-mono font-semibold text-gray-900 text-xs">
                            {line.ref_produit || "—"}
                          </p>
                          {line.designation && (
                            <p
                              className="text-gray-500 text-xs truncate max-w-[220px]"
                              title={line.designation}
                            >
                              {line.designation}
                            </p>
                          )}
                          {line.confidence < 0.7 && (
                            <ConfidenceIndicator value={line.confidence} />
                          )}
                        </td>

                        {/* Qté BC */}
                        <td className="text-right px-3 py-3 border-l border-blue-100 tabular-nums">
                          {formatQty(line.qty_bc)}
                        </td>

                        {/* Prix BC */}
                        <td
                          className={clsx(
                            "text-right px-3 py-3 border-l border-blue-100 tabular-nums",
                            cellHighlight("prix_unitaire", line.mismatch_fields)
                          )}
                        >
                          {formatCurrency(line.prix_bc, "")}
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════
          TABLE 2 — COMPARAISON FAC/BL vs BC (verdicts, écarts, TVA)
          This table shows matched/compared data — NOT raw invoice lines.
          Raw invoice lines are displayed separately in InvoiceLinesTable.
      ══════════════════════════════════════════════════════════════════ */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <FileText size={15} className="text-violet-600" />
          <h3 className="text-sm font-semibold text-violet-700 uppercase tracking-wide">
            Comparaison FAC / BL vs BC
          </h3>
        </div>

        <div className="overflow-x-auto rounded-lg border border-violet-200">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-violet-50 text-xs uppercase tracking-wide">
                <th className="text-left px-4 py-3 font-semibold text-violet-700">
                  Réf / Désignation
                </th>
                <th className="text-right px-3 py-3 font-semibold text-teal-600 border-l border-violet-100">
                  BL Qté
                </th>
                <th className="text-right px-3 py-3 font-semibold text-violet-600 border-l border-violet-100">
                  FAC Qté
                </th>
                <th className="text-right px-3 py-3 font-semibold text-violet-600">
                  Prix UN
                </th>
                <th className="text-right px-3 py-3 font-semibold text-violet-600">
                  TVA%
                </th>
                <th className="text-center px-4 py-3 font-semibold text-gray-600 border-l border-violet-100">
                  Verdict
                </th>
                {/* expand toggle column */}
                <th className="px-3 py-3" />
              </tr>
            </thead>
            <tbody>
              {lineVerdicts.map((line, idx) => {
                const style =
                  LINE_VERDICT_STYLES[line.verdict] ||
                  LINE_VERDICT_STYLES.PARTIAL_DATA;
                const isExpanded = expandedRows.has(idx);
                const hasMismatches = line.mismatch_fields?.length > 0;
                const missing = isMissingLine(line);

                return (
                  <>
                    <tr
                      key={idx}
                      className={clsx(
                        "border-t border-gray-100 transition-colors",
                        style.bg,
                        hasMismatches && "cursor-pointer hover:brightness-95"
                      )}
                      onClick={() => hasMismatches && toggleRow(idx)}
                    >
                      {/* Réf + désignation (empty for MISSING lines).
                          Always show the FACTURE/BL side reference here,
                          never the BC reference — use ref_produit_facture or
                          ref_produit_bl when available, otherwise show "—".
                          Falling back to ref_produit (BC ref) would make this
                          table look identical to the BC table above (table-reuse
                          display bug). */}
                      {missing ? (
                        <td className="px-4 py-3 text-gray-300 italic text-xs select-none">
                          —
                        </td>
                      ) : (
                        <td className="px-4 py-3">
                          <p className="font-mono font-semibold text-gray-900 text-xs">
                            {line.ref_produit_facture || line.ref_produit_bl || "—"}
                          </p>
                          {line.designation && (
                            <p
                              className="text-gray-500 text-xs truncate max-w-[220px]"
                              title={line.designation}
                            >
                              {line.designation}
                            </p>
                          )}
                        </td>
                      )}

                      {/* BL Qté */}
                      <td
                        className={clsx(
                          "text-right px-3 py-3 border-l border-violet-100 tabular-nums",
                          cellHighlight("qty_bc_vs_bl", line.mismatch_fields)
                        )}
                      >
                        {formatQty(line.qty_bl)}
                      </td>

                      {/* FAC Qté */}
                      <td
                        className={clsx(
                          "text-right px-3 py-3 border-l border-violet-100 tabular-nums",
                          cellHighlight("qty_bc_vs_facture", line.mismatch_fields)
                        )}
                      >
                        {formatQty(line.qty_facture)}
                      </td>

                      {/* FAC Prix UN */}
                      <td
                        className={clsx(
                          "text-right px-3 py-3 tabular-nums",
                          cellHighlight("prix_unitaire", line.mismatch_fields)
                        )}
                      >
                        {formatCurrency(line.prix_facture, "")}
                      </td>

                      {/* TVA% */}
                      <td
                        className={clsx(
                          "text-right px-3 py-3 tabular-nums",
                          cellHighlight("tva_rate", line.mismatch_fields)
                        )}
                      >
                        {line.tva_facture != null ? `${line.tva_facture}%` : "—"}
                      </td>

                      {/* Verdict */}
                      <td className="text-center px-4 py-3 border-l border-violet-100">
                        <LineVerdictBadge verdict={line.verdict} />
                      </td>

                      {/* Expand toggle */}
                      <td className="px-3 py-3 text-gray-400">
                        {hasMismatches &&
                          (isExpanded ? (
                            <ChevronUp size={14} />
                          ) : (
                            <ChevronDown size={14} />
                          ))}
                      </td>
                    </tr>

                    {/* Expanded mismatch detail row */}
                    {isExpanded && hasMismatches && (
                      <tr
                        key={`${idx}-detail`}
                        className="bg-red-50 border-t border-red-100"
                      >
                        <td colSpan={7} className="px-6 py-3">
                          <p className="text-xs font-semibold text-red-700 mb-1">
                            Champs en écart :
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {line.mismatch_fields.map((f) => (
                              <span
                                key={f}
                                className="bg-red-100 text-red-800 text-xs px-2 py-0.5 rounded font-mono"
                              >
                                {formatMismatchField(f)}
                              </span>
                            ))}
                          </div>
                          {line.notes && (
                            <p className="text-xs text-red-600 mt-1">
                              {line.notes}
                            </p>
                          )}
                          {line.match_layer > 0 && (
                            <p className="text-xs text-gray-400 mt-1">
                              Couche de correspondance : {line.match_layer}
                              {line.match_layer === 5 ? " (LLM)" : ""}
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
