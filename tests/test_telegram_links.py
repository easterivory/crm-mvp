import unittest

from app.core.telegram_links import (
    build_telegram_bot_start_link,
    canonicalize_telegram_web_link,
)


class TelegramLinkCompatibilityTests(unittest.TestCase):
    def test_new_start_links_use_browser_safe_host(self) -> None:
        self.assertEqual(
            build_telegram_bot_start_link("@sample_bot", "ref_campaign-1"),
            "https://telegram.me/sample_bot?start=ref_campaign-1",
        )

    def test_legacy_host_is_replaced_without_changing_path_or_query(self) -> None:
        legacy = "https://t.me/SampleBot/path?start=ref_a%2Fb&mode=compact#section"

        self.assertEqual(
            canonicalize_telegram_web_link(legacy),
            "https://telegram.me/SampleBot/path?start=ref_a%2Fb&mode=compact#section",
        )

    def test_scheme_less_legacy_link_is_supported(self) -> None:
        self.assertEqual(
            canonicalize_telegram_web_link("t.me/SampleBot?start=legacy"),
            "https://telegram.me/SampleBot?start=legacy",
        )

    def test_telegram_uri_and_custom_url_are_not_modified(self) -> None:
        self.assertEqual(
            canonicalize_telegram_web_link(
                "tg://resolve?domain=SampleBot&start=legacy"
            ),
            "tg://resolve?domain=SampleBot&start=legacy",
        )
        self.assertEqual(
            canonicalize_telegram_web_link("https://example.com/redirect?start=legacy"),
            "https://example.com/redirect?start=legacy",
        )


if __name__ == "__main__":
    unittest.main()
