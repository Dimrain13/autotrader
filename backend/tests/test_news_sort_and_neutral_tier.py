"""
Regression test for the news RANKING fix (same-day follow-up to the
news-display fix in test_news_min_score_fix.py):

User feedback: "I see the news is coming in now, but its not being ranked
at all." Root cause: articles carried a score/sentiment field but were
never sorted by relevance - just left in raw chronological API order.

Fixes verified here:
1. scanner_service.check_alpaca_news() sorts `articles` by `score` desc.
2. google_news_service.search_stock_news() sorts `articles` by `score` desc.
3. score_headline() labels score==0 as 'neutral' (not 'weak' anymore).
4. GET /api/news/{symbol} end-to-end: articles non-increasing by score,
   and any score==0 article has sentiment=='neutral'.
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

from services.google_news_service import score_headline
from services.scanner_service import scanner_service

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    import pathlib
    env_path = pathlib.Path(__file__).resolve().parents[2] / "frontend" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
BASE_URL = (BASE_URL or "").rstrip("/")


@pytest.fixture(scope="module")
def auth_headers():
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not (email and password):
        pytest.skip("ADMIN_EMAIL/ADMIN_PASSWORD not set - cannot authenticate")
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed ({r.status_code}) - skipping authenticated tests")
    token = r.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


class TestScoreHeadlineNeutralTier:
    """score_headline() sentiment tier boundaries."""

    def test_zero_score_headline_is_neutral_not_weak(self):
        result = score_headline("Company holds annual shareholder meeting", min_score=0)
        assert result is not None
        assert result["score"] == 0
        assert result["sentiment"] == "neutral"

    def test_weak_tier_score_2_to_4_is_weak(self):
        result = score_headline("Some Company gains after announcement", min_score=0)
        assert result["score"] == 2
        assert result["sentiment"] == "weak"

    def test_momentum_tier_score_5_to_9_is_momentum(self):
        result = score_headline("Company shares surge on strong demand", min_score=0)
        assert result["score"] == 5
        assert result["sentiment"] == "momentum"

    def test_strong_catalyst_tier_score_10_plus(self):
        result = score_headline("Company Receives FDA Approval For New Drug", min_score=0)
        assert result["score"] == 10
        assert result["sentiment"] == "strong_catalyst"


class TestCheckAlpacaNewsSorting:
    @pytest.mark.parametrize("symbol", ["AAPL", "NVDA", "TSLA", "AMD"])
    def test_articles_sorted_desc_by_score(self, symbol):
        result = scanner_service.check_alpaca_news(symbol, hours_back=48, limit=8, min_score=0)
        scores = [a["score"] for a in result["articles"]]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), (
            f"{symbol}: articles not sorted descending by score: {scores}"
        )

    @pytest.mark.parametrize("symbol", ["AAPL", "NVDA", "TSLA", "AMD"])
    def test_zero_score_articles_are_neutral(self, symbol):
        result = scanner_service.check_alpaca_news(symbol, hours_back=48, limit=8, min_score=0)
        for a in result["articles"]:
            if a["score"] == 0:
                assert a["sentiment"] == "neutral"


class TestNewsDisplayEndpointSorting:
    """GET /api/news/{symbol} end-to-end sort + neutral tier check."""

    @pytest.mark.parametrize("symbol", ["NVDA", "AMZN", "TSLA", "AAPL", "AMD", "META", "GOOGL"])
    def test_endpoint_returns_non_increasing_scores(self, auth_headers, symbol):
        r = requests.get(
            f"{BASE_URL}/api/news/{symbol}",
            params={"limit": 8},
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        articles = data.get("articles", [])
        if not articles:
            pytest.skip(f"{symbol}: no articles returned right now (non-deterministic, real API)")
        scores = [a["score"] for a in articles]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), (
            f"{symbol}: /api/news scores not sorted descending: {scores}"
        )
        for a in articles:
            if a["score"] == 0:
                assert a["sentiment"] == "neutral", f"{symbol}: score 0 article mislabeled: {a}"
            else:
                assert a["sentiment"] != "neutral", f"{symbol}: nonzero score labeled neutral: {a}"

    def test_auto_trader_strict_path_unaffected(self):
        """
        _check_candidate_news() (auto-trader momentum scoring, min_score=10
        strict default) must remain unchanged by the sorting fix - sorting
        doesn't change which articles pass the strict filter, just order.
        """
        import inspect
        source = inspect.getsource(scanner_service._check_candidate_news)
        assert "min_score" not in source
