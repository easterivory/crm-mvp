"""CRM event dispatcher; existing direct Facebook API contracts stay unchanged."""
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.tiktok_event_service import TikTokEventService


class AdvertisingEventService(FacebookCampaignService):
    async def enqueue_mapped_event(self, **kwargs):
        await TikTokEventService(self.db).mapped_event(**kwargs)
        return await super().enqueue_mapped_event(**kwargs)

    async def enqueue_triggered_events(self, **kwargs):
        await TikTokEventService(self.db).triggered_event(**kwargs)
        return await super().enqueue_triggered_events(**kwargs)
