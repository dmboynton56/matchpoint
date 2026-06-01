import unittest
from pathlib import Path

import pandas as pd

from app.services.cleaning import resolve_job_location

CSV_PATH = Path(__file__).resolve().parents[1] / "app" / "job_board_data_100.csv"
CLOUDFLARE_DESCRIPTION = (
    "Cloudflare provides reasonable accommodations to qualified individuals with "
    "disabilities. If you require a reasonable accommodation to apply for a job, "
    "please contact us via e-mail at hr@cloudflare.com or via mail at "
    "101 Townsend St. San Francisco, CA 94107."
)
HYBRID_LOCATIONS_DESCRIPTION = (
    "Locations - Sweden (Remote) or Germany (Munich) Cloudflare is seeking a "
    "Developer Platform Engineer."
)


class ResolveJobLocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job_rows = pd.read_csv(CSV_PATH)

    def test_in_office_cloudflare_uses_description_city(self):
        row = self.job_rows[self.job_rows["location"] == "In-Office"].iloc[0]
        self.assertEqual(
            resolve_job_location(row["location"], row["description"]),
            "San Francisco, CA · In-Office",
        )

    def test_in_office_cloudflare_boilerplate(self):
        self.assertEqual(
            resolve_job_location("In-Office", CLOUDFLARE_DESCRIPTION),
            "San Francisco, CA · In-Office",
        )

    def test_hybrid_with_city_prefix(self):
        self.assertEqual(
            resolve_job_location("Hybrid - San Francisco", ""),
            "San Francisco · Hybrid",
        )

    def test_san_francisco_ca_unchanged(self):
        self.assertEqual(resolve_job_location("San Francisco, CA", ""), "San Francisco, CA")

    def test_remote_usa_normalized(self):
        self.assertEqual(
            resolve_job_location("Remote - USA", ""),
            "United States · Remote",
        )

    def test_hybrid_in_office_compound(self):
        self.assertEqual(
            resolve_job_location("Hybrid; In-Office", CLOUDFLARE_DESCRIPTION),
            "San Francisco, CA · Hybrid",
        )

    def test_hybrid_description_locations_fallback(self):
        self.assertEqual(
            resolve_job_location("Hybrid", HYBRID_LOCATIONS_DESCRIPTION),
            "Sweden (Remote) or Germany (Munich) · Hybrid",
        )

    def test_already_enriched_location_is_idempotent(self):
        enriched = "San Francisco, CA · In-Office"
        self.assertEqual(
            resolve_job_location(enriched, CLOUDFLARE_DESCRIPTION),
            enriched,
        )


if __name__ == "__main__":
    unittest.main()
