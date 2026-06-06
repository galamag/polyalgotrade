# VPS Setup

For 24/7 uptime of **deterministic** strategies. We are **not** competing with co-located HFT
— the goal is stable uptime, not sub-100ms execution.

## Choice (per research, verify L1 ourselves)
- **Hetzner Cloud CX22** (Helsinki/Falkenstein/Nuremberg): ~€5–6/mo, 2 vCPU, 4 GB RAM,
  40 GB NVMe. Sufficient for maker/copy/monitoring.
- Lower latency regions (Dublin/Amsterdam) exist but the latency numbers come from VPS-vendor
  blogs (claim L1) — **measure before paying for "trading-tuned" VPS.**

> ⚠️ No GPU on the €5 VPS → it cannot run local LLMs. LLM-dependent (news) strategies run on
> the desktop or wait for a GPU VPS. See `../architecture/intelligence-layer.md`.

## First steps (Phase 0/1)
1. From the chosen region, measure real latency to the CLOB before committing:
   `ping clob.polymarket.com` and `mtr clob.polymarket.com`. Record results in
   `../research/claims-verification.md` (L1).
2. Ubuntu 22.04, non-root user, SSH key only, UFW (deny inbound except SSH).
3. Install `uv`; clone repo; `uv sync`.
4. Run as a `systemd` unit; logs to `journalctl` (structlog JSON → stdout).
5. Secrets via `.env` on the box (mode 600), never in git.

## Notes
- The desktop (Windows 11, RTX 4070 Ti Super) is the dev machine and the only place that runs
  local LLMs. Production deterministic bots belong on the VPS (the desktop sleeps/reboots).
