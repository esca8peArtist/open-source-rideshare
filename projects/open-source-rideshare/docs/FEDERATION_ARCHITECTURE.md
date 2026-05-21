# Federation Architecture — Phase 5.3

**Project**: OpenRide / Open-Repo Knowledge Repository  
**Phase**: 5.3 — Federation & Distributed Versioning  
**Date**: 2026-05-21  
**Status**: Design — Pre-Implementation  
**Predecessors**: Phase 5.1 (offline ZIM export, ready to merge), Phase 5.2 (Medical, Water, Seed, Food, Botanical content candidates)

---

## Goal

Enable libraries (curated offline knowledge packages) to be shared across communities with version control and collaborative updates. A community in rural Montana should be able to receive a medical reference library that a cooperative in Vermont has already verified, extend it with local context, and push those additions back for review. No central authority should be required for this to function — but central hubs can optionally accelerate discovery.

---

## 1. Distributed Identity Model

### 1.1 Node Identity

Every federation participant — a community server, a cooperative node, or an individual contributing peer — is identified by a **node identity** consisting of:

- A **public key** (Ed25519, 256-bit): generated locally, never leaves the node unless explicitly shared
- A **node ID**: SHA-256 hash of the public key, encoded as base58 (`nid_7xQm3...`)
- An optional **display name** and **home URL**: human-readable metadata attached to the identity, signed by the node's private key

Node identities are self-sovereign. No registration step is required. A node can participate in federation immediately after key generation.

```
Node Identity Bundle (public, shareable)
{
  "nid": "nid_7xQm3Rkv...",
  "public_key": "ed25519:ABC123...",
  "display_name": "Green Mountain Coop",
  "home_url": "https://gmc.example.org",
  "signed_at": "2026-05-21T14:00:00Z",
  "signature": "..."        // self-signed by the node's private key
}
```

### 1.2 Peer-to-Peer vs. Hub Models

The federation supports two topologies and any mix between them.

**Peer-to-peer (P2P)**: Two nodes exchange libraries directly. Each learns of the other through out-of-band introduction (email, QR code, community forum post). All trust decisions are local. This is the minimum viable federation: no infrastructure beyond the two nodes.

**Hub model**: A community-trusted hub node aggregates identities and library metadata from many peers. Peers do not need to discover each other directly; they query the hub. The hub does not store full library content — only metadata (name, version hash, publisher node ID, trust attestations). Hubs are optional acceleration infrastructure, not required gatekeepers.

Both models use identical wire protocols. A node cannot tell at the protocol level whether its counterpart is a leaf or a hub. This means a P2P deployment can migrate to hub-assisted discovery later without code changes.

### 1.3 No Single Root of Trust

There is no global registry, no certificate authority, and no domain that must remain online for federation to function. Trust is established locally through explicit endorsement chains (see Section 3). This mirrors the WebFinger + ActivityPub approach used by the Mastodon federation, adapted for library content rather than social posts.

---

## 2. Library Sharing Protocols

### 2.1 Discovery

A node discovers shareable libraries through four mechanisms, in priority order:

1. **Direct URL**: operator or user pastes a library manifest URL (`https://node.example.org/.well-known/libraries/medical-v2.3.json`)
2. **Hub query**: node queries a known hub's REST endpoint (`GET /api/federation/libraries?tag=medical&lang=en`)
3. **Peer advertisement**: a trusted peer pushes a signed `LibraryAnnounce` activity to the node's federation inbox (analogous to ActivityPub `Announce`)
4. **IPFS CID discovery**: if the node has IPFS enabled, it can resolve library content by CID published in a manifest

The hub query and peer advertisement mechanisms each return library manifests, not content. The manifest contains the metadata needed for the receiving node to decide whether to download and verify the library.

```
Library Manifest (JSON)
{
  "library_id": "med-primary-care-en",
  "version": "2.3.1",
  "publisher_nid": "nid_7xQm3...",
  "content_hash": "sha256:abc...",
  "merkle_root": "sha256:def...",
  "size_bytes": 48372910,
  "zim_url": "https://node.example.org/libraries/med-primary-care-en-2.3.1.zim",
  "delta_url": "https://node.example.org/libraries/med-primary-care-en-2.3.0-to-2.3.1.zdelta",
  "tags": ["medical", "primary-care", "english"],
  "content_domains": ["medicine"],
  "published_at": "2026-05-20T10:00:00Z",
  "signature": "ed25519:..."       // signed by publisher_nid private key
}
```

### 2.2 Trust Verification Before Download

A node MUST complete four checks before accepting content from a remote peer:

1. **Signature check**: verify manifest signature against the publisher's known public key
2. **Trust state check**: confirm publisher is in local trust store with state `trusted` or `provisional` (see Section 3)
3. **Content hash check**: after download, SHA-256 of received bytes must match `content_hash`
4. **Merkle tree check**: if the library has a merkle tree (required for any library >10 MB), verify root hash against `merkle_root`

Failure at any step aborts the import and logs the failure. The publisher's trust score is decremented (see Section 3.3).

### 2.3 Integrity Verification

Every ZIM file is accompanied by a detached signature file (`<name>.zim.sig`) and a merkle manifest (`<name>.merkle.json`). The merkle manifest lists SHA-256 hashes for each 4 MB block of the ZIM file. This allows:

- **Resumable downloads**: a partially downloaded ZIM can be verified block-by-block; only failed blocks need re-download
- **Tamper detection**: a single corrupted block is identified without re-hashing the entire file
- **Delta integrity**: when receiving a delta update, only changed blocks need new hash verification

The merkle tree depth is fixed at a maximum of 16 levels (sufficient for libraries up to ~256 GB at 4 MB blocks).

---

## 3. Trust Model

### 3.1 Trust States

Each node maintains a local trust store mapping `nid → trust_state`. The valid states are:

| State | Description |
|---|---|
| `unknown` | Never seen; no content accepted |
| `provisional` | Manually added or hub-introduced; content accepted but flagged; no auto-propagation |
| `trusted` | Actively trusted; content accepted and eligible for re-sharing |
| `suspended` | Temporarily suspended; content queued but not imported |
| `revoked` | Permanently revoked; all content from this node rejected |

State transitions:
- `unknown` → `provisional`: operator manually adds a node, or hub introduces it with a voucher from a trusted node
- `provisional` → `trusted`: operator explicitly upgrades after reviewing library content, or an established trusted peer provides a second endorsement
- `trusted` → `suspended`: automatic after 3 consecutive integrity failures within 30 days
- `suspended` → `trusted`: operator reviews and restores
- Any → `revoked`: operator-triggered; terminal; requires key rotation for re-admission

### 3.2 Peer Reputation Scoring

Each node maintains a rolling reputation score (0.0–1.0) for its peers, separate from the discrete trust state. The score is used to rank competing versions of the same library when multiple publishers exist.

Score inputs:
- **Integrity pass rate**: ratio of successful hash verifications to total downloads from this peer (weight 0.5)
- **Content quality endorsements**: number of distinct trusted nodes that have endorsed this peer's libraries (weight 0.3)
- **Version freshness**: how promptly this peer publishes updates relative to the original source (weight 0.2)

Score updates happen asynchronously after each library import or endorsement event. Scores are local — they are never shared with other nodes.

### 3.3 Cryptographic Signatures

All federation protocol messages are signed with the sender's Ed25519 private key:

- Library manifests: signed by the publishing node
- Endorsement records: signed by the endorsing node
- Delta announcements: signed by the originating node
- Revocation notices: signed by the revoking node

Signature verification uses the sender's public key retrieved from the local trust store or, for provisional nodes, from the manifest itself (bootstrap case, verified against the hub's cached copy).

### 3.4 Revocation Mechanisms

**Node revocation**: An operator revokes a peer's trust locally. The revocation is optionally broadcast to the operator's trusted peer set as a signed `Revoke` activity. Receiving nodes may apply the revocation or log it for review — automatic propagation of revocations is opt-in to prevent denial-of-service via malicious revocations.

**Key rotation**: A node whose private key is compromised can publish a signed `KeyRotation` notice from the old key (if still available) or through a trusted hub that can vouch for the continuity of identity. Key rotation does not change the node ID; it updates the public key in the identity bundle.

**Content revocation**: A library publisher can issue a signed `Withdraw` notice for a specific library version. Receiving nodes that have imported the library are notified and given a configurable grace period before the content is flagged as withdrawn. Withdrawn content is not automatically deleted — operators make that decision.

---

## 4. Case Studies

### 4.1 IPFS-Based Archives

The InterPlanetary File System provides a useful reference for content-addressed, distributed storage. IPFS uses content identifiers (CIDs) derived from the SHA-256 hash of the content, making each piece of content self-verifying and location-independent. The Filecoin network extends IPFS with economic incentives for storage persistence.

**What we adopt**: content-addressed manifests (library manifests include a content hash that serves the same verification role as an IPFS CID), and the block-level merkle tree structure.

**What we do not adopt**: IPFS's DHT-based routing, which requires persistent connectivity and a minimum peer set to function. Our federation is designed for nodes that may be offline for weeks. We use direct HTTP transfer with resumable downloads instead.

**Lesson**: The InterPlanetary Wayback Machine project demonstrated that IPFS alone is insufficient for persistence without incentive structures. Our trust model and hub architecture provide the social incentives that IPFS lacks.

### 4.2 Scientific Journal Federation Models

The Open Archives Initiative Protocol for Metadata Harvesting (OAI-PMH) allows repositories to expose structured metadata that aggregators harvest on a schedule. Institutional repositories like arXiv, PubMed Central, and CORE use this model to share preprints and full-text articles across institutions without a central authority controlling content.

**What we adopt**: the harvesting pull model (hubs pull library manifests from peers on a schedule, rather than requiring peers to push), and the concept of a `datestamp` in each record to enable incremental harvesting.

**What we adapt**: OAI-PMH uses XML over HTTP and does not include content integrity verification or publisher signatures. We replace the XML format with JSON and add mandatory Ed25519 signatures to all metadata records.

**Lesson**: OAI-PMH succeeded because it imposed minimal requirements on participating repositories. Our protocol follows this principle: a conforming node needs only to serve a JSON manifest endpoint and verify incoming signatures.

### 4.3 Wikipedia Federation Precedent

Wikipedia's sister project federation (Wikisource, Wikibooks, Wikivoyage, etc.) demonstrates how a family of content projects can share infrastructure (MediaWiki software, Wikimedia Commons media repository) while maintaining independent editorial governance. Wikidata serves as a shared structured knowledge graph that all projects can query without copying data.

**What we adopt**: the content module pattern — a "Botanical reference" library is a standalone module that can be included in any community's library set without requiring them to adopt the entire knowledge base.

**What we adapt**: Wikipedia's federation model relies on a shared database infrastructure controlled by the Wikimedia Foundation. Our federation has no shared infrastructure; each node is independently operated. We replicate the content-module concept but distribute it over the peer protocol.

**Lesson**: Wikipedia's edit history and talk pages are essential to its quality model. Our versioning strategy (see VERSIONING_STRATEGY.md) incorporates equivalent provenance tracking.

---

## 5. Implementation Timeline (Phase 5.4+)

### Phase 5.4 — Basic P2P Federation (Q3 2026)

Scope: two nodes can exchange libraries manually. No hub infrastructure.

- Node identity generation (Ed25519 key pair, node ID derivation)
- Library manifest format (JSON schema, signature generation and verification)
- Manual peer addition (operator pastes node URL into admin interface)
- One-way library push (publishing node pushes manifest to subscriber)
- Content hash verification on import
- Basic trust store (unknown / trusted / revoked states only)

Deliverable: two OpenRide deployments can share a ZIM library with integrity guarantees.

### Phase 5.5 — Hub Discovery + Merkle Verification (Q4 2026)

Scope: hub-assisted discovery, resumable downloads, full trust state machine.

- Hub node type (metadata aggregation, no content storage)
- Hub query API (`GET /api/federation/libraries`)
- Full trust state machine (provisional, suspended states)
- Merkle tree generation for ZIM files
- Resumable downloads (block-level verification)
- Peer reputation scoring

Deliverable: communities can discover libraries through a shared hub without direct introductions.

### Phase 5.6 — Collaborative Updates + Revocation (Q1 2027)

Scope: communities can submit content contributions; revocation propagates.

- Contribution submission protocol (signed delta packages)
- Endorsement chains (trusted node endorses provisional node)
- Revocation broadcast (opt-in propagation)
- Key rotation support
- Content withdrawal notices

Deliverable: full bidirectional collaboration across the federation with integrity and revocation guarantees.

---

## Appendix: Wire Protocol Summary

All federation HTTP endpoints use JSON bodies and require an `X-Federation-Signature` header containing the Ed25519 signature of the request body (base64-encoded).

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/federation` | GET | Node identity bundle |
| `/.well-known/libraries` | GET | Library manifest index |
| `/.well-known/libraries/{id}` | GET | Single library manifest |
| `/api/federation/inbox` | POST | Receive federation activities (Announce, Withdraw, Revoke) |
| `/api/federation/peers` | GET | Admin: list known peers |
| `/api/federation/peers` | POST | Admin: add a peer |
| `/api/federation/peers/{nid}/trust` | PUT | Admin: update trust state |
