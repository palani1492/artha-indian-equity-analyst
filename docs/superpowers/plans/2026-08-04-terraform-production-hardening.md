# Terraform Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden existing Terraform WAF and RDS defaults for production readiness without adding services, changing application behavior, or applying AWS changes.

**Architecture:** Keep the existing regional WAF and RDS resources. Add a regex pattern set for a configurable narrow mutation-path list, retain OAuth as its own exact-path rate rule, and use non-replacement RDS safety defaults. Document inputs and verify locally with Terraform formatting, validation, and native tests when available.

**Tech Stack:** Terraform >= 1.7, AWS provider ~> 5.80, AWS WAFv2, Amazon RDS.

## Global Constraints

- Do not add services or change application code.
- Do not run `terraform apply` or make AWS changes.
- Preserve existing resource identifiers and avoid forced destructive changes.
- Keep the OAuth WAF rule.
- Use only the requested narrow mutation paths.

---

### Task 1: Add WAF rate-based protections

**Files:**
- Modify: `infra/waf.tf`
- Modify: `infra/variables.tf`

- [ ] Add `chat_rate_limit`, `mutation_api_rate_limit`, and `mutation_api_path_patterns` variables with descriptions, safe defaults, minimum validations, and regex-pattern documentation. Defaults must cover `/api/v1/chat`, `/api/v1/refresh`, `/api/v1/stocks/`, `/api/v1/persona`, `/api/v1/notes`, and `/api/v1/conversations`; the stocks pattern must include descendants.
- [ ] Add an `aws_wafv2_regex_pattern_set` containing the configured regex strings.
- [ ] Add separate IP-aggregated block rules for exact chat and the regex-backed mutation paths, with unique priorities and CloudWatch metrics.
- [ ] Keep the existing OAuth callback rule unchanged except for priority renumbering if required.

### Task 2: Harden RDS defaults safely

**Files:**
- Modify: `infra/database.tf`
- Modify: `infra/variables.tf`

- [ ] Change the backup retention default to a production baseline and validate it within AWS's supported range.
- [ ] Default deletion protection to enabled.
- [ ] Default `skip_final_snapshot` to false and set a stable, identifier-derived `final_snapshot_identifier` that does not replace the existing instance.
- [ ] Preserve the existing RDS identifier, engine, storage, subnet group, and lifecycle structure.

### Task 3: Document examples and Terraform tests

**Files:**
- Modify: `infra/terraform.tfvars.example`
- Modify: `infra/README.md`
- Create: `infra/tests/production_hardening.tftest.hcl` if native Terraform test support works with the installed Terraform/provider.

- [ ] Document all new and changed WAF/RDS variables with example values and explain the WAF regex semantics.
- [ ] Add native Terraform assertions for the default WAF paths/rules and RDS safety defaults where mock planning is supported.
- [ ] If native tests cannot plan in this repository, record the exact limitation and rely on validation plus `terraform fmt` and `terraform validate`; do not add a fake or non-executed test.

### Task 4: Verify locally

**Files:**
- No additional files.

- [ ] Run `terraform -chdir=infra fmt -check -recursive` and format only Terraform files if needed.
- [ ] Run `terraform -chdir=infra validate` after initialization is already available; do not apply.
- [ ] Run `terraform -chdir=infra test` if the test file is added and the command is supported.
- [ ] Inspect `git diff` and confirm no application files, deployment execution, secrets, or unrelated changes were introduced.
