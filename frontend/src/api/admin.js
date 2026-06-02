// src/api/admin.js
import apiClient from "./client";

export async function submitReview(jobId, { reviewerId, approved, notes }) {
  const res = await apiClient.post(`/jobs/${jobId}/review`, {
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

export async function saveLineEdits(jobId, documentId, edits) {
  const res = await apiClient.patch(`/jobs/${jobId}/documents/${documentId}/lines`, {
    edits,
  });
  return res.data;
}

export async function saveDocumentHeader(jobId, documentId, fields) {
  const res = await apiClient.patch(`/jobs/${jobId}/documents/${documentId}`, fields);
  return res.data;
}

export async function rerunMatch(jobId) {
  const res = await apiClient.post(`/jobs/${jobId}/rematch`);
  return res.data;
}

/**
 * Returns the URL to embed the PDF in an iframe.
 *
 * Strategy: always use the same-origin API proxy endpoint.
 * The server streams the file from MinIO internally, so:
 *   - No CORS issues (same origin as the API)
 *   - No signed-URL expiry
 *   - Works identically in dev (Vite proxy) and prod (reverse proxy / Docker)
 *   - No hardcoded hostnames anywhere
 */
export async function getPdfViewUrl(jobId) {
  // Option A (preferred): skip the /pdf-url round-trip entirely — we already
  // know the URL pattern.  The axios baseURL is the API root, but the iframe
  // src must be an absolute URL, so we derive it from the current page origin.
  const apiBase = apiClient.defaults.baseURL || "/api/v1";

  // If baseURL is relative (e.g. "/api/v1") resolve against window.location
  let base = apiBase;
  try {
    // Will throw for relative URLs — that's expected
    new URL(apiBase);
  } catch {
    base = `${window.location.origin}${apiBase}`;
  }

  // Remove trailing slash before appending path
  return `${base.replace(/\/$/, "")}/jobs/${jobId}/pdf`;
}