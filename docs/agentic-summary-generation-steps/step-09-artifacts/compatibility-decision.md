# Step 9 contract and persistence decision

Inspection before implementation found that SummaryContent has plain executive
and key-point strings, and section-wide IDs only. It cannot express individual
claim support. Step 9 will add a typed supported-content subclass and a bounded
writer-fragment response contract, preserving the existing SummaryContent and
TenderSummary formats and legacy rows unchanged.

Step 8 already stores bounded typed results nested in orchestration.v1. Step 9
will extend that nested union for writer fragments, paged inclusion manifests
and an intermediate draft seal. The SQL JSON root and existing atomic
step/checkpoint/continuation transaction remain unchanged. No table, migration,
RLS, grant or runtime schema setup is needed. WRITE gains a bounded self-edge;
only a final intermediate draft may transition to the still-unimplemented VERIFY.

The writer will consume a sealed, authorized Step 8 register and use existing
adapters and durable budgets. It will not change analyst behavior, enable a
feature, register a production graph or write DocumentSummary/revision pointers.

Requirement categories are not stored in the existing Requirement contract.
They will be routed deterministically to obligations_conditions without inferred
classification. Original requirements, dependencies, aliases and evidence remain
available through the pinned register. Inclusion manifests measure references in
final prose, separately from retention of the complete structured register.

Independent semantic verification, numerical relationship checks, quality
decisions, writer/evidence repair and publication remain Steps 10–11.
