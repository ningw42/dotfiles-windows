---
name: traceability
description: Hold a conversion or review to two principles — completeness and consistency — between a source and its outputs.
disable-model-invocation: true
---

# Traceability

Two principles govern any faithful transformation from a source to derived outputs: **completeness** — nothing in the source is lost — and **consistency** — nothing in the outputs departs from the source. Honor both in the mode you are running:

- **Review** — the outputs already exist. Run completeness and consistency as two more **axes** of the review: spawn one subagent per axis, each running its axis under Build bidirectional traceability below against the complete source and output sets, alongside whatever axes the primary review skill already spawns. The main agent then aggregates the axes into the report below and summarizes as the primary review skill usually does.
- **Conversion** — you produce the outputs from the source: reformat one document into another, or break one document into many items. Honor both principles while producing, then verify your own output the same way.

When a primary skill drives the work (a review skill, a conversion procedure), apply this as its authoritative addendum. Preserve every non-conflicting part of it; where instructions conflict, follow this skill. The primary's scope, filters, taxonomies, and word limits do not suppress findings required here.

Hand each review subagent this skill, the complete source and output sets, and the reporting requirements below. The main agent — the coordinator — remains responsible for the completion criterion however the axes run.

## Fix the two input sets

Name both sets before starting:

- **Source** is the authority for the expected result — the document(s) reviewed against or converted from. Use them complete, including applicable linked material, conditions, and exceptions.
- **Outputs** are everything derived from the source: the artifacts under review, or the converted document and broken-down items. Treat documents, plans, designs, configurations, generated output, and source code uniformly as inspectable evidence.

Use explicit precedence rules within the source set. Where two sources conflict without a precedence rule, report the source conflict and continue with every unaffected requirement.

## Build bidirectional traceability

### Completeness: source to output

1. Extract every independently verifiable **ask** from the entire source set. Include required outcomes, constraints, acceptance criteria, invariants, prohibitions, conditional cases, and exceptions; retain a precise source citation for each.
2. Trace each ask to exact evidence anywhere in the output set. When the outputs are many items, a single item carrying the ask satisfies it.
3. Mark each ask `complete`, `partial`, `missing`, or `unverifiable`. Accept `complete` only when inspectable evidence covers the whole ask, including its conditions and exceptions.
4. Report every `partial`, `missing`, and `unverifiable` ask. Group findings only when every underlying ask and citation remains explicit.

### Consistency: output to source

1. Check every material claim, decision, value, definition, behavior, boundary, and condition in the output set against every applicable statement in the source set.
2. Report direct contradictions and semantic conflicts, including incompatibly changed scope or conditions, incompatible terminology or values, and claims of compliance unsupported by the outputs.
3. Treat additional output content as consistent when it is compatible with the complete source set; leave questions of unrequested scope to the primary skill.

## Report

Keep any primary output and add separate `Completeness` and `Consistency` sections. For each finding, provide:

- the source citation and the requirement or statement it establishes;
- the output citation, or the locations examined when evidence is absent;
- the precise gap or conflict and the correction required.

When a principle holds, say so with the evidence count: completeness reports covered asks over total asks; consistency reports outputs checked and zero conflicts. List unresolved source conflicts or ambiguities separately from output defects.

The work is complete only when every source document and output is accounted for, every ask has a status and evidence, every material output statement has been checked against all applicable sources, and every non-passing result has been reported. Complete all non-conflicting requirements of any primary skill as well.
