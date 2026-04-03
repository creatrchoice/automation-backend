"""
Email service using Resend API.

Handles team invitation emails and other transactional emails.
"""
import logging
import resend
from app.core.config import dm_settings as settings

logger = logging.getLogger(__name__)

# Initialize Resend
resend.api_key = settings.RESEND_API_KEY


def _from_address() -> str:
    """Build the From header, e.g. 'Sharda <sharda@creatrchoice.info>'."""
    return f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>"


async def send_invitation_email(
    to_email: str,
    inviter_name: str,
    org_name: str,
    role: str,
    invite_link: str,
) -> dict:
    """
    Send a team invitation email.

    Args:
        to_email: Recipient email address
        inviter_name: Name of the person sending the invite
        org_name: Organization name
        role: Role being assigned (e.g. "editor")
        invite_link: Full URL for the accept-invite page

    Returns:
        Resend API response dict (contains 'id')

    Raises:
        Exception: On send failure
    """
    subject = f"{inviter_name} invited you to join {org_name} on CreatrChoice"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
    </head>
    <body style="margin:0; padding:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f4f4f5;">
      <table width="100%" cellpadding="0" cellspacing="0" style="padding: 40px 20px;">
        <tr>
          <td align="center">
            <table width="480" cellpadding="0" cellspacing="0" style="background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
              <!-- Header -->
              <tr>
                <td style="padding: 32px 32px 0 32px;">
                  <h2 style="margin: 0 0 4px 0; font-size: 20px; color: #18181b;">You're invited!</h2>
                  <p style="margin: 0; color: #71717a; font-size: 14px;">Join the team on CreatrChoice</p>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding: 24px 32px;">
                  <p style="margin: 0 0 16px; font-size: 15px; color: #27272a; line-height: 1.6;">
                    <strong>{inviter_name}</strong> has invited you to join
                    <strong>{org_name}</strong> as a <strong>{role.capitalize()}</strong>.
                  </p>
                  <p style="margin: 0 0 24px; font-size: 14px; color: #52525b; line-height: 1.5;">
                    Click the button below to accept the invitation and get started.
                    This link will expire in {settings.INVITE_TOKEN_EXPIRY_HOURS} hours.
                  </p>
                  <!-- CTA Button -->
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td align="center">
                        <a href="{invite_link}"
                           style="display: inline-block; padding: 12px 32px; background-color: #18181b; color: #ffffff;
                                  font-size: 14px; font-weight: 600; text-decoration: none; border-radius: 8px;">
                          Accept Invitation
                        </a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="padding: 20px 32px 32px; border-top: 1px solid #f4f4f5;">
                  <p style="margin: 0; font-size: 12px; color: #a1a1aa; line-height: 1.5;">
                    If you didn't expect this invitation, you can safely ignore this email.
                    <br />This link can only be used once.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    try:
        params = {
            "from": _from_address(),
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }

        result = resend.Emails.send(params)
        logger.info(f"Invitation email sent to {to_email} (resend id: {result.get('id', 'unknown')})")
        return result

    except Exception as e:
        logger.error(f"Failed to send invitation email to {to_email}: {e}")
        raise
