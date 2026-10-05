# Multi-Tenancy

```text
Platform
 |-- Tenant A: users, agents, leads, calls, memory, knowledge
 |-- Tenant B: users, agents, leads, calls, memory, knowledge
```

Tenant identity comes from authenticated server context. Queries, cache keys, vector retrieval, object storage and background jobs must carry tenant scope.

A user from Tenant A must never retrieve, mutate, search or infer Tenant B data through APIs, workers, caches, vectors or files.
