# Security and deployment

This repository is a local reference implementation, not a multi-tenant
service. Its demo API deliberately has no authentication, authorization,
rate-limit, or durable database. Do not expose it directly to the public
internet.

Before adapting it for real users:

- authenticate both room controls and chat turns;
- authorize membership per room before reading lyrics, playback state, or
  singing-session status;
- set a precise production `CORS_ORIGINS` value and serve it over HTTPS;
- add request-size limits, rate limits, and abuse monitoring;
- replace in-memory session retention with an explicitly documented retention
  policy;
- keep raw audio out of the pitch-sharing path unless a separate product design
  has explicit consent, access control, deletion, and threat-model review;
- use a secret manager and keep credentials outside the repository.

Please report vulnerabilities privately to the maintainer of the fork you are
using. Do not include credentials, recordings, account data, or private URLs
in a public issue.
