"""
Regression test for the Alpaca/Benzinga news-check bug:
scanner_service.check_alpaca_news() was silently returning has_news=False
for EVERY symbol because it accessed a `.news` attribute the alpaca-py
NewsSet model doesn't expose (real articles live under `.data['news']`).
This forced 100% reliance on the slower Google News fallback with zero
errors logged. Fixed by reading `news_set.data['news']` instead.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()

from services.scanner_service import scanner_service


class TestAlpacaNewsAccess:
    def test_news_client_configured(self):
        from services.alpaca_service import news_pool
        assert news_pool.configured_count > 0, (
            "Alpaca news_pool not configured - ALPACA_DATA_API_KEY/SECRET missing"
        )

    def test_check_alpaca_news_returns_correct_shape(self):
        """Regardless of whether a symbol has catalyst news right now, the
        call must succeed (no silent attribute-error swallow) and return the
        expected {'has_news': bool, 'articles': list} shape."""
        result = scanner_service.check_alpaca_news("AAPL", hours_back=24, limit=5)
        assert set(result.keys()) == {"has_news", "articles"}
        assert isinstance(result["has_news"], bool)
        assert isinstance(result["articles"], list)

    def test_alpaca_news_finds_a_real_strong_catalyst_headline(self):
        """
        Pull a batch of real, current Alpaca/Benzinga headlines, find one
        that legitimately scores as a strong catalyst (e.g. "acquisition",
        "takeover"), then confirm check_alpaca_news() for that exact symbol
        reports has_news=True via the Alpaca path. This is the definitive
        regression check: before the fix, this ALWAYS returned False no
        matter what real data Alpaca had.
        """
        import requests
        from services.google_news_service import score_headline

        api_key = os.getenv("ALPACA_DATA_API_KEY")
        secret_key = os.getenv("ALPACA_DATA_SECRET_KEY")
        headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
        r = requests.get(
            "https://data.alpaca.markets/v1beta1/news",
            headers=headers,
            params={"limit": 50},
            timeout=15,
        )
        assert r.status_code == 200
        news_items = r.json().get("news", [])

        catalyst_symbol = None
        for item in news_items:
            if score_headline(item["headline"]) and item.get("symbols"):
                catalyst_symbol = item["symbols"][0]
                break

        if not catalyst_symbol:
            pytest.skip("No strong-catalyst headline in the current live feed to test against")

        result = scanner_service.check_alpaca_news(catalyst_symbol, hours_back=24, limit=5)
        assert result["has_news"] is True, (
            f"Expected {catalyst_symbol} to have news via the Alpaca path "
            f"(real catalyst headline confirmed in raw feed) - got: {result}"
        )
        assert len(result["articles"]) > 0
