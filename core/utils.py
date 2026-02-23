from django.core.mail import EmailMessage

def send_verification_email(email, token):
    
    verification_url = f"http://localhost:8000/api/verify-link?token={token}&email={email}"
    
    subject = "Let's get you started!"
    
    html_content = f"""
        <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello User,</h2>
                        <p>Thank you for registering. Please click the button below to verify your email address:</p>
                        
                        <!-- Bulletproof Button -->
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{verification_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        Verify Email
                                    </a>
                                </td>
                            </tr>
                        </table>
                        
                        <p>If you did not register, please ignore this email.</p>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
    """
    
    email_message = EmailMessage(
        subject=subject,
        body=html_content,
        to=[email]
    )
    
    email_message.content_subtype = "html"
    email_message.send()