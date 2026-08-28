import os
import smtplib
from email.message import EmailMessage


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_FROM", username or "no-reply@topbearing.local"))
    use_ssl = os.getenv("SMTP_SSL", "0") == "1"
    use_tls = os.getenv("SMTP_TLS", os.getenv("SMTP_STARTTLS", "1")) == "1"

    message = EmailMessage()
    message["Subject"] = "TopBearing — відновлення пароля"
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(
        "Ви запросили відновлення пароля TopBearing.\n\n"
        f"Перейдіть за посиланням: {reset_url}\n\n"
        "Посилання діє обмежений час. Якщо ви не робили запит, просто проігноруйте цей лист."
    )

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=20) as smtp:
        if not use_ssl and use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True
