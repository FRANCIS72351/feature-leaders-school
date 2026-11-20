"""Pure SMTP email automation helper for the FLPA Portal."""
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

# Load environment variables automatically when this module is imported or run
load_dotenv()


def send_school_email(recipient_email, subject, body_text, html_body=None):
    """
    Send an automated email via SMTP using Python's built-in smtplib.
    Returns True on success, False on failure.
    """
    if not recipient_email or '@' not in recipient_email:
        print("SMTP Error: Invalid recipient email address.")
        return False

    smtp_server = os.environ.get('SMTP_SERVER', 'smtp-relay.brevo.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_login = os.environ.get('SMTP_LOGIN', '')
    smtp_password = os.environ.get('SMTP_PASSWORD', '')
    sender_email = os.environ.get('SENDER_EMAIL', '')
    sender_name = os.environ.get('SENDER_NAME', 'Future Leaders Preparatory Academy')

    if not all([smtp_login, smtp_password, sender_email]):
        print("SMTP Error: Missing SMTP credentials in environment variables.")
        return False

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{sender_email}>"
    msg['To'] = recipient_email
    msg.set_content(body_text)

    if html_body:
        msg.add_alternative(html_body, subtype='html')

    try:
        print(f"Connecting to {smtp_server}:{smtp_port}...")
        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            print(f"Logging in as {smtp_login}...")
            server.login(smtp_login, smtp_password)
            print(f"Sending email to {recipient_email}...")
            server.send_message(msg)
        print(f"SMTP Success: Email sent to {recipient_email}")
        return True
    except Exception as e:
        print(f"SMTP Error sending to {recipient_email}: {e}")
        return False


# This allows you to run `python school_mailer.py` directly to test it
if __name__ == '__main__':
    print("Running direct email test...")
    test_recipient = "xhangocharm@gmail.com"
    send_school_email(
        recipient_email=test_recipient,
        subject="FLPA Portal Direct Test",
        body_text="Hello! This is a direct test execution of the school mailer."
    )