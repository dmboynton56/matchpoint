# Jordan Kim

San Francisco, CA · jordan.kim@email.example · linkedin.com/in/jordankim-eng · github.com/jkim-arch

---

## Summary

Senior software engineer with 11 years of experience designing and operating distributed systems at scale. Deep backend expertise (Python, Go, PostgreSQL) with strong ownership of reliability, observability, and cross-team technical direction. Interested in staff-level IC roles and platform engineering.

---

## Skills

**Languages:** Python, Go, TypeScript, SQL, Bash

**Systems:** Distributed systems, event-driven architecture, PostgreSQL, Redis, Kafka, gRPC

**Platform:** Kubernetes, AWS (EKS, Lambda, DynamoDB), Terraform, Datadog, PagerDuty

**Practices:** System design, incident response, SLOs/SLIs, technical mentoring, RFC writing

---

## Work Experience

### Senior Software Engineer — Meridian Payments

San Francisco, CA · Mar 2019 – Present

- Tech lead for ledger ingestion platform processing 45M events/day with 99.97% monthly availability.
- Led migration from monolithic Python service to Go microservices; cut p99 latency from 820ms to 190ms.
- Introduced idempotent event processing and dead-letter queues; eliminated duplicate settlement bugs.
- Authored RFCs for multi-region failover; implemented read replicas and automated failover drills.
- Mentored 4 engineers (2 promoted to senior); ran weekly architecture office hours for the org.
- Owned on-call for payments core; reduced MTTR from 47 minutes to 12 minutes over 18 months.
- Partnered with security on PCI scope reduction by isolating cardholder data into a dedicated VPC segment.

### Software Engineer II — Streamline Health

Remote · Aug 2015 – Feb 2019

- Built patient scheduling APIs in Python/Django serving 1.2M appointments annually.
- Designed HIPAA-compliant audit logging and role-based access for clinical staff workflows.
- Optimized slow reporting queries; added materialized views and cut nightly batch window by 3 hours.
- Led brownfield rewrite of notification service from cron jobs to SQS-backed workers.

### Software Engineer — Innotech Labs

Austin, TX · Jul 2013 – Jul 2015

- Full-stack development on B2B SaaS dashboard (AngularJS, Python, MySQL).
- Implemented SSO integration (SAML) for enterprise customers.

---

## Projects

**OpenMetrics Kit** — Lightweight SLO dashboard templates (Go, Prometheus) — 420 GitHub stars

- Talk at regional SRE meetup (2023): "SLOs without the enterprise tax."

---

## Education

**B.S. Computer Science** — University of Texas at Austin · 2013

**Certifications:** AWS Solutions Architect – Associate (2021, renewed 2024)
