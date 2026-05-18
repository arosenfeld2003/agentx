# Phase 0f: First Self-Task

**Status:** `[~]` — implemented, pending real-world verification

## Description

Verify the full email round-trip: `send_task.py` sends a `[task]` email from the VPS
host → listener picks it up → dispatches ralph → listener sends a reply email.

`send_task.py` running and sending is confirmed. What remains unverified is the
listener side: receiving the email, dispatching ralph, and replying.

## Acceptance Criteria

- [ ] Listener receives a `[task]` email and logs "Processing message"
- [ ] `ralph.sh` subprocess is launched (appears in listener log)
- [ ] Reply email is received at the sending address
- [ ] IMPLEMENTATION_PLAN shows the full loop verified end-to-end

## Known Blockers

- Requires the listener daemon running on the VPS host
- Requires a real email to be sent and received; cannot be mocked from inside Docker
- Verification must be done by operator via VPS observation

## Notes

`send_task.py` must run on the VPS host — email credentials are not available inside
the Docker container.
