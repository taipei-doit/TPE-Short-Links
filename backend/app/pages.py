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
      /* 無障礙檢核：字型與欄寬用相對單位，欄寬 38em ≈ 38 個中文字（上限 40） */
      .wrap { max-width: 38em; margin: 4.5em auto; padding: 0 1.25em; }
      .card { background:#fff; border:1px solid #e2e8f0; border-radius:1em; padding:1.75em; box-shadow: 0 0.6em 1.5em rgba(15,23,42,0.08); }
      h1 { font-size: 1.75em; margin: 0 0 0.75em; }
      p { font-size: 1em; line-height: 1.7; margin: 0 0 0.5em; color:#334155; }
"""

NOT_FOUND_HTML = f"""<!doctype html>
<html lang="zh-Hant-TW">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex" />
    <title>頁面不存在</title>
    <style>{PAGE_STYLE}</style>
  </head>
  <body>
    <div class="wrap">
      <main class="card">
        <h1>抱歉！找不到您要找的頁面。</h1>
        <p>如網址正確，表示該頁面已下架或連結已失效，</p>
        <p>如需了解進一步資訊，請逕洽網站頁面之主責機關。</p>
        <p><a href="/" style="color:#0F5C86; font-weight:600;">回到 url.taipei 服務首頁</a></p>
      </main>
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
