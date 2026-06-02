import { FileText } from "lucide-react";
import { formatQty, formatCurrency } from "../../utils/formatters";
import ConfidenceIndicator from "./ConfidenceIndicator";

/**
 * Pure invoice-lines display — no comparison columns, no verdicts.
 * Accepts raw line items from the FACTURE document (results.documents).
 * Props:
 *   lines: Array<{ ref_produit, designation, qty, prix_unitaire, extraction_confidence }>
 */
export default function InvoiceLinesTable({ lines }) {
  // Keep only lines that have at least a reference or a designation.
  // This guards against comparison-only objects leaking in.
  const invoiceLines = (lines || []).filter(
    (l) =>
      (l.ref_produit || l.designation) &&
      l.verdict === undefined &&
      l.matchStatus === undefined &&
      l.poQuantity === undefined &&
      l.isMissingFromInvoice === undefined
  );

  if (invoiceLines.length === 0) {
    return (
      <div className="rounded-lg border border-violet-200 py-8 text-center text-sm text-gray-400 italic">
        Aucune ligne facture extraite
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <FileText size={15} className="text-violet-600" />
        <h3 className="text-sm font-semibold text-violet-700 uppercase tracking-wide">
          Facture
        </h3>
      </div>

      <div className="overflow-x-auto rounded-lg border border-violet-200">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-violet-50 text-violet-700 text-xs uppercase tracking-wide">
              <th className="text-left px-4 py-3 font-semibold">
                Réf / Désignation
              </th>
              <th className="text-right px-3 py-3 font-semibold border-l border-violet-100">
                Qté
              </th>
              <th className="text-right px-3 py-3 font-semibold border-l border-violet-100">
                Prix unitaire
              </th>
            </tr>
          </thead>
          <tbody>
            {invoiceLines.map((line, idx) => (
              <tr
                key={idx}
                className="border-t border-gray-100 hover:bg-violet-50/30 transition-colors"
              >
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
                  {line.extraction_confidence != null &&
                    line.extraction_confidence < 0.7 && (
                      <ConfidenceIndicator value={line.extraction_confidence} />
                    )}
                </td>

                {/* Qté */}
                <td className="text-right px-3 py-3 border-l border-violet-100 tabular-nums">
                  {formatQty(line.qty)}
                </td>

                {/* Prix unitaire */}
                <td className="text-right px-3 py-3 border-l border-violet-100 tabular-nums">
                  {formatCurrency(line.prix_unitaire, "")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
