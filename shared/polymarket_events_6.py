import pytest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta
import json

from polymarket_events_4 import (
    search_short_duration_markets,
    search_all_events_paginated,
    find_by_specific_slugs,
)


class TestSearchShortDurationMarkets:
    """Tests for search_short_duration_markets function"""

    @patch('polymarket_events_4.requests.get')  # Changed from 'shared.polymarket_events_4.requests.get'
    def test_returns_markets_ending_soon(self, mock_get):
        """Should return markets that end within 24 hours"""
        mock_markets = [
            {
                'question': 'Bitcoin up or down at 6pm?',
                'endDate': (datetime.utcnow() + timedelta(hours=2)).isoformat() + 'Z',
                'clobTokenIds': json.dumps(['1766273344050', '1766273344051']),
            },
            {
                'question': 'ETH above $4000?',
                'endDate': (datetime.utcnow() + timedelta(hours=5)).isoformat() + 'Z',
                'clobTokenIds': '["123456", "789012"]',
            },
        ]
        mock_get.return_value = Mock(json=Mock(return_value=mock_markets))

        result = search_short_duration_markets()

        assert len(result) == 2
        assert result[0]['question'] == 'Bitcoin up or down at 6pm?'
        mock_get.assert_called_once()

    @patch('polymarket_events_4.requests.get')
    def test_handles_empty_response(self, mock_get):
        """Should handle empty market list gracefully"""
        mock_get.return_value = Mock(json=Mock(return_value=[]))

        result = search_short_duration_markets()

        assert result == []

    @patch('polymarket_events_4.requests.get')
    def test_handles_missing_clob_token_ids(self, mock_get):
        """Should handle markets without clobTokenIds"""
        mock_markets = [
            {
                'question': 'Some market',
                'endDate': (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z',
            },
        ]
        mock_get.return_value = Mock(json=Mock(return_value=mock_markets))

        result = search_short_duration_markets()

        assert len(result) == 1

    @patch('polymarket_events_4.requests.get')
    def test_handles_list_clob_token_ids(self, mock_get):
        """Should handle clobTokenIds as list (not JSON string)"""
        mock_markets = [
            {
                'question': 'Market with list tokens',
                'endDate': (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z',
                'clobTokenIds': ['token1', 'token2'],
            },
        ]
        mock_get.return_value = Mock(json=Mock(return_value=mock_markets))

        result = search_short_duration_markets()

        assert len(result) == 1


class TestSearchAllEventsPaginated:
    """Tests for search_all_events_paginated function"""

    @patch('polymarket_events_4.requests.get')
    def test_finds_events_with_hourly_keywords(self, mock_get):
        """Should find events containing hourly/time keywords"""
        mock_events = [
            {
                'title': 'Bitcoin Up or Down 6pm ET',
                'slug': 'bitcoin-up-or-down-december-20-6pm-et',
                'markets': [{'question': 'Will BTC be up?'}],
            },
        ]
        mock_get.side_effect = [
            Mock(json=Mock(return_value=mock_events)),
            Mock(json=Mock(return_value=[])),
        ]

        result = search_all_events_paginated()

        assert len(result) >= 1

    @patch('polymarket_events_4.requests.get')
    def test_finds_bitcoin_markets_ending_soon(self, mock_get):
        """Should identify Bitcoin markets with short duration"""
        end_time = (datetime.utcnow() + timedelta(hours=2)).isoformat() + 'Z'
        mock_events = [
            {
                'title': 'Bitcoin Price Prediction',
                'slug': 'btc-price',
                'markets': [
                    {
                        'question': 'BTC above 100k?',
                        'endDate': end_time,
                        'clobTokenIds': '["111", "222"]',
                    }
                ],
            },
        ]
        mock_get.side_effect = [
            Mock(json=Mock(return_value=mock_events)),
            Mock(json=Mock(return_value=[])),
        ]

        result = search_all_events_paginated()

        assert isinstance(result, list)

    @patch('polymarket_events_4.requests.get')
    def test_stops_at_max_offset(self, mock_get):
        """Should stop pagination at offset 500"""
        mock_events = [{'title': 'Some Event', 'slug': 'some-event', 'markets': []}]
        mock_get.return_value = Mock(json=Mock(return_value=mock_events))

        search_all_events_paginated()

        assert mock_get.call_count == 10

    @patch('polymarket_events_4.requests.get')
    def test_handles_malformed_end_date(self, mock_get):
        """Should handle invalid endDate gracefully"""
        mock_events = [
            {
                'title': 'Bitcoin Test',
                'slug': 'btc-test',
                'markets': [
                    {
                        'question': 'Test?',
                        'endDate': 'invalid-date-format',
                        'clobTokenIds': '["111"]',
                    }
                ],
            },
        ]
        mock_get.side_effect = [
            Mock(json=Mock(return_value=mock_events)),
            Mock(json=Mock(return_value=[])),
        ]

        result = search_all_events_paginated()
        assert isinstance(result, list)


class TestFindBySpecificSlugs:
    """Tests for find_by_specific_slugs function"""

    @patch('polymarket_events_4.requests.get')
    def test_finds_existing_slug(self, mock_get):
        """Should successfully find event by known slug"""
        mock_event = {
            'title': 'Bitcoin Up or Down',
            'markets': [
                {'question': 'Will BTC be up at 6pm?'},
                {'question': 'Will BTC be down at 6pm?'},
            ],
        }
        mock_get.return_value = Mock(
            status_code=200,
            json=Mock(return_value=mock_event)
        )

        find_by_specific_slugs()

        assert mock_get.called

    @patch('polymarket_events_4.requests.get')
    def test_handles_not_found_slug(self, mock_get):
        """Should handle 404 for non-existent slugs"""
        mock_get.return_value = Mock(status_code=404)

        find_by_specific_slugs()

        assert mock_get.called

    @patch('polymarket_events_4.requests.get')
    def test_handles_request_exception(self, mock_get):
        """Should handle network errors gracefully"""
        mock_get.side_effect = Exception("Network error")

        find_by_specific_slugs()

    @patch('polymarket_events_4.requests.get')
    def test_tries_all_slug_patterns(self, mock_get):
        """Should attempt all predefined slug patterns"""
        mock_get.return_value = Mock(status_code=404)

        find_by_specific_slugs()

        assert mock_get.call_count >= 7


class TestIntegration:
    """Integration tests using real slug from URL"""

    def test_known_slug_format(self):
        """Verify we understand the slug format from real URL"""
        url = "https://polymarket.com/event/bitcoin-up-or-down-december-20-6pm-et?tid=1766273344050"
        
        slug = url.split('/event/')[1].split('?')[0]
        assert slug == "bitcoin-up-or-down-december-20-6pm-et"
        
        tid = url.split('tid=')[1]
        assert tid == "1766273344050"

    def test_slug_patterns_include_date_format(self):
        """Verify slug patterns could match dated events"""
        keywords = ['up or down', 'up-or-down', 'pm', '6:']
        slug = "bitcoin-up-or-down-december-20-6pm-et"
        
        matches = [kw for kw in keywords if kw in slug]
        assert len(matches) > 0, "Should match at least one keyword"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])