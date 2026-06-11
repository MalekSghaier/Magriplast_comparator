import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadDocument } from "../api/jobs";
import UploadZone from "../components/upload/UploadZone";
import UploadProgress from "../components/upload/UploadProgress";
import PageWrapper from "../components/layout/PageWrapper";
import Alert from "../components/ui/Alert";
import {
  ArrowRight,
  Info,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  Upload,
} from "lucide-react";

export default function UploadPage() {
  const navigate = useNavigate();
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState(null); // null | 'uploading' | 'success' | 'error'
  const [uploadError, setUploadError] = useState(null);

  const handleFileSelected = (file) => {
    setSelectedFile(file);
    setUploadStatus(null);
    setUploadError(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setUploadStatus("uploading");
    setUploadError(null);

    try {
      const result = await uploadDocument(selectedFile);
      setUploadStatus("success");
      setTimeout(() => navigate(`/jobs/${result.job_id}`), 500);
    } catch (err) {
      setUploadStatus("error");
      setUploadError(err.message);
    }
  };

  const isUploading = uploadStatus === "uploading";
  const isSuccess = uploadStatus === "success";
  const isError = uploadStatus === "error";
  const isIdle = uploadStatus === null;

  return (
    <PageWrapper
      title="Glissez votre fichier"
      subtitle="Déposez votre PDF ici — Bon de Commande, Bon de Livraison ou Facture"
    >
      <div className="max-w-2xl mx-auto">

        {/* ── Info banner ── */}
        <div
          className="rounded-xl mb-6 px-5 py-4 flex items-start gap-3"
          style={{ background: "#eff6ff", border: "1px solid #bfdbfe" }}
        >
          <div
            className="flex-shrink-0 flex items-center justify-center rounded-lg mt-0.5"
            style={{ width: 28, height: 28, background: "#dbeafe" }}
          >
            <Info size={13} color="#2563eb" strokeWidth={2.5} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-blue-900 leading-tight">
              Formats acceptés
            </p>
            <p className="text-xs text-blue-600 mt-1 leading-relaxed">
              Un seul PDF suffit — le système identifie et classe automatiquement vos Bons de Commande, Bons de Livraison et Factures

            </p>
          </div>
        </div>

        {/* ── Main upload card ── */}
        <div
          className="bg-white rounded-2xl overflow-hidden"
          style={{
            border: "1px solid #e5e7eb",
            boxShadow:
              "0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.04)",
          }}
        >
          {/* Card header */}
          <div
            className="px-7 py-5 border-b border-gray-100 flex items-center gap-3"
            style={{ background: "#fafafa" }}
          >
            <div
              className="flex-shrink-0 flex items-center justify-center rounded-xl"
              style={{
                width: 38,
                height: 38,
                background: "#fff",
                border: "1px solid #e5e7eb",
              }}
            >
              <Upload size={16} className="text-gray-400" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-0.5">
                Etape 1 sur 2
              </p>
              <p className="text-sm font-semibold text-gray-800">
                Sélectionnez votre document
              </p>
            </div>
          </div>

          {/* Drop zone */}
          <div className="px-7 py-6">
            <UploadZone
              onFileSelected={handleFileSelected}
              disabled={isUploading || isSuccess}
            />
          </div>

          {/* ── File preview panel ── */}
          {selectedFile && (
            <div className="px-7 pb-7">
              <div
                className="rounded-xl overflow-hidden"
                style={{ border: "1px solid #e5e7eb" }}
              >
                {/* File identity row */}
                <div className="px-5 py-4 flex items-center gap-4">
                  {/* PDF icon tile */}
                  <div
                    className="flex-shrink-0 flex items-center justify-center rounded-xl"
                    style={{
                      width: 46,
                      height: 46,
                      background: isError
                        ? "#fef2f2"
                        : isSuccess
                        ? "#f0fdf9"
                        : "#eff6ff",
                      border: `1px solid ${
                        isError
                          ? "#fecaca"
                          : isSuccess
                          ? "#d1fae5"
                          : "#bfdbfe"
                      }`,
                    }}
                  >
                    <FileText
                      size={20}
                      color={
                        isError
                          ? "#ef4444"
                          : isSuccess
                          ? "#10b981"
                          : "#3b82f6"
                      }
                      strokeWidth={1.8}
                    />
                  </div>

                  {/* File name + size */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-900 truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {formatFileSize(selectedFile.size)}
                      <span className="mx-1.5 text-gray-200">·</span>
                      PDF document
                    </p>
                  </div>

                  {/* State badge */}
                  <div className="flex-shrink-0">
                    <StatusChip status={uploadStatus} />
                  </div>
                </div>

                {/* Upload progress component */}
                <div
                  className="border-t"
                  style={{ borderColor: "#f3f4f6" }}
                >
                  <UploadProgress
                    file={selectedFile}
                    status={uploadStatus}
                    error={uploadError}
                  />
                </div>

                {/* Progress bar track — shown during upload */}
                {isUploading && (
                  <div className="px-5 pb-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-gray-400">
                        Téléchargement
                      </span>
                      <span className="text-xs font-semibold text-blue-600">
                        En cours…
                      </span>
                    </div>
                    <div
                      className="w-full rounded-full overflow-hidden"
                      style={{ height: 5, background: "#e0e7ff" }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: "65%",
                          background:
                            "linear-gradient(90deg, #3b82f6, #6366f1)",
                          borderRadius: 9999,
                          animation:
                            "shimmer 2s ease-in-out infinite alternate",
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Success bar — full green */}
                {isSuccess && (
                  <div className="px-5 pb-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-gray-400">
                        Téléchargement terminé
                      </span>
                      <span className="text-xs font-semibold text-emerald-600">
                        100%
                      </span>
                    </div>
                    <div
                      className="w-full rounded-full overflow-hidden"
                      style={{ height: 5, background: "#a7f3d0" }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: "100%",
                          background: "#10b981",
                          borderRadius: 9999,
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Upload button ── */}
          {selectedFile && !isSuccess && (
            <div
              className="px-7 pb-7"
              style={{ marginTop: selectedFile ? 0 : undefined }}
            >
              <UploadButton
                status={uploadStatus}
                onClick={handleUpload}
              />
            </div>
          )}

          {/* ── Success redirect notice ── */}
          {isSuccess && (
            <div className="px-7 pb-6">
              <div
                className="flex items-center gap-2.5 rounded-xl px-5 py-3.5"
                style={{ background: "#f0fdf9", border: "1px solid #d1fae5" }}
              >
                <Loader2
                  size={15}
                  color="#059669"
                  strokeWidth={2.5}
                  className="animate-spin flex-shrink-0"
                />
                <p className="text-sm font-semibold text-emerald-700">
                  Téléchargement réussi — redirection vers le traitement…
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ── Error alert (outside card) ── */}
        {uploadError && (
          <div
            className="mt-4 rounded-xl px-5 py-4 flex items-start gap-3"
            style={{ background: "#fef2f2", border: "1px solid #fecaca" }}
          >
            <AlertCircle
              size={16}
              color="#ef4444"
              strokeWidth={2}
              className="flex-shrink-0 mt-0.5"
            />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-red-800">
                Téléchargement échoué
              </p>
              <p className="text-xs text-red-500 mt-0.5 leading-relaxed">
                {uploadError}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Shimmer keyframes */}
      <style>{`
        @keyframes shimmer {
          from { width: 35%; }
          to   { width: 80%; }
        }
      `}</style>
    </PageWrapper>
  );
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function StatusChip({ status }) {
  if (!status) {
    return (
      <span
        className="text-[11px] font-semibold px-2.5 py-1 rounded-full"
        style={{ background: "#f3f4f6", color: "#9ca3af" }}
      >
        Ready
      </span>
    );
  }
  if (status === "uploading") {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full"
        style={{ background: "#dbeafe", color: "#1d4ed8" }}
      >
        <Loader2 size={10} className="animate-spin" strokeWidth={2.5} />
        Téléchargement
      </span>
    );
  }
  if (status === "success") {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full"
        style={{ background: "#d1fae5", color: "#065f46" }}
      >
        <CheckCircle2 size={10} strokeWidth={2.5} />
        Terminé
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full"
        style={{ background: "#fee2e2", color: "#991b1b" }}
      >
        <X size={10} strokeWidth={2.5} />
        Échoué
      </span>
    );
  }
  return null;
}
function UploadButton({ status, onClick }) {
  const isUploading = status === "uploading";

  return (
    <button
      onClick={onClick}
      disabled={isUploading}
      className="w-full flex items-center justify-center gap-2.5 font-semibold text-sm rounded-xl transition-all duration-200"
      style={{
        paddingTop: 14,
        paddingBottom: 14,
        background: isUploading
          ? "linear-gradient(90deg, #93c5fd, #a5b4fc)"
          : "linear-gradient(90deg, #2563eb, #4f46e5)",
        color: "#fff",
        border: "none",
        cursor: isUploading ? "not-allowed" : "pointer",
        boxShadow: isUploading
          ? "none"
          : "0 1px 2px rgba(37,99,235,0.2), 0 4px 12px rgba(37,99,235,0.25)",
        letterSpacing: "0.01em",
      }}
    >
      {isUploading ? (
        <>
          <Loader2 size={16} strokeWidth={2.5} className="animate-spin" />
          Téléchargement…
        </>
      ) : (
        <>
           Lancer l'analyse
          <ArrowRight size={16} strokeWidth={2.5} />
        </>
      )}
    </button>
  );
}