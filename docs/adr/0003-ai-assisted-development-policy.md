# ADR 0003: AI-assisted development policy

## Status

Accepted

## Context

AI coding agents are a normal part of the developer's workflow and make an ambitious solo project feasible. The principal risk is not use of AI itself; it is accepting code, statistical choices, or football definitions that the developer cannot validate or explain. The project must demonstrate accountable engineering rather than typing volume.

## Decision

Use AI agents for implementation proposals, boilerplate, repetitive mappings, test scaffolds, refactoring suggestions, and documentation assistance. For every important feature, follow this evidence trail:

1. human-written problem definition;
2. inputs, outputs, constraints, and success criteria;
3. recorded architecture/research decision where material;
4. agent-proposed implementation;
5. critical human review;
6. improved behavioural tests;
7. validation run and inspected outputs;
8. at least one meaningful manual modification;
9. documented limitations and trade-offs;
10. a human teach-back without the agent.

Core learning components identified in each phase must be implemented or substantially rewritten manually. AI-generated code is not accepted because it compiles or because an agent says it is correct.

## Alternatives considered

- **Avoid AI entirely:** rejected because it does not match the intended working style and would reduce achievable end-to-end scope.
- **Unrestricted agent implementation:** rejected because it creates unowned methodology, weak interview readiness, and hidden correctness risks.
- **Require fixed percentages of manual code:** rejected because line counts do not measure understanding or responsibility.

## Consequences

- Development can remain fast while producing review and learning evidence.
- Important tasks include extra time for test design, manual changes, and explanation.
- Prompts and agent output need not all be committed, but decisions and limitations must be.
- If the developer cannot explain a core path, that feature is not done even when tests pass.

## Review trigger

Review if the workflow repeatedly blocks delivery without improving understanding, if AI-related defects escape validation, or if employer/interview evidence suggests a different proof of ownership is needed. The accountability requirement remains even if tools change.

