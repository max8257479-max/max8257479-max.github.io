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
