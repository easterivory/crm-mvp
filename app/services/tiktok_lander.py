import json
from uuid import UUID

from app.services.tiktok_event_service import static_tiktok_parameters, tiktok_event_id


def render_tiktok_pixel(pixel_id: str, mappings: list[dict], bridge_url: str, start_key: str, link_id: UUID) -> str:
    config = json.dumps({"pixel": pixel_id, "bridge": bridge_url,
                         "events": {m["source_event"]: {"name": m["event_name"], "params": static_tiktok_parameters(m.get("parameters", {})), "id": tiktok_event_id(link_id, m["source_event"], f"browser:{start_key}")}
                                    for m in mappings if m.get("enabled", True) and m["source_event"] in {"page_view", "telegram_click"}}}).replace("<", "\\u003c")
    return (
        "<script>(function(){var c=" + config + ";"
        "!function(w,d,t){w.TiktokAnalyticsObject=t;var q=w[t]=w[t]||[];"
        "q.methods=['page','track','identify','instances','debug','on','off','once','ready','alias','group','enableCookie','disableCookie'];"
        "q.setAndDefer=function(o,m){o[m]=function(){o.push([m].concat(Array.prototype.slice.call(arguments,0)));};};"
        "for(var i=0;i<q.methods.length;i++){q.setAndDefer(q,q.methods[i]);}"
        "q.instance=function(id){var o=q._i[id]||[];for(var j=0;j<q.methods.length;j++){q.setAndDefer(o,q.methods[j]);}return o;};"
        "q.load=function(id,o){q._i=q._i||{};q._i[id]=[];q._i[id]._u='https://analytics.tiktok.com/i18n/pixel/events.js';q._t=q._t||{};q._t[id]=+new Date;q._o=q._o||{};q._o[id]=o||{};"
        "var s=d.createElement('script');s.async=true;s.src='https://analytics.tiktok.com/i18n/pixel/events.js?sdkid='+encodeURIComponent(id)+'&lib='+t;"
        "var f=d.getElementsByTagName('script')[0];f.parentNode.insertBefore(s,f);};q.load(c.pixel);}(window,document,'ttq');"
        "ttq.page();"
        "function pixel(source){var m=c.events[source];if(m){ttq.track(m.name,m.params,{event_id:m.id});}}"
        "function sync(source){var p={crm_tiktok_source:source,event_source_url:location.href};"
        "document.cookie.split(';').forEach(function(v){var a=v.trim().split('=');if(a[0]==='_ttp'){p._ttp=decodeURIComponent(a.slice(1).join('='));}});"
        "fetch(c.bridge,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p),keepalive:true}).catch(function(){});}"
        "pixel('page_view');sync('page_view');"
        "var clicked=false;var previous=window.__crmTrackTelegramOpen;window.__crmTrackTelegramOpen=function(){"
        "if(previous){previous();}if(!clicked){clicked=true;pixel('telegram_click');sync('telegram_click');}};"
        "document.addEventListener('click',function(e){"
        "var a=e.target&&e.target.closest?e.target.closest('a[data-crm-telegram-link]'):null;"
        "if(a){window.__crmTrackTelegramOpen();}},true);"
        "})();</script>"
    )
