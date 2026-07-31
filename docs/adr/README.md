# Architecture Decision Records

ADRs capture decisions that are expensive to reverse, affect several modules, or add a technology/process to the project. They are short evidence of engineering judgment, not a diary of every implementation choice.

## Format

Each ADR contains:

- **Status:** Proposed, Accepted, Superseded, or Rejected
- **Context:** the observed problem and constraints
- **Decision:** what will be done
- **Alternatives considered:** credible options, including continuing the current approach
- **Consequences:** benefits, costs, and risks
- **Review trigger:** evidence or a date that should reopen the decision

Name records `NNNN-short-title.md`. Do not rewrite an accepted decision to hide history. Add a superseding ADR and link both records. A pull request or commit that changes architecture should add or update the relevant ADR and documentation in the same change.

## Decision test for new technology

An ADR proposing a new tool must answer:

1. Which existing, observed problem does it solve?
2. Why is the current solution insufficient?
3. What new complexity, failure modes, and maintenance does it add?
4. What learning or portfolio value justifies that cost?

“Industry standard,” “might scale,” and “useful on a CV” are not sufficient evidence.

## Index

- [0001 — Monorepo architecture](0001-monorepo-architecture.md)
- [0002 — PostgreSQL as primary database](0002-postgresql-as-primary-database.md)
- [0003 — AI-assisted development policy](0003-ai-assisted-development-policy.md)

