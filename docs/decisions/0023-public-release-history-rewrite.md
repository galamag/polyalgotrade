# ADR 0023 — Public release: history rewritten to remove a personal email; publish to a fresh repository

- **Date:** 2026-11-20
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
The user wants the repository public, as portfolio evidence for a hackathon application. A
pre-publication audit of every git object, reachable and dangling, found no secrets: no private
keys, API keys or tokens, and the RPC key held in the local `.env` occurs in no object. It found
one privacy problem, in two places:

1. The design spec carried the owner's personal email address on its `Owner:` line, in every
   commit since the first.
2. The original private GitHub repository still serves early commits that were authored with that
   address and later replaced by a force-push. A force-push only moves the branch; the old commits
   stay fetchable by SHA until GitHub garbage-collects them, which only GitHub Support or deleting
   the repository can force.

ADR 0011 records that the personal Polymarket account uses an email login, so the address is more
than contact data.

## Options considered
1. **Flip the existing repository to public** — rejected. It leaks the address through both
   paths: fixing the file in a new commit does not remove it from history, and we cannot remove
   the dangling commits ourselves.
2. **Fresh repository with one squashed commit** — safe, but it discards 134 commits of history,
   which is most of the portfolio value.
3. **Rewrite history to change that one line, then publish `main` to a brand-new repository** —
   keeps the history. A push sends only objects reachable from the pushed branch, so neither the
   old blobs nor the dangling commits can follow.

## Decision
Option 3. `git filter-branch --index-filter` replaced the address with the GitHub handle in the
one affected file across all 134 commits. The old tip is kept locally as
`refs/backup/pre-email-scrub` — deliberately not a branch, so `git push --all` cannot publish it.
The original private repository stays private, as an archive, and is never made public.

The README was rewritten in the same session to say plainly what this project is: a personal
experiment in which no strategy passed its gate.

## Rationale
Principle 7 (keys and private data never leak) and principle 1 (honesty): the public face of the
project must not overstate it, and publishing must not cost the owner their privacy. Option 3 is
the only one that satisfies both without losing the record of the work.

Verification, run on the rewritten branch:
- 134 commits before and after; author, committer, dates and messages identical for every commit.
- Each commit differs from its original by exactly one line in the one file.
- The address occurs in no object of a simulated publish (a push of `main` into an empty bare
  repository), and every commit identity there is the GitHub noreply address.

## Consequences
- Positive: the repository can be published with its full history and no personal email.
- Negative / risks: **every commit SHA changed.** SHAs quoted in older notes or session logs
  refer to the pre-rewrite history. Local `main` no longer shares history with the old private
  remote: never pull from it or merge it into `main`.
- Follow-ups: push **only `main`** to the new repository (never `--mirror`, which would publish
  the backup ref and the old remote-tracking refs). Enable GitHub's "Keep my email addresses
  private" and "Block command line pushes that expose my email".
