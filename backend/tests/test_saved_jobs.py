from copy import deepcopy

import pytest
from fastapi import HTTPException

import app.db.database as db_module
import app.db.turso as turso
import app.routes.matches as matches_route
from app.routes.matches import (
    SavedJobsTableNotConfigured,
    _fetch_saved_jobs_by_job_ids,
    _get_saved_matches,
    _get_user_matches,
    _is_missing_saved_jobs_table_error,
    _update_saved_job_flag,
    _upsert_saved_job_from_match,
)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(
        self,
        store: "FakeSupabaseStore",
        table_name: str,
        *,
        mode: str = "select",
        payload=None,
        on_conflict: str | None = None,
    ):
        self.store = store
        self.table_name = table_name
        self.mode = mode
        self.payload = payload
        self.on_conflict = on_conflict
        self.filters: dict = {}
        self.order_col: str | None = None
        self.order_desc = False
        self._maybe_single = False
        self._single = False

    def select(self, _cols, **_kwargs):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = set(vals)
        return self

    def order(self, col, desc=False):
        self.order_col = col
        self.order_desc = desc
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def single(self):
        self._single = True
        return self

    def upsert(self, payload, on_conflict=None):
        return _FakeQuery(
            self.store,
            self.table_name,
            mode="upsert",
            payload=payload,
            on_conflict=on_conflict,
        )

    def update(self, vals):
        return _FakeQuery(
            self.store,
            self.table_name,
            mode="update",
            payload=vals,
        )

    def delete(self):
        return _FakeQuery(self.store, self.table_name, mode="delete")

    def _matches(self, row: dict) -> bool:
        for key, value in self.filters.items():
            if isinstance(value, set):
                if row.get(key) not in value:
                    return False
            elif row.get(key) != value:
                return False
        return True

    def _filtered_rows(self) -> list[dict]:
        rows = self.store.tables.setdefault(self.table_name, [])
        matched = [row for row in rows if self._matches(row)]
        if self.order_col:
            matched = sorted(
                matched,
                key=lambda row: row.get(self.order_col) or "",
                reverse=self.order_desc,
            )
        return matched

    def execute(self):
        if self.mode == "upsert":
            rows = self.store.tables.setdefault(self.table_name, [])
            payload = deepcopy(self.payload)
            conflict_keys = (
                [part.strip() for part in self.on_conflict.split(",")]
                if self.on_conflict
                else []
            )
            existing = None
            if conflict_keys:
                for row in rows:
                    if all(row.get(key) == payload.get(key) for key in conflict_keys):
                        existing = row
                        break
            if existing is not None:
                existing.update(payload)
                return _FakeResponse([existing])
            rows.append(payload)
            return _FakeResponse([payload])

        if self.mode == "update":
            updated = []
            for row in self.store.tables.setdefault(self.table_name, []):
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(row)
            return _FakeResponse(updated)

        if self.mode == "delete":
            rows = self.store.tables.setdefault(self.table_name, [])
            kept = [row for row in rows if not self._matches(row)]
            deleted_count = len(rows) - len(kept)
            self.store.tables[self.table_name] = kept
            return _FakeResponse([{"deleted": deleted_count}])

        matched = self._filtered_rows()
        if self._maybe_single:
            if len(matched) == 1:
                return _FakeResponse(matched[0])
            return _FakeResponse(None)
        if self._single:
            if len(matched) != 1:
                raise RuntimeError("Expected exactly one row for .single()")
            return _FakeResponse(matched[0])
        return _FakeResponse(matched)


class FakeSupabaseStore:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = {name: deepcopy(rows) for name, rows in (tables or {}).items()}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


USER_ID = "user-1"
JOB_ID = "11111111-2222-4333-8444-555555555555"
MATCH_ID = "match-1"


def _sample_match(**overrides) -> dict:
    payload = {
        "id": MATCH_ID,
        "job_id": JOB_ID,
        "user_id": USER_ID,
        "match_score": 0.91,
        "is_viewed": False,
        "is_favorited": False,
        "is_applied": False,
        "created_at": "2026-06-10T00:00:00Z",
        "match_notes": [{"text": "Strong overlap", "is_warning": False}],
        "match_highlights": ["Python"],
        "match_concerns": [],
        "interview_likelihood": 0.7,
        "skills_fit": 0.9,
        "experience_fit": 0.85,
        "seniority_fit": 0.8,
        "location_fit": 0.75,
        "pay_fit": 0.7,
        "role_fit": 0.88,
        "preference_fit": 0.8,
        "location_reason": None,
        "location_evidence": None,
        "pay_reason": None,
        "pay_evidence": None,
        "role_reason": None,
        "role_evidence": None,
        "job_facts": None,
    }
    payload.update(overrides)
    return payload


def _sample_job(**overrides) -> dict:
    payload = {
        "id": JOB_ID,
        "title": "Senior Python Engineer",
        "company": "Stripe",
        "location": "Remote",
        "description": "Build APIs and platform tooling.",
        "apply_url": "https://stripe.com/jobs/1",
        "posted_at": "2026-06-08T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _sample_saved_job(**overrides) -> dict:
    payload = {
        "id": "saved-1",
        "user_id": USER_ID,
        "job_id": JOB_ID,
        "source_match_id": MATCH_ID,
        "is_favorited": True,
        "is_applied": False,
        "favorited_at": "2026-06-10T01:00:00Z",
        "applied_at": None,
        "updated_at": "2026-06-10T01:00:00Z",
        "latest_match_score": 0.91,
        "job_snapshot": {
            "id": JOB_ID,
            "title": "Senior Python Engineer",
            "company": "Stripe",
            "location": "Remote",
            "apply_url": "https://stripe.com/jobs/1",
            "description": "Build APIs and platform tooling.",
            "posted_at": "2026-06-08T00:00:00+00:00",
        },
        "match_snapshot": {
            "match_id": MATCH_ID,
            "job_id": JOB_ID,
            "matched_at": "2026-06-10T00:00:00Z",
            "match_score": 0.91,
            "match_notes": [{"text": "Strong overlap", "is_warning": False}],
            "match_highlights": ["Python"],
            "match_concerns": [],
            "interview_likelihood": 0.7,
            "skills_fit": 0.9,
            "experience_fit": 0.85,
            "seniority_fit": 0.8,
            "location_fit": 0.75,
            "pay_fit": 0.7,
            "role_fit": 0.88,
            "preference_fit": 0.8,
            "location_reason": None,
            "location_evidence": None,
            "pay_reason": None,
            "pay_evidence": None,
            "role_reason": None,
            "role_evidence": None,
            "job_facts": None,
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def reset_turso():
    turso.close()
    turso.init_schema()
    embedding = [1.0] + [0.0] * 1535
    turso.upsert_jobs(
        [
            {
                "external_id": "ext-1",
                "company": "Stripe",
                "title": "Senior Python Engineer",
                "description": "Build APIs and platform tooling.",
                "location": "Remote",
                "posted_at": "2026-06-08T00:00:00+00:00",
                "apply_url": "https://stripe.com/jobs/1",
                "embedding": embedding,
                "last_seen_at": "2026-06-10T00:00:00+00:00",
            }
        ]
    )
    yield
    turso.close()


@pytest.fixture
def fake_supabase():
    original_db_supabase = db_module.supabase
    original_route_supabase = matches_route.supabase
    store = FakeSupabaseStore(
        {
            "job_matches": [_sample_match()],
            "user_saved_jobs": [],
        }
    )
    db_module.supabase = store
    matches_route.supabase = store
    yield store
    db_module.supabase = original_db_supabase
    matches_route.supabase = original_route_supabase


def test_is_missing_saved_jobs_table_error():
    assert _is_missing_saved_jobs_table_error(
        RuntimeError('relation "public.user_saved_jobs" does not exist')
    )
    assert not _is_missing_saved_jobs_table_error(RuntimeError("connection refused"))


def test_upsert_saved_job_from_match_creates_row_with_snapshots(fake_supabase):
    result = _upsert_saved_job_from_match(
        user_id=USER_ID,
        match=_sample_match(is_favorited=True),
        job=_sample_job(),
        is_favorited=True,
    )

    assert result["job_id"] == JOB_ID
    assert result["is_favorited"] is True
    assert len(fake_supabase.tables["user_saved_jobs"]) == 1
    saved = fake_supabase.tables["user_saved_jobs"][0]
    assert saved["job_snapshot"]["company"] == "Stripe"
    assert saved["match_snapshot"]["match_score"] == 0.91
    assert saved["latest_match_score"] == 0.91


def test_upsert_saved_job_from_match_deletes_when_both_flags_false(fake_supabase):
    fake_supabase.tables["user_saved_jobs"] = [_sample_saved_job()]

    result = _upsert_saved_job_from_match(
        user_id=USER_ID,
        match=_sample_match(is_favorited=False, is_applied=False),
        job=_sample_job(),
        is_favorited=False,
        is_applied=False,
    )

    assert result == {
        "job_id": JOB_ID,
        "is_favorited": False,
        "is_applied": False,
    }
    assert fake_supabase.tables["user_saved_jobs"] == []


def test_get_saved_matches_filters_favorited(fake_supabase):
    fake_supabase.tables["user_saved_jobs"] = [
        _sample_saved_job(),
        _sample_saved_job(
            id="saved-2",
            job_id="22222222-3333-4333-8444-555555555555",
            is_favorited=False,
            is_applied=True,
            favorited_at=None,
            applied_at="2026-06-11T00:00:00Z",
            updated_at="2026-06-11T00:00:00Z",
        ),
    ]

    favorites = _get_saved_matches(USER_ID, favorited=True)
    applied = _get_saved_matches(USER_ID, applied=True)

    assert len(favorites) == 1
    assert favorites[0]["job_id"] == JOB_ID
    assert favorites[0]["jobs"]["company"] == "Stripe"
    assert len(applied) == 1
    assert applied[0]["is_applied"] is True


def test_update_saved_job_flag_toggles_and_deletes_when_cleared(fake_supabase):
    fake_supabase.tables["user_saved_jobs"] = [_sample_saved_job(is_applied=False)]

    new_value = _update_saved_job_flag(
        user_id=USER_ID,
        job_id=JOB_ID,
        flag="is_favorited",
    )

    assert new_value is False
    assert fake_supabase.tables["user_saved_jobs"] == []
    assert fake_supabase.tables["job_matches"][0]["is_favorited"] is False


def test_update_saved_job_flag_keeps_row_when_other_flag_set(fake_supabase):
    fake_supabase.tables["user_saved_jobs"] = [
        _sample_saved_job(is_favorited=True, is_applied=True)
    ]

    new_value = _update_saved_job_flag(
        user_id=USER_ID,
        job_id=JOB_ID,
        flag="is_favorited",
    )

    assert new_value is False
    assert len(fake_supabase.tables["user_saved_jobs"]) == 1
    saved = fake_supabase.tables["user_saved_jobs"][0]
    assert saved["is_favorited"] is False
    assert saved["is_applied"] is True


def test_update_saved_job_flag_raises_when_saved_job_missing(fake_supabase):
    with pytest.raises(HTTPException) as exc:
        _update_saved_job_flag(
            user_id=USER_ID,
            job_id="missing-job-id",
            flag="is_favorited",
        )

    assert exc.value.status_code == 404


def test_fetch_saved_jobs_by_job_ids_returns_empty_when_table_missing(fake_supabase):
    class MissingSavedJobsStore(FakeSupabaseStore):
        def table(self, name: str):
            if name == "user_saved_jobs":
                raise RuntimeError(
                    'Could not find the table public.user_saved_jobs in the schema cache'
                )
            return super().table(name)

    store = MissingSavedJobsStore(fake_supabase.tables)
    db_module.supabase = store
    matches_route.supabase = store

    assert _fetch_saved_jobs_by_job_ids(USER_ID, [JOB_ID]) == {}


def test_get_saved_matches_raises_when_table_missing(fake_supabase):
    class MissingSavedJobsStore(FakeSupabaseStore):
        def table(self, name: str):
            if name == "user_saved_jobs":
                raise RuntimeError('relation "public.user_saved_jobs" does not exist')
            return super().table(name)

    store = MissingSavedJobsStore(fake_supabase.tables)
    db_module.supabase = store
    matches_route.supabase = store

    with pytest.raises(SavedJobsTableNotConfigured):
        _get_saved_matches(USER_ID, favorited=True)


def test_get_user_matches_overrides_flags_from_saved_jobs(fake_supabase):
    turso_job_id = turso.get_client().execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    fake_supabase.tables["user_saved_jobs"] = [
        _sample_saved_job(
            job_id=turso_job_id,
            is_favorited=True,
            is_applied=True,
            job_snapshot=_sample_job(id=turso_job_id),
            match_snapshot=_sample_saved_job()["match_snapshot"]
            | {"job_id": turso_job_id},
        )
    ]
    fake_supabase.tables["job_matches"] = [
        _sample_match(
            job_id=turso_job_id,
            is_favorited=False,
            is_applied=False,
        )
    ]

    matches = _get_user_matches(USER_ID, viewed=None, favorited=None, applied=None)

    assert len(matches) == 1
    assert matches[0]["is_favorited"] is True
    assert matches[0]["is_applied"] is True
    assert matches[0]["jobs"]["title"] == "Senior Python Engineer"
