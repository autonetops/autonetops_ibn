# prod

Same composition as `../lab`, with:

- backend prefix `env/prod`
- project `<org>-ibn-prod` (deletion policy PREVENT, cluster deletion
  protection on — both already keyed off `environment = "prod"` in modules)
- chart versions promoted from staging only
- Infrahub treated as tier-0: backup/restore runbook
  (`docs/runbooks/infrahub-recovery.md`) must exist before first prod apply

Created deliberately empty until staging is live.
