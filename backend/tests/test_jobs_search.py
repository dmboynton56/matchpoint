import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import app.db.turso as turso


def _seed_jobs():
    turso.close()
    turso.init_schema()
    now = datetime.now(timezone.utc)
    jobs = [
        {
            "external_id": "gh-1",
            "company": "Acme",
            "title": "Senior Software Engineer",
            "description": "Build distributed systems with Python and Go.",
            "location": "Denver, CO",
            "posted_at": (now - timedelta(days=2)).isoformat(),
            "apply_url": "https://example.com/1",
            "embedding": [0.1] * 8,
            "last_seen_at": now.isoformat(),
            "workplace_type": "on_site",
            "experience_level": "senior",
            "job_type": "full_time",
            "pay_min": 150000,
            "pay_max": 180000,
            "pay_currency": "USD",
            "summary": "Senior engineer role building distributed systems.",
        },
        {
            "external_id": "gh-2",
            "company": "Beta Labs",
            "title": "Machine Learning Engineer",
            "description": "Train models for recommendation systems.",
            "location": "Remote - USA",
            "posted_at": (now - timedelta(days=5)).isoformat(),
            "apply_url": "https://example.com/2",
            "embedding": [0.2] * 8,
            "last_seen_at": now.isoformat(),
            "workplace_type": "remote",
            "experience_level": "mid",
            "job_type": "full_time",
            "pay_min": 130000,
            "pay_max": 170000,
            "pay_currency": "USD",
            "summary": "ML engineer building recommendation models.",
        },
        {
            "external_id": "gh-3",
            "company": "Gamma",
            "title": "Product Designer Intern",
            "description": "Design UI for mobile apps.",
            "location": "San Francisco, CA",
            "posted_at": (now - timedelta(days=40)).isoformat(),
            "apply_url": "https://example.com/3",
            "embedding": [0.3] * 8,
            "last_seen_at": now.isoformat(),
            "workplace_type": "hybrid",
            "experience_level": "internship",
            "job_type": "internship",
            "pay_min": 50000,
            "pay_max": 80000,
            "pay_currency": "USD",
            "summary": "Internship designing mobile UI.",
        },
    ]
    turso.upsert_jobs(jobs)
    return jobs


@pytest.fixture(autouse=True)
def fresh_db():
    _seed_jobs()
    yield
    turso.close()


class TestTursoSearchJobs:
    def test_keyword_and_filters(self):
        rows, total = turso.search_jobs(keywords="python")
        assert total == 1
        assert rows[0]["title"] == "Senior Software Engineer"

    def test_location_or_filter(self):
        rows, total = turso.search_jobs(locations=["Remote", "Denver"])
        assert total == 2
        titles = {row["title"] for row in rows}
        assert "Senior Software Engineer" in titles
        assert "Machine Learning Engineer" in titles

    def test_date_posted_window(self):
        rows, total = turso.search_jobs(date_posted="7d")
        assert total == 2
        assert all("Intern" not in row["title"] for row in rows)

    def test_experience_level_filter(self):
        rows, total = turso.search_jobs(experience_levels=["internship"])
        assert total == 1
        assert rows[0]["title"] == "Product Designer Intern"

    def test_workplace_filter(self):
        rows, total = turso.search_jobs(workplace_types=["remote"])
        assert total == 1
        assert rows[0]["company"] == "Beta Labs"

    def test_pay_overlap_filter(self):
        rows, total = turso.search_jobs(pay_min=160000)
        assert total == 2
        companies = {row["company"] for row in rows}
        assert companies == {"Acme", "Beta Labs"}

    def test_pay_filter_excludes_unknown_pay(self):
        now = datetime.now(timezone.utc)
        turso.upsert_jobs(
            [
                {
                    "external_id": "gh-unknown-pay",
                    "company": "Unknown Pay Co",
                    "title": "Mystery Role",
                    "description": "No compensation listed.",
                    "location": "Remote",
                    "posted_at": now.isoformat(),
                    "apply_url": "https://example.com/unknown",
                    "embedding": [0.4] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )

        rows, total = turso.search_jobs(pay_min=100000)
        assert all(row["company"] != "Unknown Pay Co" for row in rows)

        rows_all, total_all = turso.search_jobs()
        assert total_all == 4
        assert any(row["company"] == "Unknown Pay Co" for row in rows_all)

    def test_date_posted_excludes_unknown_posted_at(self):
        now = datetime.now(timezone.utc)
        turso.upsert_jobs(
            [
                {
                    "external_id": "gh-unknown-date",
                    "company": "Undated Co",
                    "title": "Undated Role",
                    "description": "Evergreen opening.",
                    "location": "Remote",
                    "posted_at": None,
                    "apply_url": "https://example.com/undated",
                    "embedding": [0.5] * 8,
                    "last_seen_at": now.isoformat(),
                    "workplace_type": "remote",
                    "experience_level": "mid",
                    "job_type": "full_time",
                    "pay_min": 120000,
                    "pay_max": 140000,
                    "pay_currency": "USD",
                }
            ]
        )

        rows, total = turso.search_jobs(date_posted="7d")
        assert all(row["company"] != "Undated Co" for row in rows)

        rows_all, total_all = turso.search_jobs()
        assert any(row["company"] == "Undated Co" for row in rows_all)

    def test_relevance_sort(self):
        rows, _ = turso.search_jobs(
            keywords="engineer machine",
            sort="relevance",
        )
        assert rows[0]["title"] == "Machine Learning Engineer"

    def test_newest_sort(self):
        rows, _ = turso.search_jobs(sort="newest")
        assert rows[0]["title"] == "Senior Software Engineer"

    def test_pagination(self):
        rows, total = turso.search_jobs(page=1, page_size=2)
        assert total == 3
        assert len(rows) == 2

        rows2, _ = turso.search_jobs(page=2, page_size=2)
        assert len(rows2) == 1

    def test_browse_columns_exclude_description(self):
        rows, _ = turso.search_jobs()
        for row in rows:
            assert "description" not in row
            assert "summary" in row

    def test_batch_update_job_summaries(self, monkeypatch):
        rows, _ = turso.search_jobs(page_size=3)
        updates = [
            (
                row["id"],
                {
                    "summary": f"Updated summary {index}",
                    "source_hash": f"hash-{index}",
                    "model": "test-model",
                    "generated_at": "2026-07-15T12:00:00+00:00",
                },
            )
            for index, row in enumerate(rows)
        ]

        connection = turso.get_client()

        class RecordingConnection:
            def __init__(self):
                self.commit_calls = 0

            def execute(self, *args, **kwargs):
                return connection.execute(*args, **kwargs)

            def commit(self):
                self.commit_calls += 1
                return connection.commit()

        recording_connection = RecordingConnection()
        monkeypatch.setattr(turso, "get_client", lambda: recording_connection)

        turso.batch_update_job_summaries(updates)

        assert recording_connection.commit_calls == 1
        cursor = connection.execute(
            "SELECT summary FROM jobs WHERE id IN (?, ?, ?)",
            [row["id"] for row in rows],
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "Updated summary 0",
            "Updated summary 1",
            "Updated summary 2",
        }

    def test_batch_update_job_summaries_rejects_stale_hash(self):
        rows, _ = turso.search_jobs(page_size=1)
        job_id = rows[0]["id"]
        conn = turso.get_client()
        conn.execute(
            "UPDATE jobs SET summary = ?, summary_source_hash = ? WHERE id = ?",
            ["Existing summary", "current-hash", job_id],
        )
        conn.commit()

        turso.batch_update_job_summaries(
            [
                (
                    job_id,
                    {
                        "summary": "Should not apply",
                        "source_hash": "stale-hash",
                        "model": "test-model",
                        "generated_at": "2026-07-15T12:00:00+00:00",
                    },
                )
            ]
        )

        cursor = conn.execute(
            "SELECT summary, summary_source_hash FROM jobs WHERE id = ?",
            [job_id],
        )
        summary, source_hash = cursor.fetchone()
        assert summary == "Existing summary"
        assert source_hash == "current-hash"

    def test_metadata_backfill_marks_unclassified_rows(self):
        now = datetime.now(timezone.utc)
        turso.upsert_jobs(
            [
                {
                    "external_id": "gh-unclassified",
                    "company": "Plain Co",
                    "title": "Generalist",
                    "description": "Do many things.",
                    "location": "Austin, TX",
                    "posted_at": now.isoformat(),
                    "apply_url": "https://example.com/plain",
                    "embedding": [0.2] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )
        rows = turso.fetch_jobs_for_metadata_backfill(limit=10)
        assert any(row["title"] == "Generalist" for row in rows)

        from app.services.job_metadata import derive_browse_metadata, metadata_derived_timestamp

        derived_at = metadata_derived_timestamp()
        batch = []
        for row in rows:
            if row["title"] != "Generalist":
                continue
            metadata = derive_browse_metadata(
                title=row.get("title") or "",
                location=row.get("location"),
                description=row.get("description"),
            )
            metadata["metadata_derived_at"] = derived_at
            batch.append((row["id"], metadata))
        turso.batch_update_job_metadata(batch)

        rows_after = turso.fetch_jobs_for_metadata_backfill(limit=10)
        assert all(row["title"] != "Generalist" for row in rows_after)


class TestJobsSearchRoute:
    def test_search_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/jobs/search?q=python")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["jobs"][0]["title"] == "Senior Software Engineer"
        assert "description" not in payload["jobs"][0]

    def test_default_load_returns_latest_ten(self):
        from fastapi.testclient import TestClient
        from app.main import app

        conn = turso.get_client()
        conn.execute("DELETE FROM jobs")
        conn.commit()

        now = datetime.now(timezone.utc)
        jobs = []
        for index in range(12):
            posted_at = (
                (now - timedelta(days=index)).isoformat()
                if index < 9
                else None
            )
            jobs.append(
                {
                    "external_id": f"latest-{index}",
                    "company": "Ordering Inc",
                    "title": f"Ordered Role {index}",
                    "description": f"Description {index}",
                    "location": "Denver, CO",
                    "posted_at": posted_at,
                    "apply_url": f"https://example.com/latest/{index}",
                    "embedding": [0.1] * 8,
                    "last_seen_at": now.isoformat(),
                    "workplace_type": "on_site",
                    "experience_level": "mid",
                    "job_type": "full_time",
                    "summary": f"Summary {index}",
                }
            )
        turso.upsert_jobs(jobs)

        response = TestClient(app).get("/jobs/search")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 12
        assert len(payload["jobs"]) == 10
        posted_values = [job["posted_at"] for job in payload["jobs"]]
        assert posted_values[-1] is None
        assert posted_values[:-1] == sorted(posted_values[:-1], reverse=True)

    def test_default_load_does_not_block_on_llm(self, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import job_summary

        now = datetime.now(timezone.utc)
        description = "Respond immediately with this description excerpt."
        turso.upsert_jobs(
            [
                {
                    "external_id": "no-block",
                    "company": "Fast Path LLC",
                    "title": "Fast Path Engineer",
                    "description": description,
                    "location": "Remote",
                    "posted_at": (now + timedelta(days=1)).isoformat(),
                    "apply_url": "https://example.com/no-block",
                    "embedding": [0.6] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )

        def fail_if_called(*args, **kwargs):
            raise RuntimeError("simulated LLM outage")

        monkeypatch.setattr(job_summary, "generate_summary", fail_if_called)

        response = TestClient(app).get("/jobs/search")

        assert response.status_code == 200
        job = next(
            job for job in response.json()["jobs"] if job["title"] == "Fast Path Engineer"
        )
        assert job["summary"] == description

    def test_first_display_defers_summary_generation(self, monkeypatch):
        """First display is an excerpt; the completed background task fills the cache."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import job_summary

        now = datetime.now(timezone.utc)
        turso.upsert_jobs(
            [
                {
                    "external_id": "gh-4",
                    "company": "Delta",
                    "title": "Junior Data Analyst",
                    "description": (
                        "Analyze dashboards and reports. This hybrid role pays "
                        "$70,000 - $90,000 per year."
                    ),
                    "location": "Chicago, IL",
                    "posted_at": now.isoformat(),
                    "apply_url": "https://example.com/4",
                    "embedding": [0.4] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )

        calls = {"count": 0}

        def fake_generate(description, *, title="", company=""):
            calls["count"] += 1
            return "LLM summary for the analyst role."

        monkeypatch.setattr(job_summary, "generate_summary", fake_generate)

        client = TestClient(app)
        response = client.get("/jobs/search?q=dashboards")
        assert response.status_code == 200
        job = response.json()["jobs"][0]
        assert job["summary"] == (
            "Analyze dashboards and reports. This hybrid role pays "
            "$70,000 - $90,000 per year."
        )
        assert calls["count"] == 1

        # Salary + metadata were extracted and persisted on first display.
        assert job["pay_min"] == 70000
        assert job["pay_max"] == 90000
        assert job["workplace_type"] == "hybrid"
        assert job["experience_level"] == "entry"

        # TestClient has finished the background task, so the DB is populated.
        conn = turso.get_client()
        cursor = conn.execute(
            "SELECT summary FROM jobs WHERE id = ?", [job["id"]]
        )
        assert cursor.fetchone()[0] == "LLM summary for the analyst role."

        # Second request serves the stored summary without another generation.
        response = client.get("/jobs/search?q=dashboards")
        assert response.status_code == 200
        job = response.json()["jobs"][0]
        assert job["summary"] == "LLM summary for the analyst role."
        assert job["pay_min"] == 70000
        assert calls["count"] == 1

    def test_summary_failure_falls_back_to_excerpt_without_caching(self, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import job_summary

        now = datetime.now(timezone.utc)
        turso.upsert_jobs(
            [
                {
                    "external_id": "gh-5",
                    "company": "Epsilon",
                    "title": "QA Engineer",
                    "description": "Write end-to-end tests for web applications.",
                    "location": "Austin, TX",
                    "posted_at": now.isoformat(),
                    "apply_url": "https://example.com/5",
                    "embedding": [0.5] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )

        calls = {"count": 0}

        def fake_failure(*args, **kwargs):
            calls["count"] += 1
            return None

        monkeypatch.setattr(job_summary, "generate_summary", fake_failure)

        client = TestClient(app)
        response = client.get("/jobs/search?q=end-to-end")
        assert response.status_code == 200
        job = response.json()["jobs"][0]
        assert job["summary"] == "Write end-to-end tests for web applications."

        # Not persisted — the next request should try generation again.
        rows = turso.fetch_job_text([job["id"]])
        conn = turso.get_client()
        cursor = conn.execute(
            "SELECT summary FROM jobs WHERE id = ?", [job["id"]]
        )
        stored = cursor.fetchone()[0]
        assert stored in (None, "")
        assert rows[0]["description"]

        response = client.get("/jobs/search?q=end-to-end")
        assert response.status_code == 200
        assert response.json()["jobs"][0]["summary"] == (
            "Write end-to-end tests for web applications."
        )
        assert calls["count"] == 2

    def test_background_dedup(self, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services import job_summary

        now = datetime.now(timezone.utc)
        description = "Build reliable duplicate-resistant background systems."
        turso.upsert_jobs(
            [
                {
                    "external_id": "dedup-job",
                    "company": "Concurrency Co",
                    "title": "Background Systems Engineer",
                    "description": description,
                    "location": "Remote",
                    "posted_at": now.isoformat(),
                    "apply_url": "https://example.com/dedup",
                    "embedding": [0.7] * 8,
                    "last_seen_at": now.isoformat(),
                }
            ]
        )

        generation_started = threading.Event()
        allow_generation_to_finish = threading.Event()
        calls = {"count": 0}

        def slow_generate(*args, **kwargs):
            calls["count"] += 1
            generation_started.set()
            assert allow_generation_to_finish.wait(timeout=5)
            return "Generated exactly once."

        monkeypatch.setattr(job_summary, "generate_summary", slow_generate)
        first_client = TestClient(app)
        second_client = TestClient(app)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_request = pool.submit(
                first_client.get, "/jobs/search?q=duplicate-resistant"
            )
            assert generation_started.wait(timeout=5)
            second_request = pool.submit(
                second_client.get, "/jobs/search?q=duplicate-resistant"
            )
            try:
                second_response = second_request.result(timeout=5)
            finally:
                allow_generation_to_finish.set()
            first_response = first_request.result(timeout=5)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json()["jobs"][0]["summary"] == description
        assert second_response.json()["jobs"][0]["summary"] == description
        assert calls["count"] == 1

    def test_parse_endpoint_mocked(self, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.routes import jobs as jobs_route
        from app.schemas.job_search import ParsedJobSearchFilters

        def fake_parse(message: str):
            return ParsedJobSearchFilters(
                keywords="machine learning",
                locations=["Denver"],
                experienceLevels=["entry"],
                payMin=120000,
            )

        monkeypatch.setattr(jobs_route, "parse_job_search_message", fake_parse)

        client = TestClient(app)
        response = client.post(
            "/jobs/search/parse",
            json={"message": "entry level ml in denver over 120k"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["keywords"] == "machine learning"
        assert data["locations"] == ["Denver"]
        assert data["experienceLevels"] == ["entry"]
        assert data["payMin"] == 120000

    def test_parse_endpoint_rejects_whitespace_only_message(self):
        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).post(
            "/jobs/search/parse",
            json={"message": "   "},
        )
        assert response.status_code == 422

    def test_parse_endpoint_returns_generic_error(self, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.routes import jobs as jobs_route

        def boom(_message: str):
            raise RuntimeError("secret parser failure")

        monkeypatch.setattr(jobs_route, "parse_job_search_message", boom)

        response = TestClient(app).post(
            "/jobs/search/parse",
            json={"message": "senior remote roles"},
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "Failed to parse search query."
        assert "secret parser failure" not in response.text


class TestGenerateAndAttachSummary:
    def test_does_not_cache_hash_on_generation_failure(self, monkeypatch):
        from app.services import job_summary

        monkeypatch.setattr(job_summary, "generate_summary", lambda *args, **kwargs: None)

        job = {
            "description": "Build reliable systems end to end.",
            "title": "Platform Engineer",
            "company": "Example Co",
        }
        result = job_summary.generate_and_attach_summary(dict(job))

        assert result["summary"] == "Build reliable systems end to end."
        assert result.get("summary_source_hash") is None
        assert result.get("summary_model") is None
        assert result.get("summary_generated_at") is None
