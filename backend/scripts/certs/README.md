# Supabase DB CA

`supabase-prod-ca-2021.crt` is the public CA certificate linked by the production
project dashboard's Database Settings → SSL configuration → Download certificate.
It contains no private key or credentials.

Source: https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt
Retrieved: 2026-10-30

The TLS diagnostic loads this CA in addition to system roots. It still requires
certificate-chain and hostname verification. Update it when Supabase rotates the
CA, after verifying the replacement against the dashboard's official link.
This file does not change Network Restrictions or the CLI container's SSL policy.
