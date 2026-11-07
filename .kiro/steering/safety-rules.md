---
inclusion: always
---

# Hauntlet safety rules (always loaded)

These rules bind every spec, task and generated artifact in this project. They
are the reason a prompt-injection *range* can be built and hosted responsibly.
Kiro must refuse or flag any work that violates them.

## Hard rules
1. **Dummy secrets only.** Any planted credential, token or key must be a
   non-functional dummy that grants access to nothing real. Never place a real
   secret anywhere in the repo, fixtures, or served content.
2. **Harmless effects only.** Every "side effect" a trap can induce must write to
   a disposable scratch path inside the run sandbox. No trap may instruct an
   agent to delete data, modify files outside scratch, exfiltrate real data, run
   a destructive command, or contact any host other than the run's own canary
   endpoint.
3. **Serve only to active runs.** Hostile content is served only for a valid,
   active run ID, and every such page is marked `noindex`. No trap is reachable
   by a drive-by crawler or an unrelated agent.
4. **No new offensive capability.** Trap content is adapted from published,
   citable benchmarks (RepoGuardBench, CIPR, CodeIPI (UK AISI inspect_evals
   `ipi_coding_agent`), injkt, arXiv 2607.05744, arXiv 2508.14925 (MCPTox),
   arXiv 2604.05969 ("A Formal Security Framework for MCP-Based AI Agents",
   whose abstract says it "presents MCPShield, a comprehensive formal security
   framework")). The project does not invent
   novel attack techniques; it measures known ones and generates defences.
5. **Defence is the deliverable.** Every room exists to produce a score and a
   fix. A room without a corresponding Exorcist guardrail is incomplete.

## Disclosure
If a room reveals a real weakness in a third-party product (notably Kiro's
re-prompt behaviour on changed MCP tool descriptions), report it to that vendor
before any public submission, and document the disclosure in the write-up.

## When in doubt
If a task could be read as building an attack tool rather than a test range,
stop and flag it. The test is: would this still be safe if a stranger pointed
their agent at it? If not, it does not ship.
