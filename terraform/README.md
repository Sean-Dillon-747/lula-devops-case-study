# Infrastructure as Code (Terraform)

Secondary to the migration - but it's how this seat is judged beyond app-layer DevOps:
can you *author* infrastructure, not just operate a platform someone else built.

**The task:** express the service's **Azure footprint** as Terraform - the compute to run the
container, a managed **Azure SQL / Postgres**, and **Key Vault** for secrets. We're reading your
**HCL structure, module/variable boundaries, and how you reason about state and secrets** - not a
running environment.

- **`terraform validate` only.** No Azure account, no `apply`. CI runs `terraform fmt -check` and
  `terraform validate` for you (see `.github/workflows/ci.yml`).
- Keep it **small and well-reasoned** - one or two resources wired correctly, with variables and a
  clear state/secrets story, beats a broad half-built sketch.
- Be ready to **defend it live** alongside your Azure mapping in Part 2.
