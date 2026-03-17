import os
from datetime import timedelta

from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone
from dotenv import load_dotenv

from tickets.models import Ticket, TicketSubscriber

load_dotenv()
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL")


@shared_task(bind=True, max_retries=3)
def send_ticket_assignment_email(
    self, email, ticket_id, ticket_title, project_id, project_title
):
    """
    Sends an email notification to a user when they are assigned to a ticket.
    Copies all active ticket subscribers on the email.
    """
    ticket_url = f"{FRONTEND_BASE_URL}/project/{project_id}/tickets/{ticket_id}"
    subject = f"Ticket Assigned: {ticket_title}"

    html_content = f"""
        <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>You have been assigned to a new ticket in the project <strong>{project_title}</strong>.</p>
                        <p><strong>Ticket Title:</strong> {ticket_title}</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
                                    </a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
    """

    subscribers = TicketSubscriber.objects.filter(
        ticket_id=ticket_id, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    cc_emails = [
        sub.user.email
        for sub in subscribers
        if sub.user.email and sub.user.email != email
    ]

    email_message = EmailMessage(
        subject=subject,
        body=html_content,
        to=[email],
        cc=cc_emails,
    )

    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def notify_ticket_subscribers(self, ticket_id, changes):
    """
    Sends an email notification to all active subscribers detailing what fields
    changed during a ticket update.
    """
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    subscribers = TicketSubscriber.objects.filter(
        ticket=ticket, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    emails = [sub.user.email for sub in subscribers if sub.user.email]

    if not emails:
        return

    ticket_url = f"{FRONTEND_BASE_URL}/project/{ticket.project.id}/tickets/{ticket.id}"
    subject = f"Ticket Updated: {ticket.title}"

    changes_html = "<ul>"
    for change in changes:
        changes_html += f"<li style='margin-bottom: 8px;'><strong>{change['field']}:</strong> <br><span style='color: #dc3545; text-decoration: line-through;'>{change['old']}</span> &rarr; <span style='color: #28a745;'>{change['new']}</span></li>"
    changes_html += "</ul>"

    html_content = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>A ticket you are subscribed to has been updated.</p>
                        <p><strong>Ticket:</strong> {ticket.title}</p>
                        
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                            <h3 style="margin-top: 0;">What Changed:</h3>
                            {changes_html}
                        </div>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
                                    </a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    </table>
    """
    primary_email = emails[0]
    cc_emails = emails[1:] if len(emails) > 1 else []

    email_message = EmailMessage(
        subject=subject, body=html_content, to=[primary_email], cc=cc_emails
    )
    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def notify_reporter_resolved(self, reporter_email, ticket_title, ticket_id, project_id):
    """
    Sends an email notification to the original reporter when a ticket is marked as Resolved,
    prompting them to verify and close it. Copies all active subscribers.
    """
    ticket_url = f"{FRONTEND_BASE_URL}/project/{project_id}/tickets/{ticket_id}"
    subject = f"Resolved: {ticket_title}"

    html_content = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>Great news! A ticket you reported has been marked as <strong>Resolved</strong>.</p>
                        <p><strong>Ticket Title:</strong> {ticket_title}</p>
                        <p>Please review the ticket to confirm the issue is fixed. If everything looks good, you can now mark it as Closed.</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#28a745" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
                                    </a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    </table>
    """

    subscribers = TicketSubscriber.objects.filter(
        ticket_id=ticket_id, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    cc_emails = [
        sub.user.email
        for sub in subscribers
        if sub.user.email and sub.user.email != reporter_email
    ]

    email_message = EmailMessage(
        subject=subject,
        body=html_content,
        to=[reporter_email],
        cc=cc_emails,
    )

    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def send_deadline_reminder(self, ticket_id, is_two_hour=False):
    """
    Sends a deadline reminder email to the assignee, reporter, and subscribers.
    Automatically schedules a follow-up 2-hour reminder if applicable.
    """
    try:
        ticket = Ticket.objects.select_related("assignee", "reporter", "project").get(
            id=ticket_id
        )
    except Ticket.DoesNotExist:
        return f"Ticket {ticket_id} no longer exists. Task aborted."

    to_emails = []
    cc_emails = []

    if ticket.assignee and ticket.assignee.email:
        to_emails.append(ticket.assignee.email)
        if ticket.reporter and ticket.reporter.email:
            cc_emails.append(ticket.reporter.email)
    else:
        if ticket.reporter and ticket.reporter.email:
            to_emails.append(ticket.reporter.email)

    subscribers = TicketSubscriber.objects.filter(
        ticket=ticket, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    for sub in subscribers:
        sub_email = sub.user.email
        if sub_email and sub_email not in to_emails and sub_email not in cc_emails:
            cc_emails.append(sub_email)

    if not to_emails and cc_emails:
        to_emails.append(cc_emails.pop(0))

    assignee_name = ticket.assignee.email if ticket.assignee else "Unassigned"

    ticket_url = f"{FRONTEND_BASE_URL}/projects/{ticket.project.id}/tickets/{ticket.id}"

    if ticket.status == Ticket.Status.RESOLVED:
        status_msg = (
            "This ticket is marked as RESOLVED. Please verify if it can be closed."
        )
    else:
        status_msg = "Please ensure the required work is completed on time."

    if is_two_hour:
        subject = f"Urgent Deadline Reminder: {ticket.title} (Due in 2 hours)"
        time_text = "is due in approximately <b>2 hours</b>"
    else:
        subject = f"Deadline Reminder: {ticket.title}"
        time_text = "has a deadline of <b>tomorrow</b>"

    message = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5" style="font-family: Arial, sans-serif;">
        <tr>
            <td align="center" style="padding: 20px;">
                <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                    <tr>
                        <td>
                            <h2>Hello,</h2>
                            <p>This is an automated reminder that the ticket <b>'{ticket.title}'</b> in project <b>'{ticket.project.title}'</b> {time_text} ({ticket.deadline}).</p>
                            
                            <p>
                                <strong>Assignee:</strong> {assignee_name}<br>
                                <strong>Current Status:</strong> {ticket.get_status_display()}
                            </p>
                            
                            <p>{status_msg}</p>
                            
                            <table cellspacing="0" cellpadding="0" border="0" style="margin-top: 20px;">
                                <tr>
                                    <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                        <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                            View Ticket
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
    """

    email = EmailMessage(
        subject=subject,
        body=message,
        to=to_emails,
        cc=cc_emails,
    )
    email.content_subtype = "html"
    email.send(fail_silently=False)

    if not is_two_hour:
        two_hours_before = ticket.deadline - timedelta(hours=2)

        if two_hours_before > timezone.now():
            next_task = send_deadline_reminder.apply_async(
                args=[ticket.id], kwargs={"is_two_hour": True}, eta=two_hours_before
            )
            ticket.reminder_task_id = next_task.id
        else:
            ticket.reminder_task_id = None
    else:
        ticket.reminder_task_id = None

    ticket.save(update_fields=["reminder_task_id"])


@shared_task(bind=True, max_retries=3)
def notify_new_subscriber(self, ticket_id, new_subscriber_email, new_subscriber_name):
    """
    Sends an email to existing subscribers when a new user subscribes to the ticket.
    """
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    subscribers = TicketSubscriber.objects.filter(
        ticket=ticket, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    notify_emails = [
        sub.user.email
        for sub in subscribers
        if sub.user.email and sub.user.email != new_subscriber_email
    ]

    if not notify_emails:
        return

    ticket_url = f"{FRONTEND_BASE_URL}/project/{ticket.project.id}/tickets/{ticket.id}"
    subject = f"New Subscriber on Ticket: {ticket.title}"

    html_content = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p><strong>{new_subscriber_name}</strong> has just subscribed to a ticket you are following.</p>
                        <p><strong>Ticket:</strong> {ticket.title}</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0" style="margin-top: 20px;">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
                                    </a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    </table>
    """

    primary_email = notify_emails[0]
    cc_emails = notify_emails[1:] if len(notify_emails) > 1 else []

    email_message = EmailMessage(
        subject=subject, body=html_content, to=[primary_email], cc=cc_emails
    )

    email_message.content_subtype = "html"
    email_message.send()
