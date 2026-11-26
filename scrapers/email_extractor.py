import re
from urllib.parse import unquote
from config.constants import EMAIL_REGEX


INVALID_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".woff", ".woff2", ".ttf", ".css", ".js"
)

PLACEHOLDER_EMAIL_LOCAL_PARTS = {
    "you", "yourname", "your-name", "name", "username", "user",
    "johndoe", "john.doe", "janedoe", "jane.doe", "test", "example",
    "sample", "demo", "noreply", "no-reply", "donotreply", "mailer-daemon",
}

PLACEHOLDER_DOMAINS = {
    "example.com", "domain.com", "email.com", "company.com", "yourdomain.com",
    "yourmail.com", "sentry.io", "wixpress.com", "squarespace.com", "ueni.com",
}


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    email = unquote(str(email)).lower().strip().strip(".,;:<>\"'")

    for ext in INVALID_EXTENSIONS:
        if email.endswith(ext):
            return False

    if "@" not in email or "." not in email.split("@")[-1]:
        return False

    local_part, domain = email.rsplit("@", 1)
    if not local_part or not domain:
        return False
    if local_part in PLACEHOLDER_EMAIL_LOCAL_PARTS:
        return False
    if domain in PLACEHOLDER_DOMAINS or any(b in domain for b in ("example.", "wixpress.", "sentry.")):
        return False

    return bool(re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,10}", email))


def extract_emails(html: str) -> list[str]:
    if not html:
        return []
    emails = re.findall(EMAIL_REGEX, html)
    cleaned_emails = []
    seen = set()

    for email in emails:
        cand = unquote(email).strip()
        if is_valid_email(cand):
            key = cand.lower()
            if key not in seen:
                seen.add(key)
                cleaned_emails.append(cand)

    return cleaned_emails
