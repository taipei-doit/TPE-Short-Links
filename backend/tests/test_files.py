from __future__ import annotations

import datetime as dt
import io

import pytest

from app import storage as storage_mod
from app.models import FileShare, SharedFile
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


def create_share(files_client, **payload):
    return files_client.post("/api/shares", json=payload)


def add_file(files_client, code, *, name="report.pdf", content=b"hello world"):
    """Run the two-step upload the browser performs: session, then bytes."""
    session = files_client.post(
        f"/api/shares/{code}/upload-session",
        json={"filename": name, "content_type": "application/pdf", "size_bytes": len(content)},
    )
    if session.status_code != 200:
        return session
    body = session.json()
    return files_client.post(
        body["upload_url"],
        files={"file": (name, io.BytesIO(content), "application/pdf")},
        data={"upload_token": body["upload_token"]},
    )


def make_share(files_client, *, name="report.pdf", content=b"hello world", **payload):
    """Create a share holding one file and return its JSON plus the PIN."""
    created = create_share(files_client, **payload).json()
    add_file(files_client, created["code"], name=name, content=content)
    return created


# --------------------------------------------------------------------------
# Creating shares and adding files
# --------------------------------------------------------------------------


def test_create_share_returns_code_and_pin(files_client):
    r = create_share(files_client, note="給長官")
    assert r.status_code == 200, r.text
    data = r.json()

    assert len(data["pin"]) == PIN_LENGTH
    assert data["pin"].isalnum()
    assert any(c.isalpha() for c in data["pin"])
    assert any(c.isdigit() for c in data["pin"])
    assert data["note"] == "給長官"
    assert data["status"] == "active"
    assert data["file_count"] == 0
    assert data["share_url"].endswith(f"/f/{data['code']}")


def test_one_share_holds_many_files(files_client):
    created = create_share(files_client).json()
    code = created["code"]

    for i in range(7):
        r = add_file(files_client, code, name=f"附件{i}.pdf", content=b"x" * (100 + i))
        assert r.status_code == 200, r.text

    listed = files_client.get("/api/shares").json()
    assert listed["total"] == 1
    share = listed["items"][0]
    assert share["file_count"] == 7
    assert share["total_bytes"] == sum(100 + i for i in range(7))
    assert [f["filename"] for f in share["files"]] == [f"附件{i}.pdf" for i in range(7)]

    # One link, one PIN, seven files.
    r = files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]})
    assert r.status_code == 200
    assert len(r.json()["files"]) == 7


def test_pin_is_not_stored_in_plaintext(files_client, db_session):
    pin = create_share(files_client).json()["pin"]

    share = db_session.query(FileShare).one()
    assert pin not in share.pin_hash
    assert share.pin_hash.startswith("pbkdf2_sha256$")


def test_upload_session_falls_back_to_proxy_without_object_storage(files_client):
    code = create_share(files_client).json()["code"]
    r = files_client.post(
        f"/api/shares/{code}/upload-session",
        json={"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10},
    )
    assert r.status_code == 200
    body = r.json()
    # Local disk cannot issue a browser-reachable upload URL.
    assert body["mode"] == "proxy"
    assert body["upload_url"] == f"/api/shares/{code}/files"


def test_upload_session_refuses_a_file_beyond_the_overall_ceiling(files_client, monkeypatch):
    monkeypatch.setenv("MAX_FILE_MB", "1")
    get_settings.cache_clear()
    code = create_share(files_client).json()["code"]

    r = files_client.post(
        f"/api/shares/{code}/upload-session",
        json={"filename": "big.bin", "content_type": None, "size_bytes": 5 * 1024 * 1024},
    )
    assert r.status_code == 413


def test_proxy_upload_refuses_a_file_beyond_the_cloud_run_limit(files_client, monkeypatch):
    # Without object storage there is no way past what Cloud Run will accept.
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    code = create_share(files_client).json()["code"]

    r = files_client.post(
        f"/api/shares/{code}/upload-session",
        json={"filename": "big.bin", "content_type": None, "size_bytes": 5 * 1024 * 1024},
    )
    assert r.status_code == 413
    assert "無法直接上傳" in r.json()["detail"]


def test_upload_requires_a_valid_session_token(files_client):
    code = create_share(files_client).json()["code"]
    r = files_client.post(
        f"/api/shares/{code}/files",
        files={"file": ("a.pdf", io.BytesIO(b"x"), "application/pdf")},
        data={"upload_token": "forged.token"},
    )
    assert r.status_code == 400


def test_upload_token_is_bound_to_its_own_share(files_client):
    first = create_share(files_client).json()["code"]
    second = create_share(files_client).json()["code"]

    session = files_client.post(
        f"/api/shares/{first}/upload-session",
        json={"filename": "a.pdf", "content_type": None, "size_bytes": 5},
    ).json()

    r = files_client.post(
        f"/api/shares/{second}/files",
        files={"file": ("a.pdf", io.BytesIO(b"hello"), "application/pdf")},
        data={"upload_token": session["upload_token"]},
    )
    assert r.status_code == 400


def test_empty_upload_is_rejected(files_client):
    code = create_share(files_client).json()["code"]
    assert add_file(files_client, code, content=b"").status_code == 422


def test_expiry_must_be_in_the_future(files_client):
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    assert create_share(files_client, expires_at=past).status_code == 422


def test_custom_pin_is_accepted_and_validated(files_client):
    assert create_share(files_client, pin="abcd1234").json()["pin"] == "ABCD1234"

    assert create_share(files_client, pin="short1").status_code == 422
    r = create_share(files_client, pin="ABCDEFGH")
    assert r.status_code == 422
    assert "數字" in r.json()["detail"]
    r = create_share(files_client, pin="12345678")
    assert r.status_code == 422
    assert "英文" in r.json()["detail"]


def test_filename_is_sanitized(files_client):
    code = create_share(files_client).json()["code"]
    r = add_file(files_client, code, name="../../etc/passwd")
    assert r.status_code == 200
    assert r.json()["filename"] == "passwd"


# --------------------------------------------------------------------------
# The public side
# --------------------------------------------------------------------------


def test_landing_page_hides_filenames_until_the_pin_is_entered(files_client):
    created = make_share(files_client, name="機密預算表.xlsx", content=b"secret")

    r = files_client.get(f"/f/{created['code']}")
    assert r.status_code == 200
    # Anyone can reach this page, so it shows only what is safe before the PIN.
    assert "機密預算表.xlsx" not in r.text
    assert "secret" not in r.text

    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": created["pin"]})
    assert r.json()["files"][0]["filename"] == "機密預算表.xlsx"


def test_unknown_code_redirects_to_404(files_client):
    r = files_client.get("/f/NOPE12", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/404.html")


def test_share_with_no_files_is_not_public_yet(files_client):
    created = create_share(files_client).json()
    assert files_client.get(f"/f/{created['code']}", follow_redirects=False).status_code == 302
    assert files_client.post(
        f"/f/{created['code']}/verify", json={"pin": created["pin"]}
    ).status_code == 404


def test_correct_pin_yields_working_downloads(files_client):
    created = create_share(files_client).json()
    code = created["code"]
    add_file(files_client, code, name="報告.pdf", content=b"first file")
    add_file(files_client, code, name="附件.docx", content=b"second file")

    r = files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]})
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert len(files) == 2

    first = files_client.get(files[0]["download_url"])
    assert first.status_code == 200
    assert first.content == b"first file"
    # RFC 5987 encoding carries the Chinese filename through.
    assert "filename*=UTF-8''" in first.headers["content-disposition"]

    second = files_client.get(files[1]["download_url"])
    assert second.content == b"second file"

    share = files_client.get("/api/shares").json()["items"][0]
    assert share["download_count"] == 2


def test_pin_check_is_case_insensitive(files_client):
    created = make_share(files_client)
    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": created["pin"].lower()})
    assert r.status_code == 200


def test_wrong_pin_is_rejected_and_counted(files_client):
    created = make_share(files_client)

    r = files_client.post(f"/f/{created['code']}/verify", json={"pin": "WRONG123"})
    assert r.status_code == 401
    # A machine-readable code, so the page can render it in any of its languages.
    assert r.json()["detail"]["error"] == "wrong_pin"
    assert r.json()["detail"]["remaining"] == 4


def test_repeated_wrong_pins_lock_the_share(files_client):
    created = make_share(files_client)
    code = created["code"]

    for _ in range(4):
        assert files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"}).status_code == 401

    r = files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"})
    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "locked"
    assert r.json()["detail"]["minutes"] == 15

    # The correct PIN is refused too while the lockout holds.
    assert files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]}).status_code == 429
    assert files_client.get("/api/shares").json()["items"][0]["is_locked"] is True


def test_download_requires_a_valid_token(files_client):
    created = make_share(files_client)
    code = created["code"]
    file_id = files_client.get("/api/shares").json()["items"][0]["files"][0]["id"]

    assert files_client.get(f"/f/{code}/download/{file_id}?token=forged.abc").status_code == 403
    assert files_client.get(f"/f/{code}/download/{file_id}?token=99999999999.abc").status_code == 403


def test_download_token_is_bound_to_its_own_share(files_client):
    first = make_share(files_client, name="a.pdf")
    second = make_share(files_client, name="b.pdf", content=b"other bytes")

    token = (
        files_client.post(f"/f/{first['code']}/verify", json={"pin": first["pin"]})
        .json()["files"][0]["download_url"]
        .split("token=")[1]
    )
    other_id = files_client.post(f"/f/{second['code']}/verify", json={"pin": second["pin"]}).json()[
        "files"
    ][0]["id"]

    r = files_client.get(f"/f/{second['code']}/download/{other_id}?token={token}")
    assert r.status_code == 403


def test_expired_share_is_unreachable(files_client, db_session):
    created = make_share(files_client)
    share = db_session.query(FileShare).one()
    share.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db_session.commit()

    assert files_client.get(f"/f/{created['code']}", follow_redirects=False).status_code == 302
    assert files_client.post(
        f"/f/{created['code']}/verify", json={"pin": created["pin"]}
    ).status_code == 404


def test_disabled_share_is_unreachable_then_restorable(files_client):
    created = make_share(files_client)
    code = created["code"]

    assert files_client.post(f"/api/shares/{code}/disable").status_code == 200
    assert files_client.get(f"/f/{code}", follow_redirects=False).status_code == 302

    assert files_client.post(f"/api/shares/{code}/enable").status_code == 200
    assert files_client.get(f"/f/{code}").status_code == 200


# --------------------------------------------------------------------------
# Managing an existing share
# --------------------------------------------------------------------------


def test_regenerating_the_pin_invalidates_the_old_one(files_client):
    created = make_share(files_client)
    code = created["code"]

    r = files_client.post(f"/api/shares/{code}/regenerate-pin")
    assert r.status_code == 200
    new_pin = r.json()["pin"]
    assert new_pin != created["pin"]

    assert files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]}).status_code == 401
    assert files_client.post(f"/f/{code}/verify", json={"pin": new_pin}).status_code == 200


def test_regenerating_the_pin_clears_a_lockout(files_client):
    code = make_share(files_client)["code"]
    for _ in range(5):
        files_client.post(f"/f/{code}/verify", json={"pin": "WRONG123"})

    new_pin = files_client.post(f"/api/shares/{code}/regenerate-pin").json()["pin"]
    assert files_client.post(f"/f/{code}/verify", json={"pin": new_pin}).status_code == 200


def test_deleting_one_file_leaves_the_rest_of_the_share(files_client, db_session):
    created = create_share(files_client).json()
    code = created["code"]
    add_file(files_client, code, name="keep.pdf", content=b"keep me")
    add_file(files_client, code, name="drop.pdf", content=b"drop me")

    drop = db_session.query(SharedFile).filter_by(filename="drop.pdf").one()
    stored = storage_mod.get_storage()._full(drop.storage_path)
    assert stored.exists()

    assert files_client.delete(f"/api/shares/{code}/files/{drop.id}").status_code == 200
    assert not stored.exists()

    share = files_client.get("/api/shares").json()["items"][0]
    assert share["file_count"] == 1
    verified = files_client.post(f"/f/{code}/verify", json={"pin": created["pin"]}).json()
    assert [f["filename"] for f in verified["files"]] == ["keep.pdf"]


def test_delete_share_erases_every_file_but_keeps_the_row(files_client, db_session):
    created = create_share(files_client).json()
    code = created["code"]
    add_file(files_client, code, name="a.pdf", content=b"aaa")
    add_file(files_client, code, name="b.pdf", content=b"bbb")

    paths = [
        storage_mod.get_storage()._full(f.storage_path) for f in db_session.query(SharedFile).all()
    ]
    assert all(p.exists() for p in paths)

    assert files_client.delete(f"/api/shares/{code}").status_code == 200
    assert not any(p.exists() for p in paths)

    share = db_session.query(FileShare).one()
    db_session.refresh(share)
    assert share.status == "deleted"
    assert files_client.get(f"/f/{code}", follow_redirects=False).status_code == 302


def test_update_expiry_and_note(files_client):
    code = make_share(files_client, note="舊備註")["code"]
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=3)).isoformat()

    r = files_client.patch(f"/api/shares/{code}", json={"note": "新備註"})
    assert r.status_code == 200
    assert r.json()["note"] == "新備註"
    assert r.json()["expires_at"] is None

    r = files_client.patch(f"/api/shares/{code}", json={"expires_at": future})
    assert r.status_code == 200
    # Updating only the expiry must leave the note alone.
    assert r.json()["note"] == "新備註"
    assert r.json()["expires_at"] is not None


def test_list_filters_by_status_and_query(files_client):
    a = make_share(files_client, name="alpha.pdf")
    make_share(files_client, name="beta.pdf", content=b"beta")
    files_client.post(f"/api/shares/{a['code']}/disable")

    assert files_client.get("/api/shares").json()["total"] == 2
    assert files_client.get("/api/shares?status=active").json()["total"] == 1
    assert files_client.get("/api/shares?status=disabled").json()["total"] == 1
    # Searching reaches into the filenames a share holds.
    assert files_client.get("/api/shares?query=beta").json()["total"] == 1


# --------------------------------------------------------------------------
# Languages
# --------------------------------------------------------------------------


def test_landing_page_language_follows_accept_language(files_client):
    code = make_share(files_client)["code"]

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
    code = make_share(files_client)["code"]

    # ?lang= wins over the browser's preference.
    r = files_client.get(f"/f/{code}?lang=ja", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert "ファイルのダウンロード" in r.text

    # An unknown value is ignored rather than breaking the page.
    r = files_client.get(f"/f/{code}?lang=fr", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert "File Download" in r.text


def test_landing_page_ships_every_translation(files_client):
    code = make_share(files_client)["code"]
    r = files_client.get(f"/f/{code}")
    # Switching language must not need a round trip, so all four are embedded.
    for heading in ("檔案下載", "File Download", "ファイルのダウンロード", "파일 다운로드"):
        assert heading in r.text
    assert r.headers["vary"] == "Accept-Language"
