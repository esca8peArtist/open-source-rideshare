# Differential Sync Protocol — Phase 5.3

**Project**: OpenRide / Open-Repo Knowledge Repository  
**Phase**: 5.3 — Federation & Distributed Versioning  
**Date**: 2026-05-21  
**Status**: Design — Pre-Implementation  
**See also**: FEDERATION_ARCHITECTURE.md, VERSIONING_STRATEGY.md

---

## Goal

Specify the wire protocol for transferring library updates between federated nodes with minimal bandwidth. Libraries can exceed 1 GB. Many communities using this system operate on intermittent, low-bandwidth connections (satellite, shared cellular, community mesh networks). The protocol must be usable when a node has 50 KB/s uplink and may lose connectivity mid-transfer.

---

## 1. Delta Compression Approach

### 1.1 Block-Level Rsync Analogue

The sync protocol is modeled on the rsync rolling-checksum algorithm, adapted for ZIM files and the federation's security requirements.

ZIM files are divided into fixed-size **blocks** of 4 MB. For each block, the publisher maintains:

- A 4-byte rolling checksum (Adler-32) for fast scanning
- A SHA-256 hash for integrity verification

A node that already has version N of a library and wants version N+1 sends its **block manifest** to the publisher: a list of (block_index, rolling_checksum, sha256_hash) for each block it already holds. The publisher compares this against version N+1's blocks and computes the minimal set of blocks that differ.

The response is a **delta package**: a compressed archive containing only the changed blocks, plus a manifest listing which block indices to replace and which to retain unchanged.

```
Delta Package Format
delta/
  manifest.json       -- block-level change list, signed
  block_0042.zst      -- zstd-compressed replacement for block 42
  block_0107.zst      -- replacement for block 107
  ...
```

The receiving node reconstructs version N+1 by:
1. Verifying the delta manifest signature
2. For each block in the manifest: replace the old block with the decompressed replacement
3. Verify the assembled file's SHA-256 against the target version's `content_hash`
4. Verify the merkle tree root against the target version's `merkle_root`

If steps 3 or 4 fail, the node discards the assembled file and requests a fresh full download.

### 1.2 Compression

All delta blocks use **Zstandard (zstd)** compression at level 3 (default). Zstd is chosen over gzip because:

- 3–4x faster decompression at comparable compression ratios
- Available as a pure-Python library (`zstandard`) with no native build required
- Well-suited to the binary block format of ZIM files

A node may negotiate a different compression level with the publisher (e.g., level 1 for fastest decompression on a resource-constrained device, level 9 for maximum compression to minimize bytes over satellite). The negotiated level is specified in the `Accept-Zstd-Level` HTTP header.

### 1.3 Delta Size Estimation

Before the full block manifest exchange, a node can request a **size estimate** from the publisher:

```
GET /api/federation/libraries/medical-primary-care-en/delta-estimate?from=sha256:abc...&to=sha256:def...
```

The publisher responds with an estimated delta size in bytes. The node uses this to decide whether to request the delta or download the full ZIM (whichever is smaller). The threshold is configurable per node (default: if estimated delta > 60% of full file size, download the full file).

---

## 2. Incremental Sync Strategy for Low-Bandwidth Environments

### 2.1 Sync Session

A sync session is a single coordinated exchange between a subscriber node and a publisher (or hub). Sessions are designed to be resumable: if connectivity drops mid-transfer, the session can be resumed from the last verified block.

**Session initiation**:
```
POST /api/federation/sync/sessions
Body: {
  "subscriber_nid": "nid_8xRm4...",
  "library_id": "medical-primary-care-en",
  "installed_version": "sha256:abc...",
  "target_version": "sha256:def...",      // or "latest"
  "max_bandwidth_kbps": 50,               // optional hint
  "resume_token": null                    // or token from a prior interrupted session
}
```

**Session response**:
```json
{
  "session_id": "sess_A3kQm...",
  "delta_manifest_url": "https://publisher.example.org/sessions/sess_A3kQm/manifest",
  "blocks_changed": 14,
  "estimated_bytes": 38291456,
  "expires_at": "2026-05-22T14:00:00Z"
}
```

The session token is valid for 24 hours. If the subscriber resumes within that window, it provides `resume_token: "sess_A3kQm"` and the publisher resumes from the last acknowledged block.

### 2.2 Scheduled Sync for Intermittent Connections

Nodes in low-bandwidth environments configure **sync windows**: time periods when bandwidth is available and sync is permitted to run. The sync scheduler respects these windows and pauses mid-session when a window closes.

```yaml
# Node configuration example
sync:
  windows:
    - weekdays: ["mon", "wed", "fri"]
      start_utc: "02:00"
      end_utc: "05:00"
    - weekdays: ["sat"]
      start_utc: "00:00"
      end_utc: "08:00"
  max_concurrent_sessions: 1
  bandwidth_limit_kbps: 40          # leave headroom for operational traffic
  priority_order:
    - medical-primary-care-en       # highest priority: sync first
    - water-treatment-en
    - seed-saving-en
```

Within a sync window, the scheduler processes libraries in priority order. If a window closes mid-session, the session is suspended (the resume token is saved to local storage). The next window continues from the last verified block.

### 2.3 Offline-First Operation

A node that is offline can still serve its locally installed library versions to users. The sync protocol is entirely decoupled from the serving layer. A node that has been offline for 60 days and then reconnects will:

1. Query the publisher for the latest version digest
2. Compare against locally installed version
3. Request a delta sync (or full download if the delta chain is too long)
4. Verify and apply the update
5. Serve the updated version to local users

During the gap, users receive a notice in the library interface: "This library was last updated 60 days ago. A newer version may be available." This notice is generated by the local node based on the `published_at` timestamp in the installed manifest — it does not require connectivity.

---

## 3. Validation and Integrity Verification

### 3.1 Checksums

Every artifact in the protocol has a mandatory SHA-256 hash that is verified before use:

| Artifact | Hash field | Verified by |
|---|---|---|
| Library ZIM file | `content_hash` in manifest | Subscriber after full download |
| Delta package archive | `delta_hash` in delta manifest | Subscriber after delta download |
| Individual delta blocks | Per-block hash in manifest | Subscriber after each block |
| Delta manifest | Signature covers full manifest body | Subscriber immediately on receipt |
| Library manifest | `signature` field | Subscriber before any download begins |

Hash mismatches abort the operation and are logged with the publisher's node ID. Three consecutive hash mismatches from the same publisher in 30 days trigger automatic trust state transition from `trusted` to `suspended` (see FEDERATION_ARCHITECTURE.md Section 3.1).

### 3.2 Merkle Trees

Each ZIM library has an associated merkle tree where:

- **Leaves**: SHA-256 hashes of consecutive 4 MB blocks
- **Internal nodes**: SHA-256 of the concatenation of child hashes
- **Root**: stored in the library manifest as `merkle_root`

The merkle tree enables two capabilities:

**Selective verification**: A node that has only downloaded blocks 0–20 of a 100-block library can verify those 20 blocks without downloading the rest. The publisher sends the sibling hashes needed to reconstruct the path from each leaf to the root (a merkle proof). This is used for resumable downloads: each verified block is written to disk immediately.

**Tamper localization**: If the final SHA-256 of the assembled file fails, the merkle tree identifies which block is corrupted by binary search: verify the left subtree; if it passes, the corruption is in the right subtree; recurse. This avoids re-downloading the entire file when a single block is corrupt.

Merkle trees are computed by the publisher and stored as `<library_id>-<version_digest>.merkle.json`. Subscribers download the merkle tree file at the start of a sync session.

### 3.3 Protocol-Level Replay Protection

All federation protocol requests include:

- A `nonce` field: a random 128-bit value generated per-request
- A `timestamp` field: UTC ISO-8601 with second precision
- The signature covers the nonce and timestamp

Receiving nodes reject requests with a `timestamp` more than 5 minutes old (clock skew tolerance). Nonces are stored in a short-term cache (LRU, 10-minute window) and duplicate nonces from the same sender are rejected. This prevents replay attacks where an attacker captures and re-submits a valid signed request.

---

## 4. Conflict Resolution on Sync

### 4.1 Conflict Scenarios

A conflict on sync occurs when a subscriber has locally modified a library (e.g., added community annotations) and the publisher has also published a new version. The sync protocol identifies three scenarios:

**No local modifications**: Subscriber's installed content is identical to the version at the sync base point. Standard delta apply; no conflict.

**Additive local modifications**: Subscriber has added new articles (e.g., local plant species in a botanical library) that do not exist in the publisher's new version. The delta apply proceeds; the subscriber's additional articles are retained alongside the publisher's updates. The subscriber's local additions are flagged as `community-local` and not included in the publisher's version.

**Conflicting modifications**: Subscriber has modified an article that the publisher has also modified between the subscriber's base version and the target version. This is a genuine conflict.

### 4.2 Last-Write-Wins (Default for Patches)

For `PATCH`-level updates (Section 1 of VERSIONING_STRATEGY.md), the default conflict resolution is last-write-wins: the publisher's version takes precedence for any article the publisher has touched. The subscriber's local modifications to those articles are preserved in a conflict archive (stored locally, flagged for operator review).

Last-write-wins is appropriate for patch updates because patches are corrections — the publisher's corrected version is almost always more accurate than the subscriber's local edit.

### 4.3 Three-Way Merge (Minor and Major Versions)

For `MINOR` and `MAJOR` version updates, a three-way merge is attempted:

1. **Base**: the version at the subscriber's last sync point
2. **Publisher branch**: publisher's new version
3. **Subscriber branch**: subscriber's local modifications

The merge engine computes a diff from base to publisher and a diff from base to subscriber. Where diffs do not overlap, both sets of changes are applied. Where diffs overlap, the conflict is surfaced to the operator.

The three-way merge is implemented at the article level (not the block level). Each article's content is compared as a sequence of paragraphs. This gives more meaningful conflict regions than byte-level diffing.

### 4.4 Voting Mechanism

For safety-critical libraries (medical, water), where both publisher and subscriber have made conflicting changes to safety-critical content, neither last-write-wins nor automatic merge is sufficient. The conflict is escalated to a federation vote:

1. The publisher broadcasts a `ConflictNotice` activity to all `trusted`-state nodes that have the library installed
2. Nodes cast a signed `ConflictVote` activity within a 7-day window
3. The position with a majority of votes is adopted as the resolved version
4. The minority position is recorded in an editorial note appended to the article

Voting is conducted over the federation protocol. Nodes that are offline during the voting window do not cast votes. A quorum of at least 3 voting nodes is required; if fewer than 3 trusted nodes participate, the publisher's version takes precedence and the conflict is flagged for manual resolution.

---

## 5. Implementation Roadmap

### Phase 5.4 — Basic Sync (Q3 2026)

Target: two nodes can sync a library. No resumability, no compression negotiation.

- Full ZIM download via HTTP with SHA-256 verification
- Block manifest format (client-side generation)
- Publisher-side delta computation (naive: full file diff, not optimized)
- Delta package format (zstd-compressed blocks)
- Delta application (reconstruct target file from base + delta)
- Post-apply merkle root verification

Acceptance criterion: a 500 MB ZIM file can be updated across a 1 Mbps test link; the resulting file passes SHA-256 and merkle verification.

### Phase 5.5 — Resumable + Scheduled Sync (Q4 2026)

Target: sync works reliably on intermittent connections.

- Session model (session_id, resume_token, per-block acknowledgment)
- Sync window scheduler
- Per-block streaming write (write verified blocks to disk immediately)
- Delta size estimation endpoint
- Automatic fallback to full download when delta exceeds size threshold
- Publisher-side session expiry cleanup

Acceptance criterion: a sync session interrupted at 40% completion resumes without re-downloading the already-transferred blocks.

### Phase 5.6 — Conflict Resolution + Safety Voting (Q1 2027)

Target: two communities can independently edit the same library and merge their changes.

- Three-way merge engine (article level)
- Conflict archive format
- ConflictNotice and ConflictVote federation activities
- Operator conflict review interface in admin
- Quorum enforcement for safety-critical votes

Acceptance criterion: two independently edited versions of a medical library merge correctly for non-overlapping edits; overlapping edits are surfaced to operators with both versions shown side-by-side.

### Phase 5.7 — Bandwidth Optimization (Q2 2027)

Target: reduce bandwidth by 50% for typical weekly sync workloads.

- Compression level negotiation (`Accept-Zstd-Level` header)
- Rsync rolling-checksum optimization (replace naive block diff)
- Publisher-side block deduplication across library versions
- Content-defined chunking (variable block sizes for better dedup on text-heavy content)

Acceptance criterion: a weekly patch sync for a 500 MB medical library transfers fewer than 5 MB on a week with 10 article updates.

---

## Appendix: Block Manifest Wire Format

```json
{
  "library_id": "medical-primary-care-en",
  "installed_version": "sha256:abc...",
  "block_size_bytes": 4194304,
  "blocks": [
    {"index": 0, "adler32": 1234567890, "sha256": "sha256:aaa..."},
    {"index": 1, "adler32": 987654321,  "sha256": "sha256:bbb..."},
    ...
  ],
  "subscriber_nid": "nid_8xRm4...",
  "timestamp": "2026-05-21T14:00:00Z",
  "nonce": "a3f2b1c9d4e5f6a7b8c9d0e1",
  "signature": "ed25519:..."
}
```

## Appendix: Delta Manifest Wire Format

```json
{
  "session_id": "sess_A3kQm...",
  "base_version": "sha256:abc...",
  "target_version": "sha256:def...",
  "block_size_bytes": 4194304,
  "blocks_changed": [
    {"index": 42, "sha256": "sha256:new42...", "file": "block_0042.zst", "size_bytes": 2831950},
    {"index": 107, "sha256": "sha256:new107...", "file": "block_0107.zst", "size_bytes": 1024000}
  ],
  "blocks_retained": [0, 1, 2, 3, 4, 5, 41, 43],
  "target_content_hash": "sha256:def...",
  "target_merkle_root": "sha256:ghi...",
  "publisher_nid": "nid_7xQm3...",
  "timestamp": "2026-05-21T14:05:00Z",
  "nonce": "b4c3d2e1f0a9b8c7d6e5f4a3",
  "signature": "ed25519:..."
}
```
