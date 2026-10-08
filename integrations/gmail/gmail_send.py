import base64
import os
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes for Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_credentials():
    cred_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
    token_path = os.path.join(os.path.dirname(__file__), 'token.json')
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return creds

def send_email(to, subject, body, attachment_path=None):
    creds = get_credentials()
    service = build('gmail', 'v1', credentials=creds)
    message = EmailMessage()
    message['To'] = to
    message['From'] = 'me'
    message['Subject'] = subject
    message.set_content(body)
    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, 'rb') as f:
            data = f.read()
        maintype, subtype = ('application', 'octet-stream')
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=os.path.basename(attachment_path))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    result = service.users().messages().send(userId='me', body={'raw': raw}).execute()
    print('Message Id:', result['id'])

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Send Gmail via FRIDAY')
    parser.add_argument('--to', required=True)
    parser.add_argument('--subject', default='Test from FRIDAY')
    parser.add_argument('--body', default='Hello from FRIDAY')
    parser.add_argument('--attach')
    args = parser.parse_args()
    send_email(args.to, args.subject, args.body, args.attach)
