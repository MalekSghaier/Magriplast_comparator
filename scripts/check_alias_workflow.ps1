param(
  [string]$ApiUrl = "http://127.0.0.1:8000/api/v1",
  [string]$JobId = "bf4b201b-0e62-45df-a2a9-cbae689d2b10",
  [string]$InternalRef = "P199450235",
  [switch]$RunDbCheck,
  [string]$Token
)

if (-not $Token) { $Token = $env:API_TOKEN }
if (-not $Token) {
  $Token = Read-Host -Prompt "API token (Bearer) - paste the token only"
}

if (-not $Token) {
  Write-Error "No API token provided. Set API_TOKEN env or pass -Token."
  exit 1
}

$hdr = @{ Authorization = "Bearer $Token" }

Write-Host "API: $ApiUrl  Job: $JobId  internalRef: $InternalRef"

function Fetch-Audit {
  Write-Host "Fetching audit..."
  try {
    $a = Invoke-RestMethod -Uri "$ApiUrl/jobs/$JobId/audit" -Headers $hdr -ErrorAction Stop
    $a | ConvertTo-Json -Depth 6
  } catch {
    Write-Error "Failed to fetch audit: $_"
  }
}

function Fetch-Job {
  Write-Host "Fetching job..."
  try {
    $j = Invoke-RestMethod -Uri "$ApiUrl/jobs/$JobId" -Headers $hdr -ErrorAction Stop
    return $j
  } catch {
    Write-Error "Failed to fetch job: $_"
    return $null
  }
}

function Print-LineStatus($line) {
  $obj = [ordered]@{
    ref_produit = $line.ref_produit
    ref_produit_facture = $line.ref_produit_facture
    ref_produit_bl = $line.ref_produit_bl
    reference_alias_applied = $line.reference_alias_applied
    reference_alias_id = $line.reference_alias_id
    reference_alias_external = $line.reference_alias_external
    reference_alias_internal = $line.reference_alias_internal
    verdict = $line.verdict
    match_layer = $line.match_layer
  }
  $obj | ConvertTo-Json -Depth 4
}

function Trigger-Rematch {
  Write-Host "Triggering rematch..."
  try {
    $r = Invoke-RestMethod -Method Post -Uri "$ApiUrl/jobs/$JobId/rematch" -Headers $hdr -ErrorAction Stop
    Write-Host "Rematch triggered: " (ConvertTo-Json $r -Depth 5)
  } catch {
    Write-Error "Rematch failed: $_"
  }
}

# --- run checks ---
Fetch-Audit

$job = Fetch-Job
if (-not $job) { Write-Error "Cannot proceed without job JSON (authentication?)."; exit 1 }

$lines = @()
if ($job.match_result -and $job.match_result.line_verdicts) {
  foreach ($l in $job.match_result.line_verdicts) {
    if ($l.ref_produit -eq $InternalRef) { $lines += $l }
  }
}

if ($lines.Count -eq 0) {
  Write-Host "No line found with ref_produit == $InternalRef in job.match_result.line_verdicts"
  Write-Host "Printing candidate lines containing the internal ref (fallback search)"
  foreach ($l in $job.match_result.line_verdicts) {
    if (($l.ref_produit -and $l.ref_produit -like "*$InternalRef*") -or ($l.ref_produit_facture -and $l.ref_produit_facture -like "*$InternalRef*")) {
      Print-LineStatus $l
    }
  }
  exit 0
}

Write-Host "Found $($lines.Count) matching BC lines. Status:"
foreach ($ln in $lines) { Print-LineStatus $ln }

$notApplied = $lines | Where-Object { -not $_.reference_alias_applied }
if ($notApplied.Count -eq 0) {
  Write-Host "All matching lines already have reference_alias_applied=true. UI should show 'Enregistré'."
} else {
  Write-Host "$($notApplied.Count) lines without alias applied. Will trigger rematch and re-check."
  Trigger-Rematch
  Start-Sleep -Seconds 2
  $job2 = Fetch-Job
  if ($job2 -ne $null) {
    $lines2 = @()
    foreach ($l in $job2.match_result.line_verdicts) { if ($l.ref_produit -eq $InternalRef) { $lines2 += $l } }
    Write-Host "After rematch - status:"
    foreach ($ln in $lines2) { Print-LineStatus $ln }
  }
}

if ($RunDbCheck) {
  Write-Host "Running DB alias check script (may fail if DB not reachable)..."
  $env:PYTHONPATH = 'server'
  try {
    python -u server/scripts/check_alias_row.py
  } catch {
    Write-Error "DB check script failed: $_"
  }
}

Write-Host "Done. If alias applied=true for the BC line, the frontend will show 'Enregistre' after refresh." 
