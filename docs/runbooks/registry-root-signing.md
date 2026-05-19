# Operator runbook — registry-root signing

Sprint 4e tier-2 signing layer. Read alongside
`pursue-opsec-staging/findings/2026-05-18-tier2-registry-signing-rfc.md`.

## What this is

Every promote bumps `data/asset-bytes-registry.jsonl`. A companion
file, `data/registry-root.txt`, holds a Merkle-root commitment over
the registry's canonical bytes. You sign a `git tag` whose tree
includes the bumped root file. That signature is what a reader
verifies to know your registry hasn't been mutated by anyone other
than you.

Two workflows enforce this:

* `.github/workflows/registry-root-on-promote.yml` — runs on every
  push that touches the registry OR the root file. Re-derives the
  root and **fails the build** if `registry-root.txt` is stale
  relative to the live registry. This is the workflow whose red
  state is load-bearing.
* `.github/workflows/verify-assets-daily.yml` — daily cron. Adds a
  `git tag -v` step on the latest `registry-root-*` tag. Opens a
  `signing-failure` issue on failure.

## Trust anchor

CI verification (the `verify-assets-daily.yml` signing step) trusts
**exactly the operator signing key, pinned via a GitHub Actions
secret**: `OPERATOR_ALLOWED_SIGNERS`. The secret holds one or more
allowed-signers lines (`<email> ssh-ed25519 <base64-key>`); the
verify step writes them to a runner-local tmp file at job time and
runs `git -c gpg.ssh.allowedSignersFile=<tmp> tag -v <latest>`.

Three previous trust-anchor designs were rejected:

1. **`docs/allowed-signers.txt` in-repo** — anyone with repo:write
   can swap in their own key. Same threat tier-2 exists to detect.
2. **`gh api .verification.verified`** — only confirms "valid
   signature against ANY GitHub-registered Signing key". A
   repo:write attacker with their *own* registered Signing key
   passes this check (Codex P1 #3, PR #68).
3. **Pubkey fetched from `https://github.com/<owner>.keys`** —
   same hole as (2) if the attacker is a collaborator.

The GHA secret is only modifiable by users with admin/maintain
role on the repo, which is the security boundary tier-2 cares
about.

`docs/allowed-signers.txt` remains in the repo as **reader
convenience** for offline `git tag -v`. Readers should also
cross-check against `https://github.com/<owner>.keys` or the
GitHub UI's "Verified" badge on the tag — but neither of those is
the production trust anchor.

## One-time setup

### 1. Upload your SSH signing key to GitHub

GitHub Settings → SSH and GPG keys → New SSH key. Choose **Key type:
Signing Key**. This is separate from any "Authentication" key you
already use for git push — both can be the same underlying pubkey,
but must be registered twice under the two key-types.

This step is what makes the "Verified" badge appear on signed tags
in the GitHub UI. It is NOT what gates the CI verify — that's the
secret below.

### 2. Set the `OPERATOR_ALLOWED_SIGNERS` repo secret

Repo Settings → Secrets and variables → Actions → New repository
secret.

* **Name**: `OPERATOR_ALLOWED_SIGNERS`
* **Value**: one line in OpenSSH allowed-signers format:
  ```text
  david@bpsaisoftware.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...
  ```

The principal (`david@bpsaisoftware.com`) must match your
`git config --global user.email` (git tag -s signs with that
principal by default).

If you ever rotate signing keys: update this secret in the same
step you upload the new key to GitHub Signing Keys.

### 3. Configure git for SSH signing

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub  # or your yubikey-backed key
git config --global tag.gpgsign true                        # auto-sign every tag
```

The `gpg.format=ssh` shape means git uses the SSH agent (yubikey
included) for signing, not GPG. No GPG key material needed.

### 4. Populate `docs/allowed-signers.txt` (reader convenience)

Replace the placeholder line with your real ssh-ed25519 public key:

```text
david@bpsaisoftware.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...
```

Source options:
* `cat ~/.ssh/id_ed25519.pub` (or the corresponding `.pub` for whichever key you signed with).
* `curl -s https://github.com/Buschleague.keys` to fetch GitHub's record of your keys.

Commit + push. Readers can now run local `git tag -v` against this
file for offline verification; the CI lane uses the GH-API anchor
described above regardless.

### 5. Sign the baseline registry-root tag

The current registry has 230 rows. Sign the current root state once,
then per-promote signings extend the chain.

```bash
# Compute the current root (idempotent; safe to re-run).
python scripts/registry_root.py

# Stage the bumped (or freshly-created) root files.
git add data/registry-root.txt data/registry-root-manifest.txt

# Commit them.
git commit -m "chore(registry): baseline registry-root commitment"
git push

# Sign + push the baseline tag against the freshly-pushed commit.
git tag -s registry-root-$(date -u +%Y-%m-%d-%H%M)-baseline HEAD
git push --tags
```

The tag name format is `registry-root-YYYY-MM-DD-HHMM[-baseline]`
(UTC; minute-level resolution). The `-baseline` suffix is convention
for the first signed root only — subsequent tags drop it.

### 6. Optional: configure tag-pattern protection on GitHub

In repo settings → Rules → Rulesets, add a rule that prevents
force-deletion of tags matching `registry-root-*`. This stops an
operator from accidentally `git push --delete origin
registry-root-2026-05-19-baseline` and erasing the trust anchor.

## Per-promote workflow

After every `pursue ingest run` that bumps the registry:

```bash
# Refresh the root file.
python scripts/registry_root.py

# Stage + commit alongside the manifest promote.
git add data/registry-root.txt data/registry-root-manifest.txt
git commit -m "chore(registry): promote tranche <short-sha>"
git push

# Sign the tag against the just-pushed commit.
git tag -s registry-root-$(date -u +%Y-%m-%d-%H%M) HEAD
git push --tags
```

(If `tag.gpgsign=true` is configured globally, `git tag` without
`-s` will sign anyway — the explicit `-s` is belt-and-suspenders.)

The `registry-root-on-promote.yml` workflow fires on push and
verifies the root file is in lockstep. The daily verify lane picks
up the new tag on its next 06:07 UTC tick and validates the
signature.

## Verification (any reader)

```bash
git clone https://github.com/BPSAI/pursue-index
cd pursue-index

# Latest signed tag.
git tag --list 'registry-root-*' --sort=-creatordate | head -1

# Verify the signature.
git -c gpg.format=ssh \
    -c gpg.ssh.allowedSignersFile=docs/allowed-signers.txt \
    tag -v registry-root-<YYYY-MM-DD-HHMM>

# Re-derive the root from the current registry.
python scripts/verify_registry_root.py \
    --registry data/asset-bytes-registry.jsonl \
    --root data/registry-root.txt \
    --signed-source ""
```

The first two together confirm: (a) the recorded root file is
authentic per the operator's signing key, (b) the live registry
still hashes to that root.

## Failure modes

### Workflow `registry-root-on-promote` failed red

The bumped registry and the root file are not in sync. Three paths:

1. You (the operator) edited the registry but forgot
   `python scripts/registry_root.py`. Re-run it, commit the
   freshly-bumped root file, and push.
2. **A bot writer landed a registry row without refreshing the
   root.** This should not happen after Sprint 4e — both
   `poll-pursue.yml` and `verify-assets-daily.yml` commit steps
   now run `registry_root.py` before staging. But if a future PR
   introduces a third registry writer that misses this step, this
   is what it'll look like. Add the missing
   `python scripts/registry_root.py` step + stage the root files
   alongside.
3. **The registry was tampered with** (the bytes you committed are
   not the bytes a reader sees). Roll the registry back from the
   latest signed tag's tree:
   ```bash
   git show registry-root-<latest>:data/asset-bytes-registry.jsonl > \
       data/asset-bytes-registry.jsonl
   python scripts/registry_root.py
   git diff data/registry-root.txt   # should be clean
   ```

### Workflow `verify-assets-daily` opened a `signing-failure` issue

GitHub reports the latest signed tag's `.verification.verified` as
false. Three paths:

1. **Key rotation in progress.** You uploaded a new Signing key to
   GitHub but the latest tag was signed with the old key (or vice
   versa). Re-sign the latest tag with the active key:
   ```bash
   git tag -d registry-root-<HHMM>      # delete local
   git push --delete origin registry-root-<HHMM>   # delete remote
   git tag -s registry-root-<HHMM> <original_commit>
   git push --tags
   ```
2. **Signing key removed from GitHub Settings.** Restore it under
   Settings → SSH and GPG keys → Signing keys. The tag will verify
   on the next daily tick.
3. **Genuine tampering.** Assume the worst. The tag itself was
   replaced by an attacker who had push access. Roll the repo back
   to the last commit before the tag landed:
   ```bash
   git log --show-signature data/registry-root.txt
   # find the last commit whose signature was valid
   ```
   Treat this as a security incident.

### Workflow `verify-assets-daily` opened a `signing-stale` issue

This is the **expected steady-state** signal after a bot writer
(silent-overlay catch from `verify-assets-daily.yml`, asset archive
from `poll-pursue.yml`) lands a new registry row. The bot refreshes
`data/registry-root.txt` in lockstep (so on-promote stays green),
but only you can sign a fresh `registry-root-*` tag. Until you do,
the daily verify reports `signing_state=stale` and files this
issue.

**Response**: sign a fresh tag against current HEAD:

```bash
git tag -s registry-root-$(date -u +%Y-%m-%d-%H%M) HEAD
git push --tags
```

The next daily cron tick sees the signed root match the current
root and does not file a new issue (the existing one stays open
until you close it or auto-close it via gh).

## Key rotation playbook

1. Decide on the replacement key. If the old key was yubikey-backed
   and you're rotating to a fresh yubikey: generate the new key
   on the new device, leave the old key in
   `allowed-signers.txt` for the rotation window.
2. Add the new key to `allowed-signers.txt`:
   ```text
   david@bpsaisoftware.com ssh-ed25519 OLD_KEY...
   david@bpsaisoftware.com ssh-ed25519 NEW_KEY...
   ```
3. Commit + push that change. Sign the commit with the NEW key.
4. Sign a "rotation note" commit:
   ```bash
   echo "Rotating to new signing key on $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
       > docs/key-rotation-log.md
   git commit -S -m "chore(security): key rotation note"
   ```
5. Sign the next `registry-root-*` tag with the new key.
6. After two or three subsequent promotes have signed with the new
   key (proves the new key is reliably in service), remove the old
   key from `allowed-signers.txt`. Past signatures from the old key
   stay verifiable in git history as evidence-of-past.

## Out-of-scope here

* **Sigstore / Rekor integration.** Defer per RFC §8.
* **Per-row signing.** Defer per RFC §8.
* **PQ-resistant primitives.** Defer per RFC §8.
* **Multi-signer schemes.** Not until a second operator joins.
