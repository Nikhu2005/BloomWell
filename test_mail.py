import os, smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
load_dotenv()

sender   = os.environ.get('MAIL_USERNAME')
password = os.environ.get('MAIL_PASSWORD')

print(f"Sending from: {sender}")

try:
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.ehlo()
    server.starttls()
    server.login(sender, password)
    msg = MIMEText("Test from Bloom!")
    msg['Subject'] = 'Bloom OTP Test'
    msg['From'] = sender
    msg['To'] = sender
    server.sendmail(sender, sender, msg.as_string())
    server.quit()
    print("SUCCESS - Check your inbox!")
except Exception as e:
    print(f"FAILED: {e}")