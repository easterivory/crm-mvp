# Facebook campaigns and landing gateway

## Runtime model

- A plain tracking link remains a direct Telegram deep-link.
- A Facebook campaign owns a dedicated `TrackingLink` and a `ProjectLander`.
- The lander embeds the same Telegram start payload that a plain tracking link uses, so bot, buyer, UTM attribution, and the optional funnel step are preserved.
- `page_view` and `telegram_click` are browser Pixel events.
- `bot_start` and `contact` are automatic server CAPI events.
- Server event mappings have explicit OR trigger rules: `funnel_action`,
  `lead_status`, and `lead_tag`.
- Existing mappings without a `triggers` field keep the legacy
  `funnel_action` behavior.
- A `lead_status` rule fires only when the lead actually moves to the selected
  status. A `lead_tag` rule fires only when the selected tag is newly attached.
- Registration and first/repeat deposit events can therefore be driven by CRM
  tags even when those actions happen outside the funnel.
- CAPI delivery is asynchronous through ARQ and uses a stable `event_id` for retry safety.
- When several rules for one source event match in the same lead lifecycle,
  they share the same stable event identity to prevent duplicate Meta events.

## Required environment

```dotenv
LANDER_TECH_DOMAIN=lp.sfera.cyou
FACEBOOK_GRAPH_API_VERSION=v25.0
```

Run the database migration before serving the new UI:

```bash
alembic upgrade head
```

## `lp.sfera.cyou`

The technical domain can be used directly:

```text
https://lp.sfera.cyou/l/<slug>
```

For BunnyCDN, add each advertising subdomain under `Hostnames` of the same Pull
Zone that already serves `lp.sfera.cyou`, point its DNS CNAME to the
Bunny-provided `*.b-cdn.net` hostname, and enable SSL. Do not use
`lp.sfera.cyou` as the Origin URL of another Pull Zone and do not add redirect
rules between the technical and advertising hostnames. The Pull Zone must keep
the real application origin. Add the advertising hostname under CRM domain
parking and select it in the campaign editor.

The CDN or reverse proxy must:

1. Preserve the visitor-facing `Host` header at the origin.
2. Forward `X-Forwarded-For` and `X-Forwarded-Proto`.
3. Bypass cache for `/l/*`, including HTML and `/l/<slug>/bridge/*`.
4. Respect `Cache-Control`, `CDN-Cache-Control`, and `Surrogate-Control` from the origin.
5. Route all `/l/*` requests to the FastAPI application.

Example origin proxy rules:

```nginx
location ^~ /l/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    add_header Cache-Control "no-store" always;
}
```

After deploy, purge the CDN cache for `/` and `/l/*`. The technical root must return `Landing gateway is ready.`, while an unknown `/l/<slug>` must return 404.

## Campaign checklist

1. Create the campaign in `Settings -> Landers and Domains`.
2. Select the Telegram bot and the optional target funnel step.
3. Use the technical domain directly or select a parked advertising domain.
4. Enter Pixel / Dataset ID and CAPI access token.
5. Add a proxy only when Meta traffic must leave through that proxy.
6. Use Test event code during Events Manager verification, then clear it for normal traffic.
7. Review the event map. Automatic rows explain their fixed runtime trigger.
8. For each server event, add one or more OR rules: funnel action, target lead
   status, or newly added project tag. `Purchase` supports `value` and `currency`.
9. Open the public URL with test UTM values and confirm the resulting lead contains attribution and Facebook context.

Generated Facebook campaign URLs always include visible defaults for
`utm_source`, `utm_medium`, and `utm_campaign`. Values configured in CRM replace
those defaults.

Secrets are write-only: the API only returns `has_fb_capi_token` and `has_fb_proxy` flags.
