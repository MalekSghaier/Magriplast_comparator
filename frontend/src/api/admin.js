// src/api/admin.js
import apiClient from "./client";

export async function submitReview(jobId, { reviewerId, approved, notes }) {
  const res = await apiClient.patch(`/jobs/${jobId}/review`, {
    reviewer_id: reviewerId,
    approved,
    notes,
  });
  return res.data;
}

export async function approveReferenceAlias(jobId, { reviewerId, externalRef, internalRef, supplierName, notes }) {
  const res = await apiClient.post(`/jobs/${jobId}/reference-aliases`, {
    reviewer_id: reviewerId,
    external_ref: externalRef,
    internal_ref: internalRef,
    supplier_name: supplierName,
    notes,
  });
  return res.data;
}

/**
 * Save human corrections to a document's extracted line items.
 * edits: [{ line_id, ref_produit, designation, qty, prix_unitaire, tva_rate }]
 */
export async function saveLineEdits(jobId, documentId, edits) {
  const res = await apiClient.patch(`/jobs/${jobId}/documents/${documentId}/lines`, {
    edits,
  });
  return res.data;
}

/**
 * Save human corrections to a document's header fields.
 * fields: { ref_document, document_date, supplier_name, total_ht, total_ttc }
 */
export async function saveDocumentHeader(jobId, documentId, fields) {
  const res = await apiClient.patch(`/jobs/${jobId}/documents/${documentId}`, fields);
  return res.data;
}

/**
 * Trigger re-matching after human corrections have been saved.
 * Returns the new match_result.
 */
export async function rerunMatch(jobId) {
  const res = await apiClient.post(`/jobs/${jobId}/rematch`);
  return res.data;
}

/**
 * Returns a signed / proxied URL to view the original PDF inline.
 */
export async function getPdfViewUrl(jobId) {
  const res = await apiClient.get(`/jobs/${jobId}/pdf-url`);
  return res.data.url;
}
