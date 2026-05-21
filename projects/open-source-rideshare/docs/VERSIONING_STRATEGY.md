# Versioning Strategy — Phase 5.3

**Project**: OpenRide / Open-Repo Knowledge Repository  
**Phase**: 5.3 — Federation & Distributed Versioning  
**Date**: 2026-05-21  
**Status**: Design — Pre-Implementation  
**See also**: FEDERATION_ARCHITECTURE.md, DIFFERENTIAL_SYNC_PROTOCOL.md

---

## Goal

Define how library content is versioned, how communities collaborate on updates, and how outdated or superseded content is handled. Version control for knowledge libraries has higher stakes than version control for software: a stale medical dosage reference or an outdated water treatment protocol can cause direct harm. The versioning design must make it easy to detect, flag, and replace outdated content.

---

## 1. Semantic Versioning for Library Content

Libraries use semantic versioning adapted for knowledge content:

```
MAJOR.MINOR.PATCH[-LABEL]

Examples:
  medical-primary-care-en   2.3.1
  water-treatment-en        1.0.0-draft
  seed-saving-en            3.1.0
```

**MAJOR** increments when the library's scope or structure changes fundamentally — a reorganization, a domain split, or an incompatible schema change. Nodes that have auto-update enabled do NOT automatically upgrade across major versions. An operator must review and explicitly approve.

**MINOR** increments when substantial new content is added or existing sections are significantly revised. Auto-update across minor versions is opt-in per library. All minor version changes include a human-readable changelog entry.

**PATCH** increments for corrections: typos, broken links, updated citations, factual corrections without scope change. Nodes with auto-update enabled pull patches automatically.

**Labels**:
- `-draft`: community-contributed content not yet through safety review
- `-reviewed`: completed one round of domain-expert review
- `-verified`: completed two or more independent domain-expert reviews (required for medical, water, and safety-critical libraries)
- `-deprecated`: superseded by a newer version; retained for reference

For medical and safety-critical libraries, a `-draft` version MUST NOT be served as the primary content for any library. Draft versions are available for review but the node's default serving configuration must point to the latest `-verified` version.

### 1.1 Version Identity

A specific version is identified by a **version digest**: the SHA-256 hash of the library manifest at that version, hex-encoded. This is immutable even if the manifest URL changes.

```
version_digest: sha256:f3a4b2c1...
library_id:     medical-primary-care-en
semver:         2.3.1
label:          verified
```

Version digests are the canonical reference in all sync and delta protocols. Semver strings are human-readable aliases.

---

## 2. Collaborative Editing Workflow

### 2.1 Contribution Lifecycle

Contributions follow a four-stage lifecycle:

```
DRAFT → REVIEW → STAGING → PUBLISHED
```

**DRAFT**: A contributor (a community member, a node operator, or an upstream project) prepares a content change. The change is packaged as a signed delta bundle (see DIFFERENTIAL_SYNC_PROTOCOL.md). The draft is submitted to the library's canonical publisher node or a designated review node.

**REVIEW**: Domain experts review the delta. For medical and safety-critical libraries, at least two independent reviewers with documented domain expertise must approve before the change advances. For general reference content, one reviewer is sufficient. Review comments are stored as signed annotations attached to the delta bundle, not as separate documents.

**STAGING**: The approved delta is applied to the current library in a staging environment. Automated checks run: link validation, schema conformance, content hash generation. The staging version is available to any node that opts into a staging feed for final community review.

**PUBLISHED**: After staging validation and a configurable hold period (72 hours for patches, 7 days for minor versions, 30 days for major versions), the library version is published and announced to the federation.

### 2.2 Consensus Gates for Safety-Critical Content

Medical, water treatment, and seed-saving libraries require explicit consensus gates before publishing:

| Library Class | Gate Requirements |
|---|---|
| Medical | 2 independent domain-expert reviews + safety officer sign-off |
| Water / Sanitation | 2 independent reviews + public health officer sign-off |
| Seed Saving / Food | 1 domain-expert review + community period (7 days) |
| Botanical Reference | 1 domain-expert review |
| General Reference | Author self-review + automated checks |

Sign-off is cryptographic: the reviewer's node signs the delta bundle with a `ReviewApproval` activity that references the delta's content hash. A library version cannot be published if it lacks the required number of valid, distinct `ReviewApproval` signatures.

The sign-off chain is included in the published library manifest, allowing any receiving node to independently verify that the required reviews occurred.

### 2.3 Merge Conflict Resolution

When two communities independently extend the same library (e.g., community A and community B both modify the water treatment section), a merge conflict can arise when either submits their changes to the canonical publisher.

Conflict resolution follows this priority order:

1. **Non-overlapping changes merge automatically**: if A edited Section 3 and B edited Section 5, both changes apply without conflict.
2. **Three-way merge for overlapping changes**: using the common ancestor version as the base, a standard three-way merge is attempted. If successful (no overlapping lines modified differently), the merge applies automatically.
3. **Manual resolution for genuine conflicts**: if the three-way merge produces conflicts, the publisher node surfaces them to a designated editor. The editor resolves conflicts using the review interface and produces a merged delta bundle. Both original contributions are credited in the changelog.
4. **Voting for safety-critical conflicts**: if a conflict involves safety-critical content (medical dosages, water treatment concentrations, etc.) and multiple experts disagree on the correct resolution, the conflict escalates to a community vote among all `trusted`-state nodes that have the library installed. The majority position is adopted; the minority position is recorded in an editorial note.

---

## 3. Branch Strategy

Libraries maintain three named branches in the canonical publisher's version graph:

**main**: The current stable, published version. Nodes with default configuration follow this branch. Only promoted from `staging` after consensus gates pass.

**staging**: Integration branch for approved changes awaiting final validation. Libraries on this branch are available for opt-in testing by any node. Staging versions carry the `-reviewed` label.

**community**: Open branch for draft contributions from any federated community. Submissions arrive here first. Community branches are labeled `-draft`. No node is required to install community branch content, and the default admin interface does not surface it without explicit opt-in.

Branch names are encoded in the library manifest's `branch` field. Nodes configure which branches they track per-library.

### 3.1 Long-Running Community Forks

If a community needs a persistent local adaptation (e.g., a medical reference adapted for a specific country's drug formulary), they maintain a **fork branch** named `fork-<community-nid>-<description>`. Fork branches:

- Carry the community's own version counter starting from the fork point
- Include a `fork_of` field in the manifest pointing to the original library ID and version digest
- Can receive upstream patches from `main` via delta sync (see DIFFERENTIAL_SYNC_PROTOCOL.md)
- Are community-owned; the original publisher has no editorial authority over them

A fork that is accepted back into `main` is a merge contribution subject to the standard review lifecycle.

---

## 4. Diff and Delta Protocols for Minimal Storage

### 4.1 Content Diff Format

Library content is stored as ZIM files. ZIM is a binary format, so textual diffing does not apply. Instead, deltas are represented at two levels:

**Block-level delta**: A list of (block_index, new_block_hash, compressed_block_bytes) tuples. This is the primary wire format for sync (see DIFFERENTIAL_SYNC_PROTOCOL.md). Only changed 4 MB blocks are included.

**Article-level delta** (optional, for human review): A JSON document listing article additions, modifications, and deletions by article ID. This is generated alongside the block delta for review interface display. It is not used for content reconstruction but provides human-readable context.

```json
{
  "base_version": "sha256:abc...",
  "target_version": "sha256:def...",
  "article_changes": [
    {"action": "modify", "article_id": "drug-amoxicillin", "sections_changed": ["dosage", "interactions"]},
    {"action": "add",    "article_id": "drug-azithromycin-pediatric"},
    {"action": "delete", "article_id": "drug-chloramphenicol-topical", "reason": "discontinued"}
  ],
  "block_delta_url": "https://node.example.org/deltas/med-2.3.0-to-2.3.1.zdelta",
  "block_delta_hash": "sha256:ghi...",
  "signature": "ed25519:..."
}
```

### 4.2 Storage Efficiency

The canonical publisher stores:

- Full ZIM file for the current `main` version
- Block deltas for transitions between the last 10 versions on `main`
- Full ZIM file for each major version (retained indefinitely for rollback)
- Block deltas for `staging` and active `community` branches (pruned after 90 days of inactivity)

A node that has version N and wants version N+3 reconstructs it by applying three sequential deltas: N→N+1, N+1→N+2, N+2→N+3. Alternatively, if the bandwidth cost of three delta downloads exceeds the cost of a fresh download, the node downloads the full ZIM for N+3.

---

## 5. Deprecation Handling for Outdated Content

### 5.1 Deprecation Notice

When a library version (or an entire library) is superseded, the publisher issues a signed `Deprecate` activity. The activity includes:

- `deprecated_version`: the library ID and version digest being deprecated
- `reason`: human-readable reason (e.g., "superseded by v3.0.0", "content error in Section 4")
- `replacement`: optional pointer to the recommended replacement version
- `urgency`: one of `low`, `medium`, `high`, `critical`

Receiving nodes display deprecation notices in the admin interface. For `critical` urgency (e.g., a medical error), the node also surfaces a warning to end users viewing the deprecated content.

### 5.2 Urgency Levels

| Urgency | Description | Node Behavior (default) |
|---|---|---|
| `low` | Routine version advancement | Log and display in admin |
| `medium` | Notable improvement or significant correction | Admin notification |
| `high` | Important safety or accuracy issue | Operator prompt to upgrade |
| `critical` | Dangerous content error; do not use | Block content display; force operator action |

For `critical` deprecations, a node that has installed the deprecated version will display a warning interstitial before serving the content. The content is not automatically deleted — the operator must explicitly approve deletion or upgrade. This preserves operator control while making the danger visible.

### 5.3 Retention Policy

- **Deprecated patch versions**: pruned from peer storage after 180 days unless an operator has explicitly pinned them
- **Deprecated minor versions**: retained for 1 year; then operator-prompted for deletion
- **Deprecated major versions**: retained indefinitely by default; operators may delete after reviewing that no active users depend on them
- **Critical-urgency deprecated versions**: operator is prompted to delete within 30 days; after 90 days without action, the admin interface surfaces a persistent warning on every login

### 5.4 Rollback Support

An operator may roll back to a previous version (e.g., if a newly published version has a bug not caught in staging). Rollback is supported by:

1. Storing full ZIM files for each major version
2. Storing block deltas that enable reconstruction of minor and patch versions
3. The admin interface providing a version history with one-click rollback

Rollback resets the `installed_version` field in the node's library registry to the target version digest. It does not affect the federation's published version — it only changes which version this node serves locally.
