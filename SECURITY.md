# Security policy

## Supported version

The actively maintained version is the `main` branch and the GitHub Pages deployment built from it.

## Reporting a vulnerability

Please do not publish exploit details, private route links, or personal data in a public issue.

If GitHub's **Report a vulnerability** option is available in this repository's Security tab, use it to send a private report. If private vulnerability reporting is not enabled, open a minimal issue asking the repository owner for a private reporting channel without including technical exploit details.

## Security design

- The browser app is static and does not authenticate users or store a user account database.
- Browser JavaScript is served from the same origin and restricted by a Content Security Policy.
- The only browser-side network request to a third-party service is the public OSRM route calculation endpoint.
- The tariff updater fetches only HTTPS pages from the allowlisted Hello and CarSync hosts and rejects redirects to other hosts.
- CI uses hash-verified Python wheels, pinned GitHub Actions, read-only validation permissions, and separate update/deploy jobs.
- Tariff changes are proposed as a data-only pull request and are merged automatically only after validation succeeds.

## Repository owner checklist

### Protect the `main` branch

In **Settings → Rules → Rulesets → New branch ruleset**:

1. Name the ruleset `Protect main`, set enforcement to **Active**, and target the `main` branch.
2. Enable **Require a pull request before merging**. Keep required approvals at 0 for a single-maintainer repository; inspect code changes before merging them.
3. Enable **Require status checks to pass before merging** and select the `Validate` check.
4. Enable **Block force pushes**, **Restrict deletions**, and **Require linear history**.
5. Do not add bypass actors. The tariff updater now creates a data-only PR and validates it before merging, so it does not need a direct-push bypass.

### Enable GitHub security features

In **Settings → Code security and analysis**, verify that the dependency graph, Dependabot alerts, and Dependabot security updates are enabled. Enable private vulnerability reporting if available. The repository already contains a Dependabot schedule for weekly package and GitHub Actions update PRs.

### Protect the GitHub account

In the account's **Settings → Password and authentication**, enable two-factor authentication or a passkey. Then review active sessions and revoke any unrecognized sessions; review SSH keys and remove any that are no longer used.
