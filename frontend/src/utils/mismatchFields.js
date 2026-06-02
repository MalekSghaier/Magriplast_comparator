export const MISMATCH_FIELD_LABELS = {
  qty_bc_vs_facture: "Quantite BC vs facture",
  qty_bc_vs_bl: "Quantite BC vs BL",
  prix_unitaire: "Prix unitaire",
  tva_rate: "TVA",
  ref_produit: "Reference produit",
};

export function formatMismatchField(field) {
  return MISMATCH_FIELD_LABELS[field] ?? field;
}
