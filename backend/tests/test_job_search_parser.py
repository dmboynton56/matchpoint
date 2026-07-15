import unittest
from unittest.mock import MagicMock, patch

from app.schemas.job_search import ParsedJobSearchFilters
from app.services.job_search_parser import (
    parse_job_search_message,
    parsed_filters_to_dict,
)


class JobSearchParserTests(unittest.TestCase):
    def test_parsed_filters_to_dict_omits_empty(self):
        parsed = ParsedJobSearchFilters(
            keywords="engineer",
            locations=[],
            payMin=None,
        )
        result = parsed_filters_to_dict(parsed)
        self.assertEqual(result, {"keywords": "engineer"})

    @patch("app.services.job_search_parser.parser_client")
    def test_parse_job_search_message(self, mock_client):
        mock_parsed = ParsedJobSearchFilters(
            keywords="machine learning",
            locations=["Remote"],
            experienceLevels=["senior"],
        )
        mock_choice = MagicMock()
        mock_choice.message.parsed = mock_parsed
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_client.beta.chat.completions.parse.return_value = mock_completion

        result = parse_job_search_message("senior ml jobs remote")
        self.assertEqual(result.keywords, "machine learning")
        self.assertEqual(result.locations, ["Remote"])
        self.assertEqual(result.experienceLevels, ["senior"])


if __name__ == "__main__":
    unittest.main()
