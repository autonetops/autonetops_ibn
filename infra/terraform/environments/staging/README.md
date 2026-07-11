# staging

Same composition as `../lab` (copy its `*.tf` when promoting), with:

- backend prefix `env/staging`
- project `<org>-ibn-staging`
- chart versions promoted from lab after soak
- monthly budget raised, deletion policy still permissive

Created deliberately empty until the lab environment has had its first
successful apply — no speculative copies to keep in sync.
