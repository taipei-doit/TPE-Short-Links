"""Public-facing HTML served directly by this service.

url.taipei points at Cloud Run rather than at Firebase Hosting, so anything a
member of the public sees on that domain has to be rendered here.
"""

from __future__ import annotations

from fastapi.responses import RedirectResponse

from app.settings import get_settings

PAGE_STYLE = """
      :root { color-scheme: light; }
      * { box-sizing: border-box; }
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", Arial, sans-serif; background:#f8fafc; color:#0f172a; margin:0; }
      .wrap { max-width: 720px; margin: 72px auto; padding: 0 20px; }
      .card { background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:28px; box-shadow: 0 10px 25px rgba(15,23,42,0.08); }
      h1 { font-size: 28px; margin: 0 0 12px; }
      p { font-size: 16px; line-height: 1.7; margin: 0 0 8px; color:#334155; }
"""

NOT_FOUND_HTML = f"""<!doctype html>
<html lang="zh-Hant-TW">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>頁面不存在</title>
    <style>{PAGE_STYLE}</style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>抱歉！找不到您要找的頁面。</h1>
        <p>如網址正確，表示該頁面已下架或連結已失效，</p>
        <p>如需了解進一步資訊，請逕洽網站頁面之主責機關。</p>
      </div>
    </div>
  </body>
</html>"""


def redirect_to_not_found() -> RedirectResponse:
    settings = get_settings()
    return RedirectResponse(
        url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/404.html",
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
