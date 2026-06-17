import resend
from app.core.config import settings
from app.core.logging import logger

if settings.EMAIL_API_KEY:
    resend.api_key = settings.EMAIL_API_KEY

async def send_verification_email(to_email: str, token: str) -> None:
    # Build verification link assuming frontend is on localhost:3000 or the same domain as the app
    # A cleaner way is using an APP_URL setting, but we default to localhost:3000
    app_url = "http://localhost:3000"
    verification_link = f"{app_url}/verify-email?token={token}"
    
    html_content = f"""
    <h2>Verify your Email Address</h2>
    <p>Thank you for registering. Please click the link below to verify your email address:</p>
    <a href="{verification_link}">Verify Email</a>
    <p>If you did not request this, please ignore this email.</p>
    """

    # If the API key is provided, attempt to send via Resend
    if settings.EMAIL_API_KEY:
        try:
            r = resend.Emails.send({
                "from": settings.EMAIL_FROM_ADDRESS,
                "to": to_email,
                "subject": "Verify your email address",
                "html": html_content
            })
            logger.info(f"Verification email sent to {to_email}. Response: {r}")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            raise e
    else:
        # Fallback console logger for development without an API key
        logger.warning(f"EMAIL_API_KEY not set. Mock sending verification email to {to_email}.")
        logger.warning(f"Verification Link: {verification_link}")
