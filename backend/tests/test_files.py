from __future__ import annotations

import datetime as dt
import io

import pytest

from app import storage as storage_mod
from app.models import SharedFile
from app.pins import PIN_LENGTH
from app.settings import get_settings


@pytest.fixture()
def files_client(client, tmp_path, monkeypatch):
    """A client whose shared files land in a temp directory, not in GCS."""
    monkeypatch.setenv("FILE_STORAGE_BUCKET", "")
    monkeypatch.setenv("FILE_STORAGE_LOCAL_DIR", str(tmp_path / "shared-files"))
    monkeypatch.setenv("FILE_DOWNLOAD_SECRET", "test-secret-for-download-tokens")
    get_settings.cache_clear()
    storage_mod.reset_storage()
    yield client
    get_settings.cache_clear()
    storage_mod.reset_storage()


def upload(files_client, *, name="report.pdf", content=b"hello world", **form):
    return files_client.post(
        "/api/files",
        files={"file": (name, io.BytesIO(content), "application/pdf")},
        data=form,
    )


def test_upload_returns_code_and_pin(files_client):
    r = upload(files_client, note="給長官")
    assert r.status_code == 200, r.text
    data = r.json()

    assert len(data["pin"]) == PIN_LENGTH
    assert data["pin"].isalnum()
    assert any(c.isalpha() for c in data["pin"])
    assert any(c.isdigit() for c in data["pin"])
    assert data["filename"] == "report.pdf"
    assert data["size_bytes"] == len(b"hello world")
    assert data["note"] == "給長官"
    assert data["status"] == "active"
    assert data["share_url"].endswith(f"/f/{data['code']}")


def test_pin_is_not_stored_in_plaintext(files_client, db_session):
    r = upload(files_client)
    pin = r.json()["pin"]

    record = db_session.query(SharedFile).one()
    assert pin not in record.pin_hash
    assert record.pin_hash.startswith("pbkdf2_sha256$")


def test_landing_page_shows_metadata_and_hides_content(files_client):
    code = upload(files_client, name="預算表.xlsx").json()["code"]

    r = files_client.get(f"/f/{code}")
    assert r.status_code == 200
    assert "預算表.xlsx" in r.text
    assert "PIN" in r.text
    # The bytes themselves must never appear before the PIN is entered.
    assert "hello world" not in r.text


def test_unknown_code_redirects_to_404(files_client):
    r = files_client.get("/f/NOPE12", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/404.html")


def test_correct_pin_yields_a_working_download(files_client):
    created = upload(files_client, name="報告.pdf", content=b"secret bytes").json()

    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": created["pin"]})
    assert r.status_code == 200, r.text
    download_url = r.json()["download_url"]

    d = files_client.get(download_url)
    assert d.status_code == 200
    assert d.content == b"secret bytes"
    # RFC 5987 encoding carries the Chinese filename through.
    assert "filename*=UTF-8''" in d.headers["content-disposition"]

    listed = files_client.get("/api/files").json()["items"][0]
    assert listed["download_count"] == 1


def test_pin_check_is_case_insensitive(files_client):
    created = upload(files_client).json()
    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": created["pin"].lower()})
    assert r.status_code == 200


def test_wrong_pin_is_rejected_and_counted(files_client):
    created = upload(files_client).json()

    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": "WRONG123"})
    assert r.status_code == 401
    # A machine-readable code, so the page can render it in any of its languages.
    assert r.json()["detail"]["error"] == "wrong_pin"
    assert r.json()["detail"]["remaining"] == 4


def test_repeated_wrong_pins_lock_the_link(files_client):
    created = upload(files_client).json()
    code = created["code"]

    for _ in range(4):
        assert files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"}).status_code == 401

    r = files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"})
    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "locked"
    assert r.json()["detail"]["minutes"] == 15

    # The correct PIN is refused too while the lockout holds.
    r = files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]})
    assert r.status_code == 429

    assert files_client.get("/api/files").json()["items"][0]["is_locked"] is True


def test_download_requires_a_valid_token(files_client):
    code = upload(files_client).json()["code"]

    assert files_client.get(f"/f/{code}/download?token=forged.abc").status_code == 403
    assert files_client.get(f"/f/{code}/download?token=99999999999.abc").status_code == 403


def test_download_token_is_bound_to_its_own_file(files_client):
    first = upload(files_client, name="a.pdf").json()
    second = upload(files_client, name="b.pdf", content=b"other bytes").json()

    token = files_client.post(
        f"/f/{first['code']}/verify", json={"pin": first["pin"]}
    ).json()["download_url"].split("token=")[1]

    r = files_client.get(f"/f/{second['code']}/download?token={token}")
    assert r.status_code == 403


def test_expired_file_is_unreachable(files_client, db_session):
    created = upload(files_client).json()
    record = db_session.query(SharedFile).one()
    record.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db_session.commit()

    assert files_client.get(f"/f/{created['code']}", follow_redirects=False).status_code == 302
    assert files_client.post(
        f"/f/{created['code']}/verify", json={"pin": created["pin"]}
    ).status_code == 404


def test_disabled_file_is_unreachable_then_restorable(files_client):
    created = upload(files_client).json()
    code = created["code"]

    assert files_client.post(f"/api/files/{code}/disable").status_code == 200
    assert files_client.get(f"/f/{code}", follow_redirects=False).status_code == 302

    assert files_client.post(f"/api/files/{code}/enable").status_code == 200
    assert files_client.get(f"/f/{code}").status_code == 200


def test_regenerating_the_pin_invalidates_the_old_one(files_client):
    created = upload(files_client).json()
    code = created["code"]

    r = files_client.post(f"/api/files/{code}/regenerate-pin")
    assert r.status_code == 200
    new_pin = r.json()["pin"]
    assert new_pin != created["pin"]

    assert files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]}).status_code == 401
    assert files_client.post(f"/f/{code}/verify", json={"pin": new_pin}).status_code == 200


def test_regenerating_the_pin_clears_a_lockout(files_client):
    code = upload(files_client).json()["code"]
    for _ in range(5):
        files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"})

    new_pin = files_client.post(f"/api/files/{code}/regenerate-pin").json()["pin"]
    assert files_client.post(f"/f/{code}/verify", json={"pin": new_pin}).status_code == 200


def test_delete_erases_the_bytes_but_keeps_the_row(files_client, db_session):
    created = upload(files_client).json()
    code = created["code"]
    record = db_session.query(SharedFile).one()
    stored = storage_mod.get_storage()._full(record.storage_path)
    assert stored.exists()

    assert files_client.delete(f"/api/files/{code}").status_code == 200
    assert not stored.exists()

    db_session.refresh(record)
    assert record.status == "deleted"
    assert files_client.get(f"/f/{code}", follow_redirects=False).status_code == 302


def test_custom_pin_is_accepted_and_validated(files_client):
    assert upload(files_client, pin="abcd1234").json()["pin"] == "ABCD1234"

    r = upload(files_client, pin="short1")
    assert r.status_code == 422
    r = upload(files_client, pin="ABCDEFGH")
    assert r.status_code == 422
    assert "數字" in r.json()["detail"]
    r = upload(files_client, pin="12345678")
    assert r.status_code == 422
    assert "英文" in r.json()["detail"]


def test_oversized_upload_is_rejected(files_client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()

    r = upload(files_client, content=b"x" * (2 * 1024 * 1024))
    assert r.status_code == 413
    assert files_client.get("/api/files").json()["total"] == 0


def test_empty_upload_is_rejected(files_client):
    assert upload(files_client, content=b"").status_code == 422


def test_expiry_must_be_in_the_future(files_client):
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    assert upload(files_client, expires_at=past).status_code == 422


def test_update_expiry_and_note(files_client):
    code = upload(files_client, note="舊備註").json()["code"]
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=3)).isoformat()

    r = files_client.patch(f"/api/files/{code}", json={"note": "新備註"})
    assert r.status_code == 200
    assert r.json()["note"] == "新備註"
    assert r.json()["expires_at"] is None

    r = files_client.patch(f"/api/files/{code}", json={"expires_at": future})
    assert r.status_code == 200
    # Updating only the expiry must leave the note alone.
    assert r.json()["note"] == "新備註"
    assert r.json()["expires_at"] is not None


def test_list_filters_by_status_and_query(files_client):
    a = upload(files_client, name="alpha.pdf").json()
    upload(files_client, name="beta.pdf", content=b"beta")
    files_client.post(f"/api/files/{a['code']}/disable")

    assert files_client.get("/api/files").json()["total"] == 2
    assert files_client.get("/api/files?status=active").json()["total"] == 1
    assert files_client.get("/api/files?status=disabled").json()["total"] == 1
    assert files_client.get("/api/files?query=beta").json()["total"] == 1


def test_landing_page_language_follows_accept_language(files_client):
    code = upload(files_client).json()["code"]

    cases = {
        "zh-TW,zh;q=0.9": ("檔案下載", 'lang="zh-Hant-TW"'),
        "en-US,en;q=0.9": ("File Download", 'lang="en"'),
        "ja,en;q=0.8": ("ファイルのダウンロード", 'lang="ja"'),
        "ko-KR,ko;q=0.9": ("파일 다운로드", 'lang="ko"'),
        # Unsupported languages fall back to Traditional Chinese.
        "de-DE,de;q=0.9": ("檔案下載", 'lang="zh-Hant-TW"'),
    }
    for header, (heading, lang_attr) in cases.items():
        r = files_client.get(f"/f/{code}", headers={"Accept-Language": header})
        assert r.status_code == 200
        assert heading in r.text, header
        assert lang_attr in r.text, header


def test_landing_page_language_can_be_forced_by_query(files_client):
    code = upload(files_client).json()["code"]

    # ?lang= wins over the browser's preference.
    r = files_client.get(f"/f/{code}?lang=ja", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert "ファイルのダウンロード" in r.text

    # An unknown value is ignored rather than breaking the page.
    r = files_client.get(f"/f/{code}?lang=fr", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert "File Download" in r.text


def test_landing_page_ships_every_translation(files_client):
    code = upload(files_client).json()["code"]
    r = files_client.get(f"/f/{code}")
    # Switching language must not need a round trip, so all four are embedded.
    for heading in ("檔案下載", "File Download", "ファイルのダウンロード", "파일 다운로드"):
        assert heading in r.text
    assert r.headers["vary"] == "Accept-Language"


def test_landing_page_escapes_the_filename(files_client):
    # Angle brackets never survive filename sanitisation...
    code = upload(files_client, name="<script>alert(1)</script>.pdf").json()["code"]
    assert "<script>alert(1)</script>" not in files_client.get(f"/f/{code}").text

    # ...and what does survive is still HTML-escaped on the way out.
    code = upload(files_client, name="A&B 'quoted'.pdf", content=b"x").json()["code"]
    r = files_client.get(f"/f/{code}")
    assert "A&amp;B" in r.text
    assert "A&B" not in r.text


def test_filename_is_sanitized(files_client):
    r = upload(files_client, name="../../etc/passwd")
    assert r.status_code == 200
    assert r.json()["filename"] == "passwd"
