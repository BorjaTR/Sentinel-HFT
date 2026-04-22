"use client";

import { useState, useCallback } from "react";
import { FileInput, Shuffle, MinusCircle, Clock, Info } from "lucide-react";

// DrillStressPanel — pcap replay path + chaos toggles for the drill
// runner. Sits next to the preset chips so an operator can convert the
// "fresh-ticks" run into a deterministic replay of a captured pcap, or
// stress the input with packet reorder / drop / lag before measuring
// whether the deterministic risk gate still rejects what it should.
//
// Surface contract:
//   - State stays local to this component; on every change we call
//     ``onChange({ pcap, chaos })`` so the parent can spread that onto
//     the ``overrides`` object it sends into ``streamDrill`` / ``runDrill``.
//   - We ALWAYS pass ``chaos`` even when it's all zeros, because the
//     backend expects a fully-typed object — nullable fields would be
//     a different schema break.
//   - The pcap field is a string path; the backend interprets it as
//     local-to-the-server (e.g. /var/sentinel/pcap/2026-04-22.pcap).
//     A future iteration can swap this for a /api/pcaps catalogue
//     dropdown — the client surface would not need to change.
//
// Provenance flips automatically: lib/sentinel-api.ts notices a non-
// empty ``overrides.pcap`` and dispatches ``sentinel:source = "replay"``
// instead of ``"live"`` so the persistent ProvenancePill flips its
// badge from a green LIVE pulse to the sky REPLAY indicator.

export interface ChaosOverrides {
  /** Probability (0..1) that each input frame is held back and re-
   *  emitted out-of-order in a small window. The reorder primitive
   *  itself is in the backend; this knob only sets the per-frame
   *  probability that the primitive fires. */
  reorder_pct: number;
  /** Probability (0..1) that each input frame is silently dropped on
   *  the wire before it ever reaches the parser. Used to stress the
   *  per-stage timeout / replay path. */
  drop_pct: number;
  /** Constant added wire-side latency in microseconds, applied before
   *  the parser timestamp is taken. Useful for stretching the latency
   *  histogram and proving the per-stage attribution still adds up. */
  lag_us: number;
}

export interface StressOverrides {
  pcap: string;
  chaos: ChaosOverrides;
}

const DEFAULT_CHAOS: ChaosOverrides = {
  reorder_pct: 0,
  drop_pct: 0,
  lag_us: 0,
};

export function DrillStressPanel({
  disabled,
  onChange,
}: {
  disabled?: boolean;
  onChange: (overrides: StressOverrides) => void;
}) {
  const [pcap, setPcap] = useState<string>("");
  const [chaos, setChaos] = useState<ChaosOverrides>(DEFAULT_CHAOS);

  const fire = useCallback(
    (next: { pcap?: string; chaos?: ChaosOverrides }) => {
      const merged: StressOverrides = {
        pcap: next.pcap ?? pcap,
        chaos: next.chaos ?? chaos,
      };
      onChange(merged);
    },
    [pcap, chaos, onChange],
  );

  const setPcapValue = (v: string) => {
    setPcap(v);
    fire({ pcap: v });
  };

  const setChaosField = (k: keyof ChaosOverrides, v: number) => {
    const next = { ...chaos, [k]: v };
    setChaos(next);
    fire({ chaos: next });
  };

  const replayMode = pcap.trim().length > 0;
  const chaosActive =
    chaos.reorder_pct > 0 || chaos.drop_pct > 0 || chaos.lag_us > 0;

  return (
    <div className="mb-4 rounded-lg border border-[#1a232e] bg-[#0f151d] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
          <Info className="h-3 w-3 text-sky-400" />
          Stress &amp; replay
          <span className="rounded bg-[#0a0e14] px-1.5 py-0.5 text-[9px] text-[#4d617a]">
            wire-level
          </span>
        </div>
        <div className="flex items-center gap-2">
          {replayMode && (
            <span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-sky-300">
              REPLAY
            </span>
          )}
          {chaosActive && (
            <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-amber-300">
              CHAOS
            </span>
          )}
        </div>
      </div>

      {/* PCAP replay row */}
      <div className="mb-3 flex items-center gap-3">
        <label className="flex shrink-0 items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
          <FileInput className="h-3 w-3 text-sky-400" />
          pcap path
        </label>
        <input
          type="text"
          spellCheck={false}
          disabled={disabled}
          value={pcap}
          onChange={(e) => setPcapValue(e.target.value)}
          placeholder="/var/sentinel/pcap/2026-04-22.pcap (leave empty for live ticks)"
          className="flex-1 rounded border border-[#1f2a38] bg-[#0a0e14] px-2.5 py-1.5 font-mono text-[11px] text-[#e4edf5] outline-none placeholder:text-[#4d617a] focus:border-sky-500/40 disabled:opacity-40"
        />
        {pcap && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setPcapValue("")}
            className="rounded border border-[#1f2a38] bg-[#0a0e14] px-2 py-1 font-mono text-[10px] text-[#6b8196] hover:text-[#e4edf5] disabled:opacity-40"
          >
            clear
          </button>
        )}
      </div>

      {/* Chaos knobs */}
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <ChaosKnob
          icon={Shuffle}
          label="reorder %"
          unit="%"
          step={1}
          min={0}
          max={20}
          value={chaos.reorder_pct}
          disabled={disabled}
          onChange={(v) => setChaosField("reorder_pct", v)}
          hint="frames re-emitted out of arrival order"
        />
        <ChaosKnob
          icon={MinusCircle}
          label="drop %"
          unit="%"
          step={1}
          min={0}
          max={10}
          value={chaos.drop_pct}
          disabled={disabled}
          onChange={(v) => setChaosField("drop_pct", v)}
          hint="frames silently lost on the wire"
        />
        <ChaosKnob
          icon={Clock}
          label="lag"
          unit="µs"
          step={50}
          min={0}
          max={2000}
          value={chaos.lag_us}
          disabled={disabled}
          onChange={(v) => setChaosField("lag_us", v)}
          hint="constant wire-side latency added pre-parse"
        />
      </div>

      <div className="mt-3 font-mono text-[10px] leading-relaxed text-[#4d617a]">
        Replay re-runs a captured pcap deterministically — the
        ProvenancePill flips to <span className="text-sky-300">REPLAY</span>.
        Chaos stresses the input <em>before</em> the parser timestamp, so
        the per-stage latency attribution still adds up and the
        deterministic risk gate is exercised under wire degradation.
      </div>
    </div>
  );
}

function ChaosKnob({
  icon: Icon,
  label,
  unit,
  step,
  min,
  max,
  value,
  disabled,
  onChange,
  hint,
}: {
  icon: typeof Shuffle;
  label: string;
  unit: string;
  step: number;
  min: number;
  max: number;
  value: number;
  disabled?: boolean;
  onChange: (v: number) => void;
  hint: string;
}) {
  const pct = Math.round(((value - min) / Math.max(1, max - min)) * 100);
  const active = value > 0;
  return (
    <div
      className={`rounded border p-2.5 ${
        active
          ? "border-amber-900/50 bg-amber-950/20"
          : "border-[#1a232e] bg-[#0a0e14]"
      }`}
    >
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
        <span className="flex items-center gap-1.5">
          <Icon
            className={`h-3 w-3 ${active ? "text-amber-300" : "text-[#4d617a]"}`}
          />
          {label}
        </span>
        <span
          className={`font-semibold ${
            active ? "text-amber-200" : "text-[#9ab3c8]"
          }`}
        >
          {value}
          <span className="ml-0.5 text-[#4d617a]">{unit}</span>
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-amber-400 disabled:opacity-40"
        aria-label={label}
      />
      <div className="mt-1 font-mono text-[9px] text-[#4d617a]">{hint}</div>
      <div className="sr-only">{pct}%</div>
    </div>
  );
}
