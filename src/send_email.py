import base64
import json
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import ProjectConfig
from src.cred import Credentials


class SendEmail:
    BRAND_NAME = ProjectConfig.BRAND_NAME
    THEME = ProjectConfig.EMAIL_THEME

    def _support_email(self) -> str:
        return ProjectConfig.SUPPORT_EMAIL

    def _get_logo_image(self) -> MIMEImage | None:
        logo_path = Credentials.directory + "/logo.png"

        try:
            with open(logo_path, "rb") as logo_file:
                image = MIMEImage(logo_file.read())
        except OSError:
            return None

        image.add_header("Content-ID", "<logo>")
        image.add_header("Content-Disposition", "inline", filename="logo.png")
        return image

    def smtp_host(self) -> str:
        if Credentials.smtp_host:
            return Credentials.smtp_host

        if Credentials.smtp_provider.lower() == "gmail":
            return "smtp.gmail.com"

        return f"smtp.{Credentials.smtp_provider}.com"

    def get_gmail_access_token(self) -> str | None:
        client_id = Credentials.smtp_oauth_client_id
        client_secret = Credentials.smtp_oauth_client_secret
        refresh_token = Credentials.smtp_oauth_refresh_token

        if not client_id or not client_secret or not refresh_token:
            return None

        payload = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")

        request = Request(
            "https://oauth2.googleapis.com/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=10) as response:
                response_data = json.loads(response.read().decode("utf-8"))
                return response_data.get("access_token")
        except OSError:
            return None

    def _xoauth2_auth_string(self, smtp_email: str, access_token: str) -> str:
        auth_string = f"user={smtp_email}\x01auth=Bearer {access_token}\x01\x01"
        return base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

    def send_email(
        self,
        receiver_email: str,
        subject: str,
        html_message: str,
        image: MIMEImage | None = None,
    ) -> bool:
        smtp_email = Credentials.smtp_email
        smtp_provider = Credentials.smtp_provider
        smtp_host = self.smtp_host()
        smtp_port = Credentials.smtp_port
        use_ssl = Credentials.smtp_use_ssl

        if not smtp_email or not smtp_provider:
            return False

        if smtp_provider.lower() != "gmail":
            return False

        if image is None:
            image = self._get_logo_image()

        message = MIMEMultipart("related")
        message["From"] = smtp_email
        message["To"] = receiver_email
        message["Subject"] = subject

        alternative = MIMEMultipart("alternative")
        message.attach(alternative)

        plain_text = f"{subject}\n\nPlease open this email in an HTML-compatible email client."
        alternative.attach(MIMEText(plain_text, "plain"))
        alternative.attach(MIMEText(html_message, "html"))

        if image:
            message.attach(image)

        server = None
        try:
            if use_ssl:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port)

            server.ehlo()
            if not use_ssl:
                server.starttls()
                server.ehlo()

            access_token = self.get_gmail_access_token()
            if not access_token:
                return False

            xoauth2 = self._xoauth2_auth_string(smtp_email, access_token)
            response_code, _ = server.docmd("AUTH", f"XOAUTH2 {xoauth2}")
            if response_code != 235:
                return False

            server.sendmail(smtp_email, receiver_email, message.as_string())
            return True
        except (smtplib.SMTPException, OSError, ValueError):
            return False
        finally:
            if server:
                server.quit()

    def _get_modern_email_style(self) -> str:
        return f"""
            body {{
                margin: 0;
                padding: 20px;
                background-color: {self.THEME['background_light']};
                font-family: Arial, Helvetica, sans-serif;
                color: {self.THEME['text_primary']};
            }}

            .container {{
                background-color: {self.THEME['white']};
                border-radius: 12px;
                max-width: 560px;
                margin: 0 auto;
                overflow: hidden;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
            }}

            .illustration {{
                width: 100%;
                background: linear-gradient(135deg, {self.THEME['primary_color']} 0%, {self.THEME['primary_dark']} 100%);
                text-align: center;
                padding: 22px 18px;
            }}

            .illustration img {{
                width: 220px !important;
                max-width: 72% !important;
                height: auto !important;
                display: block;
                margin: 0 auto;
            }}

            .content {{
                padding: 36px 28px;
                text-align: center;
            }}

            h1 {{
                font-size: 28px;
                color: {self.THEME['primary_color']};
                margin: 0 0 16px 0;
                font-weight: 700;
                line-height: 1.3;
            }}

            .description {{
                font-size: 15px;
                color: {self.THEME['text_primary']};
                line-height: 1.6;
                margin: 0 0 28px 0;
            }}

            .cta-button {{
                display: inline-block;
                background-color: {self.THEME['primary_color']};
                color: #ffffff !important;
                text-decoration: none;
                padding: 14px 32px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
            }}

            .credentials-container {{
                background: linear-gradient(135deg, {self.THEME['background_light']} 0%, {self.THEME['white']} 100%);
                border: 1px solid {self.THEME['border_color']};
                border-radius: 10px;
                padding: 24px;
                margin-bottom: 32px;
                text-align: left;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
            }}

            .credential-row {{
                margin-bottom: 18px;
            }}

            .credential-row:last-child {{
                margin-bottom: 0;
            }}

            .credential-label {{
                font-size: 12px;
                color: {self.THEME['primary_darker']};
                font-weight: 800;
                margin-bottom: 8px;
                display: block;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }}

            .credential-value {{
                display: block;
                background-color: {self.THEME['background_box']};
                border: 1px solid {self.THEME['border_color']};
                border-radius: 8px;
                padding: 13px 16px;
                font-size: 16px;
                font-weight: 800;
                color: {self.THEME['primary_dark']};
                word-break: break-word;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
            }}

            .otp-container {{
                text-align: center;
                margin: 20px 0 10px 0;
            }}

            .otp-box {{
                display: inline-block;
                width: 46px;
                height: 46px;
                line-height: 46px;
                text-align: center;
                margin: 0 4px 8px;
                font-size: 22px;
                font-weight: 800;
                color: {self.THEME['primary_dark']};
                background-color: {self.THEME['background_box']};
                border: 2px solid {self.THEME['primary_color']};
                border-radius: 8px;
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
            }}

            .otp-text {{
                display: inline-block;
                margin-top: 8px;
                background-color: {self.THEME['background_light']};
                border: 1px dashed {self.THEME['border_color']};
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 18px;
                font-weight: bold;
                letter-spacing: 4px;
                color: {self.THEME['primary_dark']};
            }}

            .expiry-note {{
                font-size: 13px;
                color: {self.THEME['primary_dark']};
                background-color: {self.THEME['background_light']};
                border-left: 4px solid {self.THEME['primary_color']};
                padding: 12px 15px;
                margin: 24px 0 8px;
                border-radius: 4px;
                text-align: left;
                line-height: 1.5;
            }}

            .footer-section {{
                background-color: {self.THEME['footer_bg']};
                padding: 20px;
                text-align: center;
                border-top: 1px solid {self.THEME['border_color']};
            }}

            .footer-text {{
                font-size: 13px;
                color: {self.THEME['text_secondary']};
                margin: 0 0 12px 0;
                line-height: 1.6;
            }}

            .footer-text a {{
                color: {self.THEME['primary_color']};
                text-decoration: none;
                font-weight: bold;
            }}

            .copyright {{
                font-size: 11px;
                color: {self.THEME['text_secondary']};
                margin-top: 12px;
            }}

            @media only screen and (max-width: 600px) {{
                body {{
                    padding: 10px;
                }}

                .content {{
                    padding: 18px 18px;
                }}

                h1 {{
                    font-size: 24px;
                }}

                .description {{
                    font-size: 14px;
                }}

                .otp-box {{
                    width: 38px;
                    height: 38px;
                    line-height: 38px;
                    font-size: 18px;
                }}

                .illustration img {{
                    width: 170px !important;
                    max-width: 78% !important;
                }}
            }}
        """

    def _get_header_section(self) -> str:
        return f"""
            <div class="illustration">
                <img src="cid:logo" alt="{self.BRAND_NAME} Logo" width="220" style="display:block; margin:0 auto; width:220px; max-width:72%; height:auto;" />
            </div>
        """

    def _get_footer_section(self, footer_text: str) -> str:
        return f"""
            <div class="footer-section">
                <p class="footer-text">{footer_text}</p>
                <p class="footer-text">This is an automated message. Please do not reply.</p>
                <div class="copyright">
                    © {datetime.now().year} {self.BRAND_NAME}. All rights reserved.
                </div>
            </div>
        """

    def _wrap_email(self, content_html: str, footer_text: str) -> str:
        return f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    {self._get_modern_email_style()}
                </style>
            </head>
            <body>
                <div class="container">
                    {self._get_header_section()}
                    <div class="content">
                        {content_html}
                    </div>
                    {self._get_footer_section(footer_text)}
                </div>
            </body>
            </html>
        """

    def generate_add_user_email_html(self, receiver_email: str, password: str) -> str:
        login_url = Credentials.redirect_url + "/login"
        support_email = self._support_email()

        content_html = f"""
            <h1>Welcome to {self.BRAND_NAME}</h1>
            <p class="description">
                Your account has been created successfully. Use the credentials below to log in to the portal.
            </p>

            <div class="credentials-container">
                <div class="credential-row">
                    <span class="credential-label">Email</span>
                    <span class="credential-value">{receiver_email.lower()}</span>
                </div>
                <div class="credential-row">
                    <span class="credential-label">Password</span>
                    <span class="credential-value">{password}</span>
                </div>
            </div>

            <a href="{login_url}" target="_blank" class="cta-button">
                Login to {self.BRAND_NAME}
            </a>
        """

        footer_text = f'If you did not request this, please <a href="mailto:{support_email}">contact support</a>.'
        return self._wrap_email(content_html, footer_text)

    def generate_forget_password_otp_email_html(self, otp: str) -> str:
        clean_otp = otp[:6]

        content_html = f"""
            <h1>Password Reset Request</h1>
            <p class="description">
                We received a request to reset your password. Use the OTP below to proceed.
            </p>

            <div class="otp-container">
                {''.join([f'<span class="otp-box">{char}</span>' for char in clean_otp])}
            </div>

            <div class="expiry-note">
                <strong>Expires soon:</strong> This OTP will expire in 5 minutes.
                If it expires, you can request a new one from the portal.
            </div>
        """

        footer_text = "If you did not request a password reset, you can safely ignore this email."
        return self._wrap_email(content_html, footer_text)

    def send_add_user_email(self, receiver_email: str, password: str) -> bool:
        subject = f"Welcome to {self.BRAND_NAME}"
        html_message = self.generate_add_user_email_html(receiver_email, password)
        return self.send_email(receiver_email, subject, html_message)

    def send_forgot_password_otp_email(self, receiver_email: str, otp: str) -> bool:
        subject = f"{self.BRAND_NAME} Password Reset OTP"
        html_message = self.generate_forget_password_otp_email_html(otp)
        return self.send_email(receiver_email, subject, html_message)
