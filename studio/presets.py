"""Optional example flows. Core modules contain no CLM-specific branches."""


def install_clm_v2_preset(store, project_id):
    """Install an editable example from login through send-for-signing."""
    if not store.get_project(project_id)["refresh"]:
        store.save_project(project_id, {"refresh": {
            "method": "POST", "path": "/api/auth/token/refresh/",
            "body": {"refresh": "{{refresh_token}}"},
            "captures": [
                {"name": "access_token", "path": "access", "sensitive": True},
                {"name": "refresh_token", "path": "refresh", "sensitive": True},
            ],
        }})
    if "contract_content" not in store.get_variables(project_id):
        store.set_variable(project_id, "contract_content", {
            "json": {"type": "doc", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "متن قرارداد نمونه"}]}]},
            "html": "<p>متن قرارداد نمونه</p>",
        })
    for name in ("mobile", "national_id", "address"):
        store.declare_sensitive(project_id, name)
    auth = {"Authorization": "Bearer {{access_token}}"}
    contracts = "/api/v2/tenants/{tenant_id}/contracts/"
    contract = contracts + "{contract_id}/"
    steps = [
        {"name": "ارسال پیامک ورود", "kind": "http", "method": "POST", "path": "/api/auth/send-otp/",
         "body": {"mobile": "{{mobile}}", "national_id": "{{national_id}}"}},
        {"name": "ورود کد پیامک", "kind": "manual", "manual_variables": ["otp"],
         "sensitive_variables": ["otp"]},
        {"name": "تأیید کد و دریافت توکن", "kind": "http", "method": "POST",
         "path": "/api/auth/verify-otp/",
         "body": {"mobile": "{{mobile}}", "national_id": "{{national_id}}", "code": "{{otp}}"},
         "captures": [{"name": "access_token", "path": "tokens.access", "sensitive": True},
                      {"name": "refresh_token", "path": "tokens.refresh", "sensitive": True},
                      {"name": "user_id", "path": "user.id"}]},
        {"name": "دریافت اولین فضای کار", "kind": "http", "method": "GET", "path": "/api/tenants/",
         "headers": auth, "refresh_on_401": True,
         "captures": [{"name": "tenant_id", "path": "[0].id"}]},
        {"name": "فهرست قراردادها", "kind": "http", "method": "GET", "path": contracts,
         "headers": auth, "refresh_on_401": True},
        {"name": "ایجاد قرارداد v2", "kind": "http", "method": "POST", "path": contracts,
         "headers": auth, "refresh_on_401": True,
         "body": {"title": "{{contract_title}}", "content": "{{contract_content}}",
                  "metadata": {"address": "{{address}}"}},
         "captures": [{"name": "contract_id", "path": "id"}]},
        {"name": "ثبت تاریخ پایان", "kind": "http", "method": "PATCH", "path": contract,
         "headers": auth, "refresh_on_401": True, "body": {"end_date": "{{end_date}}"}},
        {"name": "افزودن طرف، امضاکننده و تأییدکننده", "kind": "http", "method": "POST",
         "path": contract + "parties/", "headers": auth, "refresh_on_401": True,
         "body": {"user_id": "{{signer_user_id}}", "role_title": "طرف قرارداد", "order": 1,
                  "members": [
                      {"user_id": "{{signer_user_id}}", "role": "signer",
                       "role_title": "امضاکننده", "order": 1},
                      {"user_id": "{{user_id}}", "role": "approver"}]}},
        {"name": "انتشار برای بازبینی", "kind": "http", "method": "POST",
         "path": contract + "publish-for-review/", "headers": auth, "refresh_on_401": True,
         "assertions": [{"path": "contract.status", "equals": "under_approval"}]},
        {"name": "تأیید قرارداد", "kind": "http", "method": "POST",
         "path": contract + "verdict/", "headers": auth, "refresh_on_401": True,
         "body": {"state": "approved"}},
        {"name": "بررسی وضعیت تأیید", "kind": "http", "method": "GET", "path": contract,
         "headers": auth, "refresh_on_401": True,
         "assertions": [{"path": "contract.status", "equals": "approved"}]},
        {"name": "ارسال برای امضا", "kind": "http", "method": "POST",
         "path": contract + "send-for-signing/", "headers": auth, "refresh_on_401": True,
         "assertions": [{"path": "contract.status", "equals": "signing"}]},
    ]
    return store.save_flow(project_id, {"name": "نمونهٔ CLM: قرارداد v2 تا ارسال برای امضا",
                                        "steps": steps})["id"]
