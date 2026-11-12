# Sprint 3 demo

## Private network setup

Connect server S and POS machines A and B to the private router. Configure a static private IP on S, and set the Windows network profile on S to Private. Do not expose the services to the public Internet.

On S, set `POS_BIND_ADDRESS` and `MIDDLEWARE_BIND_ADDRESS` in `.env` to S's private IP. Both default to `127.0.0.1` when unset. In Git Bash, run `EXTRA_SANS=IP:<server-ip> bash scripts/generate_dev_certs.sh`, then restart middleware and pos-gateway so they load the new server certificate. Run `scripts/demo/open_firewall.ps1` as administrator on S; `close_firewall.ps1` removes the rules after the demo.

Publish the Demo POS and copy it to A and B. Copy `.certs/ca.crt`, the appropriate terminal certificate and private key, and the required demo tokens to their configured paths on each POS machine. Keep private keys and tokens private. Configure `appsettings.Local.json` beside the executable with `PosBaseUrl` set to `https://<server-ip>:9443/api/v1` and `MonitorBaseUrl` to `https://<server-ip>:8443/api/v1`; configure the asset paths and terminal list for that machine. The IP must match the server certificate SAN. Verify health and a sale from each machine before the demo.
