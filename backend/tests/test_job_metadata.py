import unittest

from app.services.job_metadata import (
    derive_browse_metadata,
    infer_experience_level,
    infer_job_type,
)


class JobMetadataTests(unittest.TestCase):
    def test_infer_experience_level_senior(self):
        self.assertEqual(infer_experience_level("Senior Software Engineer"), "senior")

    def test_infer_experience_level_intern(self):
        self.assertEqual(infer_experience_level("Software Engineering Intern"), "internship")

    def test_infer_job_type_contract(self):
        self.assertEqual(
            infer_job_type("Backend Developer", "This is a 6-month contract role."),
            "contract",
        )

    def test_derive_browse_metadata_remote_salary(self):
        metadata = derive_browse_metadata(
            title="Senior Product Manager",
            location="Remote - USA",
            description=(
                "The expected salary range for this role is $160,000 - $210,000. "
                "This role can be performed remotely."
            ),
        )
        self.assertEqual(metadata["workplace_type"], "remote")
        self.assertEqual(metadata["pay_min"], 160000)
        self.assertEqual(metadata["pay_max"], 210000)
        self.assertEqual(metadata["experience_level"], "senior")


if __name__ == "__main__":
    unittest.main()
