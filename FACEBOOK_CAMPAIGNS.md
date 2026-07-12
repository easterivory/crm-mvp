# Facebook campaigns and landing gateway

## Runtime model

- A plain tracking link remains a direct Telegram deep-link.
- A Facebook campaign owns a dedicated `TrackingLink` and a `ProjectLander`.
- The lander embeds the same Telegram start payload that a plain tracking link uses, so bot, buyer, UTM attribution, and the optional funnel step are preserved.
- `page_view` and `telegram_click` are browser Pixel events.
- `bot_start` and `contact` are automatic server CAPI events.
- Funnel-driven sources are emitted by the `send_fb_event` CRM action.
- CAPI delivery is asynchronous through ARQ and uses a stable `event_id` for retry safety.

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

A custom advertising subdomain should use a CNAME to `lp.sfera.cyou`. Add that exact hostname under CRM domain parking and select it when creating the campaign.

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
7. Review the event map. `Purchase` supports `value` and `currency`.
8. Open the public URL with test UTM values and confirm the resulting lead contains attribution and Facebook context.

Secrets are write-only: the API only returns `has_fb_capi_token` and `has_fb_proxy` flags.
