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

    def test_salary_range_without_keyword(self):
        salary = extract_salary_facts(
            "We're a fast-growing startup. $120,000 - $150,000 plus equity."
        )
        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 120000)
        self.assertEqual(salary.maximum, 150000)
        self.assertEqual(salary.period, "annual")

    def test_salary_shorthand_k_range(self):
        salary = extract_salary_facts("Base of $120-150k depending on experience.")
        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 120000)
        self.assertEqual(salary.maximum, 150000)

    def test_salary_range_uses_later_valid_match(self):
        salary = extract_salary_facts(
            "Stipend of $5 - $10 daily. Annual pay is $90,000 - $110,000."
        )
        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 90000)
        self.assertEqual(salary.maximum, 110000)

    def test_salary_range_scales_low_without_k_suffix(self):
        salary = extract_salary_facts("Role pays $120 - $150,000.")
        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 120000)
        self.assertEqual(salary.maximum, 150000)

    def test_hourly_pay_rate(self):
        salary = extract_salary_facts("Pay rate: $45 - $55 per hour.")
        self.assertIsNotNone(salary)
        self.assertEqual(salary.minimum, 45)
        self.assertEqual(salary.maximum, 55)
        self.assertEqual(salary.period, "hourly")

    def test_small_dollar_range_ignored(self):
        # "$5 - $10" (e.g. a stipend) shouldn't register as an annual salary.
        self.assertIsNone(
            extract_salary_facts("Employees get a $5 - $10 lunch credit daily.")
        )

    def test_product_designer_maps_to_design(self):
        facts = extract_job_facts(
            title="Product Designer",
            location="Remote",
            description="",
        )
        self.assertEqual(facts.role_family, "design")


if __name__ == "__main__":
    unittest.main()
