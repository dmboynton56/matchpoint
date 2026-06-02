import unittest

from app.services.job_facts import extract_job_facts, extract_salary_facts


class JobFactsTests(unittest.TestCase):
    def test_extract_remote_salary_and_role_family(self):
        facts = extract_job_facts(
            title="Senior Product Manager, AI Platform",
            location="Remote - USA",
            description=(
                "The expected salary range for this role is $160,000 - $210,000. "
                "This role can be performed remotely in the United States."
            ),
        )

        self.assertEqual(facts.work_modes, ["Remote"])
        self.assertEqual(facts.locations[0], "United States")
        self.assertEqual(facts.role_family, "product")
        self.assertIsNotNone(facts.salary)
        self.assertEqual(facts.salary.minimum, 160000)
        self.assertEqual(facts.salary.maximum, 210000)
        self.assertEqual(facts.salary.period, "annual")

    def test_salary_extractor_uses_full_compensation_sentence(self):
        salary = extract_salary_facts(
            "Compensation may be adjusted depending on work location. "
            "For NYC based hires: Estimated annual salary of "
            "$300,000 - $393,000 - $413,000."
        )

        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 300000)
        self.assertEqual(salary.maximum, 413000)
        self.assertIn("Estimated annual salary", salary.evidence)

    def test_salary_unknown_when_no_pay_evidence(self):
        self.assertIsNone(extract_salary_facts("This role has strong benefits."))

    def test_product_designer_maps_to_design(self):
        facts = extract_job_facts(
            title="Product Designer",
            location="Remote",
            description="",
        )
        self.assertEqual(facts.role_family, "design")


if __name__ == "__main__":
    unittest.main()
