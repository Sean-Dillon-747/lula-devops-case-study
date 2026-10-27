# DevOps / Platform Engineer — Case Study (starter)

This repo gives you a running start so you can spend your ~3 hours on the **platform work**, not scaffolding.

## What's provided
- `app/` — a trivial Python (FastAPI) orders API. **This is not what we're assessing** — extend or replace it freely.
- `schema.sql` — the baseline `orders` table, pre-seeded. **Your migration evolves this.**
- `docker-compose.yml` — Postgres, pre-wired and seeded. You add the `app` service once you've written the Dockerfile.
- `Dockerfile` — a bare stub to harden.
- `migrations/` — where your migration goes (**the centrepiece** — read that README).
- `.github/workflows/ci.yml` — a skeleton pipeline to fill in.
- `terraform/` — a skeleton for the IaC task (`terraform validate` only; read that README).

## What you build
The containerisation, the CI/CD pipeline, **the safe schema migration (priority)**, the observability, and a small **Terraform** (IaC) sketch — see the brief below.

## How to run
```bash
docker compose up        # brings up Postgres (and your app, once added)
```
The API needs `DB_URL` (default `postgresql://app:app@localhost:5432/app`).

---

# Case Study: DevOps / Platform Engineer

**Overview**

Well done on getting through to our case study interview! This role is the platform seat in Lula's R&D pod — a small team that ships fast into production. The most common failure point when we move quickly isn't the idea or the code, it's operational reality: broken deployments, environment drift, unsafe database changes, infrastructure that blocks promotion to production. This role owns that path — from what the pod builds to what the business can safely run.

This case study is a hands-on preview of exactly that: take a service from "runs on my machine" to "safe to run in production" — containerised, deployed through a pipeline, with a database change shipped safely, and enough observability to diagnose it when it breaks. We care about **judgment and ownership**, not a polished product.

**Objectives**

*Part 1 — Build (~3 hours).* The app is deliberately trivial; the platform work is the point. **The safe schema migration is the centrepiece — get that right first.** The container, pipeline and observability need only be good enough to demonstrate your approach; we'd rather see a solid, well-reasoned migration than four half-finished pieces.

- **Containerise the app** — a lean, multi-stage, non-root Dockerfile, and add your `app` service to `docker-compose.yml` so `docker compose up` runs the whole thing.
- **A CI/CD pipeline** (GitHub Actions — runs on your repo's free runners when you push, no cloud account needed) that builds the image, runs tests, **and runs the database migration** against the **ephemeral Postgres service container** in the CI job. That CI run *is* the "deploy" target — nothing goes to a real cloud.
- **The schema migration (the heart of it).** Evolve the baseline `orders` table with a change that's **safe under live traffic**: backwards-compatible, **expand/contract**, reversible. Then handle the **mid-run-failure path** — if it half-applies, how do you detect what actually ran and recover? (Restoring from a backup is not the answer we're after.)
- **Observability.** Instrument the service with at least one **metric** and **structured logs** (a **trace** is a bonus), and decide **one alert you'd set and why** — and one you'd *not* set because it'd be noise.
- **Infrastructure as Code (Terraform).** Express the service's Azure footprint (compute + Azure SQL/Postgres + Key Vault) as Terraform - we're reading your **HCL structure, module/variable boundaries, and state/secrets reasoning**. `terraform validate` only, no cloud account (CI runs `fmt` + `validate`). **Secondary to the migration** - small and well-reasoned beats broad. See `terraform/README.md`.

*Part 2 — Present & defend (in the session).* Walk us through what you built and **why**: the migration-safety decisions, the mid-run-failure playbook, how you'd map it to **Azure** for real (AKS / Container Apps, Azure SQL, Azure DevOps, Key Vault - your Terraform makes a start on this), and **how you used AI tools** — what you accepted and what you overrode. Expect a live technical deep-dive.

**Instructions**

- ~3 hours from your first commit. Commit regularly — we read the history. If you run short, prioritise the migration and note what you'd have done next.
- **Use AI tools** (Cursor, Claude, Copilot) — we expect it and want to see how you work with them.
- **Submit** your GitHub repo link **24 hours before** your session. Please make the repo **public for the review** (you're welcome to set it back to private afterwards), plus a short **screen recording (5-10 min)** walking through what you built, the migration-safety decisions, and how you used AI.

We look forward to discussing your response. Good luck, and please reach out to your Talent Partner, Andrea (andrea.louw@lula.co.za), should you have any questions.
