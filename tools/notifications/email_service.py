import os
import logging
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

# We load credentials here, but allow them to be overridden or skipped 
# if the user just wants to run without emails.
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_PWD = os.getenv('EMAIL_PASSWORD')

def check_credentials():
    """
    Check if required email credentials are set in the environment.
    Returns True if fully configured, False otherwise.
    """
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PWD]):
        logging.warning("Missing Gmail credentials in .env. Email notifications are DISABLED.")
        return False
    return True

def send_email(subject: str, body: str) -> bool:
    """
    Send an email notification using Gmail SMTP (SSL).
    
    Args:
        subject: The subject line of the email.
        body: The plain text body of the email.
        
    Returns:
        bool: True if email was sent successfully, False otherwise.
    """
    if not check_credentials():
        return False
        
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PWD)
            server.send_message(msg)
            
        logging.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return False
