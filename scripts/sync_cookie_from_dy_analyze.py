import re
from pathlib import Path

ROOT = Path(r"e:\dy_comments")
COOKIE_TXT = Path(r"E:\dy_analyze\cookie.txt")

raw = COOKIE_TXT.read_text(encoding="utf-8", errors="ignore").strip()
m = re.search(r"'cookie'\s*:\s*'(.*)'\s*,?$", raw, flags=re.S)
cookie = m.group(1) if m else raw
cookie = cookie.strip().strip('"').strip("'")

verify = ""
m2 = re.search(r"(?:^|;\s*)s_v_web_id=([^;]+)", cookie)
if m2:
    verify = m2.group(1).strip()

env_path = ROOT / ".env"
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()
else:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

kv = {}
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        kv[k.strip()] = v

kv["DY_COOKIE"] = cookie
if verify:
    kv["DY_VERIFY_FP"] = verify

out = [f"{k}={v}" for k, v in kv.items()]
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("updated", env_path)
print("cookie_len", len(cookie))
print("verify_fp", verify)
