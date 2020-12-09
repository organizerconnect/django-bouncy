"""Views for the django_bouncy app"""
import json
try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse

import re
import logging

from django.http import HttpResponseBadRequest, HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from django_bouncy.utils import (
    verify_notification, approve_subscription, clean_time
)
from django_bouncy.models import Bounce, Complaint, Delivery, Open, Click, Send, Reject, RenderingFailure, DeliveryDelay
from django_bouncy import signals

VITAL_NOTIFICATION_FIELDS = [
    'Type', 'Message', 'Timestamp', 'Signature',
    'SignatureVersion', 'TopicArn', 'MessageId',
    'SigningCertURL'
]

ALLOWED_TYPES = [
    'Notification', 'SubscriptionConfirmation', 'UnsubscribeConfirmation'
]
logger = logging.getLogger(__name__)


@csrf_exempt
def endpoint(request):
    """Endpoint that SNS accesses. Includes logic verifying request"""
    # pylint: disable=too-many-return-statements,too-many-branches

    # In order to 'hide' the endpoint, all non-POST requests should return
    # the site's default HTTP404
    if request.method != 'POST':
        raise Http404

    # If necessary, check that the topic is correct
    if hasattr(settings, 'BOUNCY_TOPIC_ARN'):
        # Confirm that the proper topic header was sent
        if 'HTTP_X_AMZ_SNS_TOPIC_ARN' not in request.META:
            return HttpResponseBadRequest('No TopicArn Header')

        # Check to see if the topic is in the settings
        # Because you can have bounces and complaints coming from multiple
        # topics, BOUNCY_TOPIC_ARN is a list
        if (not request.META['HTTP_X_AMZ_SNS_TOPIC_ARN']
                in settings.BOUNCY_TOPIC_ARN):
            return HttpResponseBadRequest('Bad Topic')

    # Load the JSON POST Body
    if isinstance(request.body, str):
        # requests return str in python 2.7
        request_body = request.body
    else:
        # and return bytes in python 3.4
        request_body = request.body.decode()
    try:
        data = json.loads(request_body)
    except ValueError:
        logger.warning('Notification Not Valid JSON: {}'.format(request_body))
        return HttpResponseBadRequest('Not Valid JSON')

    # Ensure that the JSON we're provided contains all the keys we expect
    # Comparison code from http://stackoverflow.com/questions/1285911/
    if not set(VITAL_NOTIFICATION_FIELDS) <= set(data):
        logger.warning('Request Missing Necessary Keys')
        return HttpResponseBadRequest('Request Missing Necessary Keys')

    # Ensure that the type of notification is one we'll accept
    if not data['Type'] in ALLOWED_TYPES:
        logger.info('Notification Type Not Known %s', data['Type'])
        return HttpResponseBadRequest('Unknown Notification Type')

    # Confirm that the signing certificate is hosted on a correct domain
    # AWS by default uses sns.{region}.amazonaws.com
    # On the off chance you need this to be a different domain, allow the
    # regex to be overridden in settings
    domain = urlparse(data['SigningCertURL']).netloc
    pattern = getattr(
        settings, 'BOUNCY_CERT_DOMAIN_REGEX', r"sns.[a-z0-9\-]+.amazonaws.com$"
    )
    if not re.search(pattern, domain):
        logger.warning(
            'Improper Certificate Location %s', data['SigningCertURL'])
        return HttpResponseBadRequest('Improper Certificate Location')

    # Verify that the notification is signed by Amazon
    if (getattr(settings, 'BOUNCY_VERIFY_CERTIFICATE', True)
            and not verify_notification(data)):
        logger.error('Verification Failure %s', )
        return HttpResponseBadRequest('Improper Signature')

    # Send a signal to say a valid notification has been received
    signals.notification.send(
        sender='bouncy_endpoint', notification=data, request=request)

    # Handle subscription-based messages.
    if data['Type'] == 'SubscriptionConfirmation':
        # Allow the disabling of the auto-subscription feature
        if not getattr(settings, 'BOUNCY_AUTO_SUBSCRIBE', True):
            raise Http404
        return approve_subscription(data)
    elif data['Type'] == 'UnsubscribeConfirmation':
        # We won't handle unsubscribe requests here. Return a 200 status code
        # so Amazon won't redeliver the request. If you want to remove this
        # endpoint, remove it either via the API or the AWS Console
        logger.info('UnsubscribeConfirmation Not Handled')
        return HttpResponse('UnsubscribeConfirmation Not Handled')

    try:
        message = json.loads(data['Message'])
    except ValueError:
        # This message is not JSON. But we need to return a 200 status code
        # so that Amazon doesn't attempt to deliver the message again
        logger.info('Non-Valid JSON Message Received')
        return HttpResponse('Message is not valid JSON')

    return process_message(message, data)


def has_vital_fields(message):
    return 'mail' in message and ('eventType' in message or 'notificationType' in message)


def process_message(message, notification):
    """
    Function to process a JSON message delivered from Amazon
    """
    # Confirm that there are 'mail' and either 'eventType' or 'notificationType'
    # fields in our message
    if not has_vital_fields(message):
        # At this point we're sure that it's Amazon sending the message
        # If we don't return a 200 status code, Amazon will attempt to send us
        # this same message a few seconds later.
        logger.info('JSON Message Missing Vital Fields')
        return HttpResponse('Missing Vital Fields')

    message_type = message.get('eventType') or message.get('notificationType')

    if message_type == 'Complaint':
        return process_complaint(message, notification)
    if message_type == 'Bounce':
        return process_bounce(message, notification)
    if message_type == 'Delivery':
        return process_delivery(message, notification)
    if message_type == 'Open':
        return process_open(message, notification)
    if message_type == 'Click':
        return process_click(message, notification)
    if message_type == 'Send':
        return process_send(message, notification)
    if message_type == 'Reject':
        return process_reject(message, notification)
    if message_type == 'Rendering Failure':
        return process_rendering_failure(message, notification)
    if message_type == 'DeliveryDelay':
        return process_delivery_delay(message, notification)
    else:
        return HttpResponse('Unknown Notification Type')


def process_send(message, notification):
    mail = message['mail']

    sends = []
    for destination in mail['destination']:
        sends += [Send.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=destination
        )]

    for send in sends:
        signals.feedback.send(
            sender=Send,
            instance=send,
            message=message,
            notification=notification
        )

    return HttpResponse('Send Processed')


def process_bounce(message, notification):
    """Function to process a bounce notification"""
    mail = message['mail']
    bounce = message['bounce']

    bounces = []
    for recipient in bounce['bouncedRecipients']:
        # Create each bounce record. Add to a list for reference later.
        bounces += [Bounce.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=recipient['emailAddress'],
            feedback_id=bounce['feedbackId'],
            feedback_timestamp=clean_time(bounce['timestamp']),
            hard=bool(bounce['bounceType'] == 'Permanent'),
            bounce_type=bounce['bounceType'],
            bounce_subtype=bounce['bounceSubType'],
            reporting_mta=bounce.get('reportingMTA'),
            action=recipient.get('action'),
            status=recipient.get('status'),
            diagnostic_code=recipient.get('diagnosticCode')
        )]

    # Send signals for each bounce.
    for each_bounce in bounces:
        signals.feedback.send(
            sender=Bounce,
            instance=each_bounce,
            message=message,
            notification=notification
        )

    logger.info('Logged %s Bounce(s)', str(len(bounces)))

    return HttpResponse('Bounce Processed')


def process_complaint(message, notification):
    """Function to process a complaint notification"""
    mail = message['mail']
    complaint = message['complaint']

    if 'arrivalDate' in complaint:
        arrival_date = clean_time(complaint['arrivalDate'])
    else:
        arrival_date = None

    complaints = []
    for recipient in complaint['complainedRecipients']:
        # Create each Complaint. Save in a list for reference later.
        complaints += [Complaint.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=recipient['emailAddress'],
            feedback_id=complaint['feedbackId'],
            feedback_timestamp=clean_time(complaint['timestamp']),
            useragent=complaint.get('userAgent'),
            feedback_type=complaint.get('complaintFeedbackType'),
            arrival_date=arrival_date
        )]

    # Send signals for each complaint.
    for each_complaint in complaints:
        signals.feedback.send(
            sender=Complaint,
            instance=each_complaint,
            message=message,
            notification=notification
        )

    logger.info('Logged %s Complaint(s)', str(len(complaints)))

    return HttpResponse('Complaint Processed')


def process_delivery(message, notification):
    """Function to process a delivery notification"""
    mail = message['mail']
    delivery = message['delivery']

    if 'timestamp' in delivery:
        delivered_datetime = clean_time(delivery['timestamp'])
    else:
        delivered_datetime = None

    deliveries = []
    for each_recipient in delivery['recipients']:
        # Create each delivery 
        deliveries += [Delivery.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=each_recipient,
            # delivery
            delivered_time=delivered_datetime,
            processing_time=int(delivery['processingTimeMillis']),
            smtp_response=delivery['smtpResponse']
        )]

    # Send signals for each delivery.
    for each_delivery in deliveries:
        signals.feedback.send(
            sender=Delivery,
            instance=each_delivery,
            message=message,
            notification=notification
        )

    logger.info('Logged %s Deliveries(s)', str(len(deliveries)))

    return HttpResponse('Delivery Processed')


def process_open(message, notification):
    """Function to process an open notification"""
    mail = message['mail']
    open_ = message['open']

    if 'timestamp' in open_:
        opened_datetime = clean_time(open_['timestamp'])
    else:
        opened_datetime = None

    opens = []
    for destination in mail['destination']:
        opens += [Open.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            # open
            address=destination,
            opened_time=opened_datetime,
            ip_address=open_['ipAddress'],
            useragent=open_['userAgent']
        )]

    for each_open in opens:
        signals.feedback.send(
            sender=Open,
            instance=each_open,
            message=message,
            notification=notification
        )

    return HttpResponse('Open Processed')


def process_click(message, notification):
    """Function to process a click notification"""
    mail = message['mail']
    click = message['click']

    if 'timestamp' in click:
        clicked_datetime = clean_time(click['timestamp'])
    else:
        clicked_datetime = None

    clicks = []
    for destination in mail['destination']:
        clicks += [Click.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=destination,
            # click
            clicked_time=clicked_datetime,
            ip_address=click['ipAddress'],
            useragent=click['userAgent'],
            link=click['link'],
            link_tags=click['linkTags']
        )]

    for each_click in clicks:
        signals.feedback.send(
            sender=Click,
            instance=each_click,
            message=message,
            notification=notification
        )

    return HttpResponse('Click Processed')


def process_reject(message, notification):
    """Function to process a reject notification"""
    mail = message['mail']
    reject = message['reject']

    rejects = []
    for destination in mail['destination']:
        rejects += [Reject.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=destination,
            # reject
            reason=reject['reason']
        )]

    for each_reject in rejects:
        signals.feedback.send(
            sender=Reject,
            instance=each_reject,
            message=message,
            notification=notification
        )

    return HttpResponse('Reject Processed')


def process_rendering_failure(message, notification):
    """Function to process a rendering failure notification"""
    mail = message['mail']
    rendering_failure = message['failure']

    rendering_failures = []
    for destination in mail['destination']:
        rendering_failures += [RenderingFailure.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=destination,
            # rendering failure
            template_name=rendering_failure['templateName'],
            error_message=rendering_failure['errorMessage']
        )]

    for each_rendering_failure in rendering_failures:
        signals.feedback.send(
            sender=RenderingFailure,
            instance=each_rendering_failure,
            message=message,
            notification=notification
        )

    return HttpResponse('Rendering Failure Processed')


def process_delivery_delay(message, notification):
    """Function to process a delivery delay notification"""
    mail = message['mail']
    delivery_delay = message['deliveryDelay']

    delivery_delays = []
    for delayed_recipient in delivery_delay['delayedRecipients']:
        delivery_delays += [DeliveryDelay.objects.create(
            sns_topic=notification['TopicArn'],
            sns_messageid=notification['MessageId'],
            mail_timestamp=clean_time(mail['timestamp']),
            mail_id=mail['messageId'],
            mail_from=mail['source'],
            address=delayed_recipient['emailAddress'],
            # delivery delay
            delayed_time=clean_time(delivery_delay['timestamp']),
            delay_type=delivery_delay['delayType'],
            expiration_time=clean_time(delivery_delay['expirationTime']),
            reporting_mta=delivery_delay.get('reportingMTA'),
            status=delayed_recipient['status'],
            diagnostic_code=delayed_recipient['diagnosticCode']
        )]

    for each_delivery_delay in delivery_delays:
        signals.feedback.send(
            sender=DeliveryDelay,
            instance=each_delivery_delay,
            message=message,
            notification=notification
        )

    return HttpResponse('Delivery Delay Processed')
