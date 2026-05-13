# RouteGuard-Med architecture

RouteGuard-Med adds an agent-routing and evaluation layer to AIMD Sentinel.

```mermaid
flowchart TD
    A[User regulatory or clinical-governance question] --> B{Router}
    B -->|Answer| C[Grounded answer generator]
    B -->|Retrieve| D[Hybrid retrieval]
    B -->|Clarify| E[Clarification response]
    B -->|Abstain| F[Abstention response]
    B -->|Escalate| G[Human review queue]
    D --> H[Evidence snippets with source IDs]
    H --> B2{Second-pass router}
    B2 --> C
    C --> I[Source-cited response]
    I --> J[Evaluation]
    E --> J
    F --> J
    G --> J
```

## Five-action routing policy

| Action | Regulated AI meaning |
|---|---|
| Answer | Evidence is sufficient and the query is low-risk. |
| Retrieve | Evidence is needed before a grounded answer. |
| Clarify | Device/manufacturer/version or intent is missing. |
| Abstain | Public evidence cannot support the requested claim. |
| Escalate | Human review required due to clinical, legal, safety, or adversarial risk. |

## Evidence rule

Generated factual claims should be tied to retrieved source IDs. Weak matches are treated as review-only.
