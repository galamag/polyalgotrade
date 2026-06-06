# Security

Money is at stake. These rules are hard constraints; the `security-reviewer` subagent gates
changes to the signing/key path.

## Keys & secrets
- Real keys/secrets live only in `.env` (gitignored, mode 600 on servers). `.env.example` is
  the only committed template.
- **Never** print a private key or API secret to logs, stdout, or chat. The logging standard
  forbids it (`../architecture/logging-observability.md`).
- Use a dedicated trading wallet funded with only the active bankroll — never a personal
  main wallet.
- Rotate API credentials if a machine is compromised or shared.

## Signing path (Polymarket V2)
- ERC-1271 / signature types are security-critical. The research flags `signature_type=3`
  (deterministic deposit wallets) as the common "insufficient balance" failure — get this
  right with the verified SDK (claim C4) and test with ≤$1 orders first.
- Any change to order signing/serialization → `security-reviewer` review + a test.

## Third-party tooling (MCP)
- MCP servers connect to *Claude Code* only (dev-time), never to the bot.
- **Read-only data servers only**, after reviewing their code. **Never** an MCP holding
  trade/private keys. See `tooling.md` and ADR 0005.

## Operational
- VPS: SSH key only, firewall, least privilege, keep the system patched.
- Kill-switch: a single command/flag that cancels open orders and halts trading
  (`runbook.md`).
- Withdrawals are manual and human-initiated — the bot never moves funds off-venue.
