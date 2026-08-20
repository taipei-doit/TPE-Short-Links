"""Translations for the public file download page.

The admin interface stays Traditional Chinese only -- it is used by city staff.
The download page is different: the link gets forwarded to people outside the
organisation, so it offers Traditional Chinese, English, Japanese and Korean.

The initial language comes from the browser's Accept-Language header (or an
explicit ?lang=), and the visitor can switch without reloading -- every string
is sent to the page, so switching is instant and needs no round trip.
"""

from __future__ import annotations

from app.pins import PIN_LENGTH

DEFAULT_LANGUAGE = "zh-Hant"

# Order here is the order of the buttons on the page.
LANGUAGE_NAMES: dict[str, str] = {
    "zh-Hant": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}

# Value for the document's lang attribute.
HTML_LANG: dict[str, str] = {
    "zh-Hant": "zh-Hant-TW",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
}

# `{len}` is the PIN length and is filled in below at import time.
# `{n}` (remaining attempts) and `{m}` (lockout minutes) are filled in by the
# page's script when an error comes back.
_RAW_STRINGS: dict[str, dict[str, str]] = {
    "zh-Hant": {
        "title": "檔案下載",
        "heading": "檔案下載",
        "intro": "此分享受 PIN 碼保護，請輸入提供者給您的 {len} 碼 PIN 碼。",
        "label_files": "檔案數量",
        "label_total_size": "檔案總大小",
        "label_expiry": "有效期限",
        # Separator after a label. Full-width in Chinese and Japanese, plain in
        # English and Korean.
        "colon": "：",
        "no_expiry": "無期限",
        "time_zone_note": "（臺北時間）",
        "pin_label": "PIN 碼",
        "submit": "確認 PIN 碼",
        "verifying": "驗證中…",
        "unlocked": "驗證成功，請點選要下載的檔案。",
        "list_heading": "檔案清單",
        "download": "下載",
        "download_all": "全部下載",
        "hint": "PIN 碼不分大小寫。連續輸入錯誤將暫時鎖定此連結。",
        "err_generic": "驗證失敗",
        "err_network": "連線失敗，請稍後再試",
        "err_wrong_pin": "PIN 碼錯誤，尚可嘗試 {n} 次",
        "err_locked": "嘗試次數過多，請於 {m} 分鐘後再試",
        "err_not_found": "連結不存在或已失效",
        "language_label": "語言",
    },
    "en": {
        "title": "File Download",
        "heading": "File Download",
        "intro": "These files are protected by a PIN. Please enter the {len}-character PIN you were given.",
        "label_files": "Files",
        "label_total_size": "Total size",
        "label_expiry": "Available until",
        "colon": ":",
        "no_expiry": "No expiry",
        "time_zone_note": "(Taipei time)",
        "pin_label": "PIN",
        "submit": "Continue",
        "verifying": "Verifying…",
        "unlocked": "Verified. Choose a file to download.",
        "list_heading": "Files",
        "download": "Download",
        "download_all": "Download all",
        "hint": "The PIN is not case-sensitive. Repeated incorrect entries will temporarily lock this link.",
        "err_generic": "Verification failed.",
        "err_network": "Connection failed. Please try again later.",
        "err_wrong_pin": "Incorrect PIN. {n} attempt(s) remaining.",
        "err_locked": "Too many attempts. Please try again in {m} minute(s).",
        "err_not_found": "This link does not exist or is no longer valid.",
        "language_label": "Language",
    },
    "ja": {
        "title": "ファイルのダウンロード",
        "heading": "ファイルのダウンロード",
        "intro": "この共有は PIN コードで保護されています。提供者から通知された {len} 桁の PIN コードを入力してください。",
        "label_files": "ファイル数",
        "label_total_size": "合計サイズ",
        "label_expiry": "有効期限",
        "colon": "：",
        "no_expiry": "無期限",
        "time_zone_note": "（台北時間）",
        "pin_label": "PIN コード",
        "submit": "確認",
        "verifying": "確認中…",
        "unlocked": "確認できました。ダウンロードするファイルを選んでください。",
        "list_heading": "ファイル一覧",
        "download": "ダウンロード",
        "download_all": "すべてダウンロード",
        "hint": "PIN コードは大文字・小文字を区別しません。連続して間違えると、このリンクは一時的にロックされます。",
        "err_generic": "確認に失敗しました。",
        "err_network": "接続に失敗しました。しばらくしてからお試しください。",
        "err_wrong_pin": "PIN コードが正しくありません。あと {n} 回入力できます。",
        "err_locked": "試行回数が多すぎます。{m} 分後にもう一度お試しください。",
        "err_not_found": "このリンクは存在しないか、無効になっています。",
        "language_label": "言語",
    },
    "ko": {
        "title": "파일 다운로드",
        "heading": "파일 다운로드",
        "intro": "이 공유는 PIN 번호로 보호되어 있습니다. 제공자에게 받은 {len}자리 PIN 번호를 입력하세요.",
        "label_files": "파일 수",
        "label_total_size": "전체 크기",
        "label_expiry": "유효 기간",
        "colon": ":",
        "no_expiry": "무기한",
        "time_zone_note": "(타이베이 시간)",
        "pin_label": "PIN 번호",
        "submit": "확인",
        "verifying": "확인 중…",
        "unlocked": "확인되었습니다. 다운로드할 파일을 선택하세요.",
        "list_heading": "파일 목록",
        "download": "다운로드",
        "download_all": "전체 다운로드",
        "hint": "PIN 번호는 대소문자를 구분하지 않습니다. 연속으로 잘못 입력하면 이 링크가 일시적으로 잠깁니다.",
        "err_generic": "확인에 실패했습니다.",
        "err_network": "연결에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        "err_wrong_pin": "PIN 번호가 올바르지 않습니다. {n}회 더 시도할 수 있습니다.",
        "err_locked": "시도 횟수가 너무 많습니다. {m}분 후에 다시 시도해 주세요.",
        "err_not_found": "이 링크는 존재하지 않거나 만료되었습니다.",
        "language_label": "언어",
    },
}

STRINGS: dict[str, dict[str, str]] = {
    lang: {key: value.replace("{len}", str(PIN_LENGTH)) for key, value in entries.items()}
    for lang, entries in _RAW_STRINGS.items()
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(STRINGS)


def pick_language(accept_language: str | None, override: str | None = None) -> str:
    """Choose a language from ?lang= if valid, otherwise from Accept-Language.

    Simplified Chinese falls through to Traditional: it is the closest of the
    four for a reader of Chinese, and this is a Taipei City service.
    """
    if override in STRINGS:
        return override
    if not accept_language:
        return DEFAULT_LANGUAGE

    entries: list[tuple[str, float]] = []
    for part in accept_language.split(",")[:20]:
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                quality = float(params[2:])
            except ValueError:
                quality = 0.0
        if tag.strip():
            entries.append((tag.strip().lower(), quality))

    for tag, _ in sorted(entries, key=lambda e: e[1], reverse=True):
        for prefix, language in (("zh", "zh-Hant"), ("en", "en"), ("ja", "ja"), ("ko", "ko")):
            if tag == prefix or tag.startswith(f"{prefix}-"):
                return language
    return DEFAULT_LANGUAGE
