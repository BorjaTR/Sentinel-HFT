"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  ShieldCheck,
  AlertTriangle,
  Upload,
  Binary,
  CheckCircle2,
  XCircle,
  FileDigit,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { tamperDemo, verifyAudit } from "@/lib/sentinel-api";
import type { TamperDemoResult, VerificationResult } from "@/lib/sentinel-types";

export default function AuditVerifierPage() {
  const [file, setFile] = useState<File | null>(null);
  const [verification, setVerification] = useState<VerificationResult | null>(null);
  const [tamper, setTamper] = useState<TamperDemoResult | null>(null);
  const [recordIndex, setRecordIndex] = useState<number>(32);
  const [byteOffset, setByteOffset] = useState<number>(80);
  const [verifying, setVerifying] = useState(false);
  const [tampering, setTampering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback((accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setVerification(null);
    setTamper(null);
    setError(null);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    maxFiles: 1,
    multiple: false,
  });

  async function doVerify() {
    if (!file) return;
    setVerifying(true);
    setError(null);
    setVerification(null);
    try {
      const res = await verifyAudit(file);
      setVerification(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setVerifying(false);
    }
  }

  async function doTamper() {
    if (!file) return;
    setTampering(true);
    setError(null);
    setTamper(null);
    try {
      const res = await tamperDemo(file, recordIndex, byteOffset);
      setTamper(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setTampering(false);
    }
  }

  return (
    <div className="max-w-6xl">
      <header className="mb-6">
        <div className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          tool · audit
        </div>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-[#e4edf5]">
          <ShieldCheck className="h-6 w-6 text-emerald-400" />
          Audit-chain verifier
        </h1>
        <p className="mt-2 max-w-3xl text-xs text-[#9ab3c8]">
          Upload any <span className="font-mono text-[#e4edf5]">.aud</span> file
          produced by a Sentinel drill. The host verifier walks the
          BLAKE2b-chained record sequence and reports head-hash, break points,
          and exact seq_no of the first tamper — the ground truth the
          RTL’s <span className="font-mono">risk_audit_log</span> is required to match.
        </p>
      </header>

      {/* Drop zone */}
      <Card className="mb-4 border-[#1a232e] bg-[#0f151d]">
        <CardContent className="p-0">
          <div
            {...getRootProps({
              className: `flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-10 transition ${
                isDragActive
                  ? "border-emerald-500/60 bg-emerald-500/5"
                  : "border-[#1f2a38] hover:border-[#2a3a4c] hover:bg-[#131c27]"
              }`,
            })}
          >
            <input {...getInputProps()} />
            <Upload className="h-6 w-6 text-[#4d617a]" />
            <div className="text-sm text-[#d5e0ea]">
              {isDragActive
                ? "drop to stage…"
                : "drop a .aud file here, or click to select"}
            </div>
            {file && (
              <div className="mt-1 font-mono text-[10px] text-[#9ab3c8]">
                {file.name} · {file.size.toLocaleString()} bytes
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 p-3 font-mono text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Action row */}
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              <FileDigit className="h-3.5 w-3.5 text-emerald-400" />
              Step 1 · walk the chain
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-xs text-[#9ab3c8]">
              Runs the canonical host verifier. Every record: seq_no linkage,
              prev_hash match, BLAKE2b-80 hash equal. Produces head-hash and a
              sorted list of breaks (empty on a clean chain).
            </p>
            <Button
              onClick={doVerify}
              disabled={!file || verifying}
              size="sm"
              className="bg-emerald-500 font-mono text-xs text-[#0a0e14] hover:bg-emerald-400 disabled:opacity-40"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              {verifying ? "walking…" : "verify chain"}
            </Button>
          </CardContent>
        </Card>

        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
              Step 2 · forge a byte
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-xs text-[#9ab3c8]">
              Copies your file, XORs a single byte at{" "}
              <span className="font-mono text-[#e4edf5]">
                record[{recordIndex}] + offset {byteOffset}
              </span>
              , re-walks both copies, and shows the first divergence. Default
              offset 80 lands inside <span className="font-mono">prev_hash_lo</span>.
            </p>
            <div className="mb-3 grid grid-cols-2 gap-3">
              <div>
                <Label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                  record index
                </Label>
                <Input
                  type="number"
                  min={0}
                  value={recordIndex}
                  onChange={(e) => setRecordIndex(Math.max(0, Number(e.target.value) || 0))}
                  className="border-[#1f2a38] bg-[#0a0e14] font-mono text-xs text-[#e4edf5]"
                  disabled={tampering}
                />
              </div>
              <div>
                <Label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                  byte offset (0-95)
                </Label>
                <Input
                  type="number"
                  min={0}
                  max={95}
                  value={byteOffset}
                  onChange={(e) =>
                    setByteOffset(Math.max(0, Math.min(95, Number(e.target.value) || 0)))
                  }
                  className="border-[#1f2a38] bg-[#0a0e14] font-mono text-xs text-[#e4edf5]"
                  disabled={tampering}
                />
              </div>
            </div>
            <Button
              onClick={doTamper}
              disabled={!file || tampering}
              size="sm"
              variant="outline"
              className="border-amber-500/40 bg-transparent font-mono text-xs text-amber-300 hover:bg-amber-500/10 hover:text-amber-200 disabled:opacity-40"
            >
              <Binary className="mr-1 h-3 w-3" />
              {tampering ? "flipping…" : "run tamper demo"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Verification result */}
      {verification && (
        <Card
          className={`mb-6 ${
            verification.ok
              ? "border-emerald-900/50 bg-emerald-950/10"
              : "border-rose-900/60 bg-rose-950/10"
          }`}
        >
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider">
              {verification.ok ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Chain OK</span>
                </>
              ) : (
                <>
                  <XCircle className="h-3.5 w-3.5 text-rose-400" />
                  <span className="text-rose-400">Chain broken</span>
                </>
              )}
              <span className="ml-auto text-[#6b8196]">
                {verification.verified_records.toLocaleString()} /{" "}
                {verification.total_records.toLocaleString()} records
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-2 font-mono text-[11px] md:grid-cols-2">
              <KV
                label="head_hash_lo"
                value={
                  verification.head_hash_lo_hex
                    ? `0x${verification.head_hash_lo_hex}`
                    : "—"
                }
              />
              <KV
                label="first_break_seq"
                value={
                  verification.first_break_seq_no != null
                    ? String(verification.first_break_seq_no)
                    : "—"
                }
              />
            </dl>
            {verification.breaks.length > 0 && (
              <div className="mt-3 overflow-hidden rounded border border-rose-900/40">
                <table className="w-full font-mono text-[11px]">
                  <thead className="bg-rose-950/40 text-rose-300">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-normal">seq_no</th>
                      <th className="px-3 py-1.5 text-left font-normal">kind</th>
                      <th className="px-3 py-1.5 text-left font-normal">detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {verification.breaks.slice(0, 20).map((b, i) => (
                      <tr key={i} className="border-t border-rose-900/30">
                        <td className="px-3 py-1.5 text-rose-300">{b.seq_no}</td>
                        <td className="px-3 py-1.5 text-rose-200">{b.kind}</td>
                        <td className="px-3 py-1.5 text-rose-100/80">{b.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {verification.breaks.length > 20 && (
                  <div className="bg-rose-950/20 px-3 py-1.5 text-[10px] text-rose-300/70">
                    … {verification.breaks.length - 20} more break(s) elided
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tamper result */}
      {tamper && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-amber-300">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
              Tamper demo · before vs. after
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-4 grid grid-cols-2 gap-2 font-mono text-[11px]">
              <KV label="record_index" value={String(tamper.tamper.record_index)} />
              <KV label="byte_offset" value={String(tamper.tamper.byte_offset)} />
              <KV
                label="file_offset"
                value={`0x${tamper.tamper.file_offset.toString(16)}`}
              />
              <KV
                label="flip"
                value={`0x${tamper.tamper.original_byte_hex} → 0x${tamper.tamper.mutated_byte_hex}`}
              />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <VerifyPanel title="clean copy" result={tamper.clean} goodWhenOk />
              <VerifyPanel title="mutated copy" result={tamper.mutated} goodWhenOk={false} />
            </div>

            <div
              className={`mt-4 rounded border p-3 font-mono text-xs ${
                tamper.first_break_seq_no != null
                  ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-300"
                  : "border-rose-900/60 bg-rose-950/40 text-rose-300"
              }`}
            >
              {tamper.first_break_seq_no != null ? (
                <>
                  <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
                  verifier caught the mutation at seq_no{" "}
                  <span className="text-emerald-200">
                    {tamper.first_break_seq_no}
                  </span>
                  .
                </>
              ) : (
                <>
                  <XCircle className="mr-1 inline h-3.5 w-3.5" />
                  verifier did not detect a mutation — unexpected; inspect the
                  file and offset.
                </>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-[#6b8196]">{label}</span>
      <span className="truncate text-[#e4edf5]">{value}</span>
    </div>
  );
}

function VerifyPanel({
  title,
  result,
  goodWhenOk,
}: {
  title: string;
  result: VerificationResult;
  goodWhenOk: boolean;
}) {
  const good = goodWhenOk ? result.ok : !result.ok;
  return (
    <div
      className={`rounded border p-3 ${
        good
          ? "border-emerald-900/50 bg-emerald-950/10"
          : "border-rose-900/60 bg-rose-950/10"
      }`}
    >
      <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider">
        <span className="text-[#6b8196]">{title}</span>
        {result.ok ? (
          <span className="text-emerald-400">OK</span>
        ) : (
          <span className="text-rose-400">BREAK</span>
        )}
      </div>
      <div className="space-y-1 font-mono text-[11px] text-[#9ab3c8]">
        <div>
          {result.verified_records.toLocaleString()} /{" "}
          {result.total_records.toLocaleString()} verified
        </div>
        <div className="truncate">
          head: {result.head_hash_lo_hex ? `0x${result.head_hash_lo_hex}` : "—"}
        </div>
        <div>
          first break seq: {result.first_break_seq_no ?? "—"}
        </div>
      </div>
    </div>
  );
}
