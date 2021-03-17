"""Tests for views.py in the django-bouncy app"""
# pylint: disable=protected-access
import json

from django.test import RequestFactory
from django.test.utils import override_settings
from django.http import Http404
from django.conf import settings
from django.dispatch import receiver
try:
    # Python 2.6/2.7
    from mock import patch
except ImportError:
    # Python 3
    # from unittest.mock import patch
    from mock import patch

from django_bouncy.tests.helpers import BouncyTestCase, loader
from django_bouncy import views, signals
from django_bouncy.utils import clean_time
from django_bouncy.models import Bounce, Complaint, Delivery, Send, Open, Click, Reject, RenderingFailure, DeliveryDelay


class BouncyEndpointViewTest(BouncyTestCase):
    """Test the endpoint view"""
    def setUp(self):
        """Setup the test"""
        self.factory = RequestFactory()
        self.request = self.factory.post('/')
        self.request.META['HTTP_X_AMZ_SNS_TOPIC_ARN'] = \
            settings.BOUNCY_TOPIC_ARN[0]

    def test_non_post_http404(self):
        """Test that GET requests to the endpoint throw a 404"""
        request = self.factory.get('/')
        with self.assertRaises(Http404):
            views.endpoint(request)

    def test_success(self):
        """Test a successful request"""
        self.request._body = json.dumps(self.notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Bounce Processed')

    def test_signals_sent(self):
        """
        Test that a notification feedback signal was sent

        Based on http://stackoverflow.com/questions/3817213/
        """
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.request._body = json.dumps(self.notification)
        self.signal_count = 0

        @receiver(signals.notification)
        def _signal_receiver(sender, **kwargs):
            """Signal test receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_request = kwargs['request']

        result = views.endpoint(self.request)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_request, self.request)
        self.assertEqual(self.signal_notification, self.notification)

    @override_settings(BOUNCY_TOPIC_ARN=['Bad ARN'])
    def test_bad_topic(self):
        """Test the response if the topic does not match the settings"""
        self.request._body = json.dumps(self.notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.content.decode('ascii'), 'Bad Topic')

    def test_no_header(self):
        """Test the results if the request does not have a topic header"""
        request = self.factory.post('/')
        request._body = json.dumps(self.notification)
        result = views.endpoint(request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.content.decode('ascii'), 'No TopicArn Header')

    def test_invalid_json(self):
        """Test if the notification does not have a JSON body"""
        self.request._body = "This Is Not JSON"
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.content.decode('ascii'), 'Not Valid JSON')

    def test_missing_necessary_key(self):
        """Test if the notification is missing vital keys"""
        self.request._body = json.dumps({})
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(
            result.content.decode('ascii'), 'Request Missing Necessary Keys')

    def test_unknown_notification_type(self):
        """Test an unknown notification type"""
        notification = loader('bounce_notification')
        notification['Type'] = 'NotAKnownType'
        self.request._body = json.dumps(notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(
            result.content.decode('ascii'), 'Unknown Notification Type')

    def test_bad_certificate_url(self):
        """Test an unknown certificate hostname"""
        notification = loader('bounce_notification')
        notification['SigningCertURL'] = 'https://baddomain.com/cert.pem'
        self.request._body = json.dumps(notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(
            result.content.decode('ascii'), 'Improper Certificate Location')

    def test_subscription_throws_404(self):
        """
        Test that a subscription request sent to bouncy throws a 404 if not
        permitted
        """
        original_setting = getattr(settings, 'BOUNCY_AUTO_SUBSCRIBE', True)
        settings.BOUNCY_AUTO_SUBSCRIBE = False
        with self.assertRaises(Http404):
            notification = loader('subscriptionconfirmation')
            self.request._body = json.dumps(notification)
            views.endpoint(self.request)
        settings.BOUNCY_AUTO_SUBSCRIBE = original_setting

    @patch('django_bouncy.views.approve_subscription')
    def test_approve_subscription_called(self, mock):
        """Test that a approve_subscription is called"""
        mock.return_value = 'Test Return Value'
        notification = loader('subscriptionconfirmation')
        self.request._body = json.dumps(notification)
        result = views.endpoint(self.request)
        self.assertTrue(mock.called)
        self.assertEqual(result, 'Test Return Value')

    def test_unsubscribe_confirmation_not_handled(self):
        """Test that an unsubscribe notification is properly ignored"""
        notification = loader('bounce_notification')
        notification['Type'] = 'UnsubscribeConfirmation'
        self.request._body = json.dumps(notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.content.decode('ascii'),
            'UnsubscribeConfirmation Not Handled'
        )

    def test_non_json_message_not_allowed(self):
        """Test that a non-JSON message is properly ignored"""
        notification = loader('bounce_notification')
        notification['Message'] = 'Non JSON Message'
        self.request._body = json.dumps(notification)
        result = views.endpoint(self.request)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.content.decode('ascii'), 'Message is not valid JSON')


class ProcessMessageTest(BouncyTestCase):
    """Test the process_message function"""
    def test_missing_fields(self):
        """Test that missing vital fields returns an error"""
        message = loader('bounce')
        del(message['mail'])
        result = views.process_message(message, self.notification)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.content.decode('ascii'), 'Missing Vital Fields')

    @patch('django_bouncy.views.process_complaint')
    def test_complaint(self, mock):
        """Test that a complaint is sent to process_complaint"""
        notification = loader('complaint_notification')
        views.process_message(self.complaint, notification)
        mock.assert_called_with(self.complaint, notification)

    @patch('django_bouncy.views.process_bounce')
    def test_bounce(self, mock):
        """Test that a bounce is sent to process_bounce"""
        views.process_message(self.bounce, self.notification)
        mock.assert_called_with(self.bounce, self.notification)

    def test_unknown_message(self):
        """Test a JSON message without a type returns an error"""
        message = loader('bounce')
        message['notificationType'] = 'Not A Valid Notification'
        result = views.process_message(message, self.notification)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.content.decode('ascii'), 'Unknown Notification Type')


class ProcessBounceTest(BouncyTestCase):
    """Test the process_bounce function"""
    def test_two_bounces_created(self):
        """Test that new bounces are added to the database"""
        original_count = Bounce.objects.count()
        result = views.process_bounce(self.bounce, self.notification)
        new_count = Bounce.objects.count()

        self.assertEqual(new_count, original_count + 2)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Bounce Processed')

    def test_signals_sent(self):
        """Test that a bounce feedback signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']

        result = views.process_bounce(self.bounce, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Bounce Processed')
        self.assertEqual(self.signal_count, 2)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_bounces_created(self):
        """Test to ensure that bounces are correctly inserted"""
        # Delete any existing bounces
        Bounce.objects.all().delete()

        result = views.process_bounce(self.bounce, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Bounce Processed')
        self.assertTrue(Bounce.objects.filter(
            sns_topic=('arn:aws:sns:us-east-1:250214102493:'
                       'Demo_App_Unsubscribes'),
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2012-06-19T01:05:45.000Z'),
            mail_id=('00000138111222aa-33322211-cccc-cccc-cccc-'
                     'ddddaaaa0680-000000'),
            mail_from='sender@example.com',
            address='recipient1@example.com',
            feedback_id=('000001378603176d-5a4b5ad9-6f30-4198-a8c3-'
                         'b1eb0c270a1d-000000'),
            feedback_timestamp=clean_time('2012-05-25T14:59:38.605-07:00'),
            hard=True,
            bounce_type='Permanent',
            bounce_subtype='General',
            reporting_mta='example.com',
            action='failed',
            status='5.0.0',
            diagnostic_code='smtp; 550 user unknown'
        ).exists())


class ProcessComplaintTest(BouncyTestCase):
    """Test the process_complaint function"""
    def setUp(self):
        self.complaint_notification = loader('complaint_notification')

    def test_complaints_created(self):
        """Test that a new complaint was added to the database"""
        original_count = Complaint.objects.count()
        result = views.process_complaint(
            self.complaint, self.complaint_notification)
        new_count = Complaint.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Complaint Processed')

    def test_signals_sent(self):
        """Test that a complaint feedback signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_complaint(
            self.complaint, self.complaint_notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Complaint Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.complaint_notification)

    def test_correct_complaint_created(self):
        """Test that the correct complaint was created"""
        Complaint.objects.all().delete()

        result = views.process_complaint(
            self.complaint, self.complaint_notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Complaint Processed')
        self.assertTrue(Complaint.objects.filter(
            sns_topic=('arn:aws:sns:us-east-1:250214102493:'
                       'Demo_App_Unsubscribes'),
            sns_messageid='217eaf35-67ae-5230-874a-e5df4c5c71c0',
            mail_timestamp=clean_time('2012-05-25T14:59:38.623-07:00'),
            mail_id=('000001378603177f-7a5433e7-8edb-42ae-af10-'
                     'f0181f34d6ee-000000'),
            mail_from='email_1337983178623@amazon.com',
            address='recipient1@example.com',
            feedback_id=('000001378603177f-18c07c78-fa81-4a58-9dd1-'
                         'fedc3cb8f49a-000000'),
            feedback_timestamp=clean_time('2012-05-25T14:59:38.623-07:00'),
            useragent='Comcast Feedback Loop (V0.01)',
            arrival_date=clean_time('2009-12-03T04:24:21.000-05:00')
        ).exists())


class ProcessDeliveryTest(BouncyTestCase):
    """Test the process_delivery function"""
    def setUp(self):
        """Setup the process delivery test"""
        self.delivery = loader('delivery')
        self.delivery_notification = loader('delivery_notification')

    def test_delivery_created(self):
        """Test that the Delivery object was created"""
        original_count = Delivery.objects.count()
        result = views.process_delivery(
            self.delivery, self.delivery_notification)
        new_count = Delivery.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Processed')

    def test_signals_sent(self):
        """Test that the django delivery signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_delivery(
            self.delivery, self.delivery_notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.delivery_notification)

    def test_correct_delivery_created(self):
        """Test that the correct delivery was created"""
        Delivery.objects.all().delete()

        result = views.process_delivery(
            self.delivery, self.delivery_notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Processed')
        self.assertTrue(Delivery.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:674400795651:Bouncy_Test',
            sns_messageid='fbdf2eda-c5ed-5096-a8d7-61a043f7db6e',
            mail_timestamp=clean_time('2014-05-28T22:40:59.638Z'),
            mail_id='0000014644fe5ef6-9a483358-9170-4cb4-a269-f5dcdf415321-000'
                    '000',
            mail_from='sender@example.com',
            address='success@simulator.amazonses.com',
            # delivery
            delivered_time=clean_time('2014-05-28T22:41:01.184Z'),
            processing_time=546,
            smtp_response='250 ok:  Message 64111812 accepted'
        ).exists())

    def test_correct_delivery_created_long_response_time(self):
        """Test that the correct delivery was created with a long processing_time"""
        Delivery.objects.all().delete()
        self.delivery['delivery']['processingTimeMillis'] = 123999123
        result = views.process_delivery(
            self.delivery, self.delivery_notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Processed')
        self.assertTrue(Delivery.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:674400795651:Bouncy_Test',
            sns_messageid='fbdf2eda-c5ed-5096-a8d7-61a043f7db6e',
            mail_timestamp=clean_time('2014-05-28T22:40:59.638Z'),
            mail_id='0000014644fe5ef6-9a483358-9170-4cb4-a269-f5dcdf415321-000'
                    '000',
            mail_from='sender@example.com',
            address='success@simulator.amazonses.com',
            # delivery
            delivered_time=clean_time('2014-05-28T22:41:01.184Z'),
            processing_time=123999123,
            smtp_response='250 ok:  Message 64111812 accepted'
        ).exists())


class ProcessSendTest(BouncyTestCase):
    def setUp(self):
        self.send = loader('send')

    def test_send_created(self):
        """Test that the Send object was created"""
        original_count = Send.objects.count()
        result = views.process_send(
            self.send, self.notification)
        new_count = Send.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Send Processed')

    def test_signals_sent(self):
        """Test that the django send signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_send(
            self.send, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Send Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_send_created(self):
        """Test that the correct delivery was created"""
        Send.objects.all().delete()

        result = views.process_send(
            self.send, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Send Processed')
        self.assertTrue(Send.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2016-10-14T05:02:16.645Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='recipient@example.com',
        ).exists())


class ProcessOpenTest(BouncyTestCase):
    def setUp(self):
        self.open = loader('open')

    def test_open_created(self):
        """Test that the Open object was created"""
        original_count = Open.objects.count()
        result = views.process_open(
            self.open, self.notification)
        new_count = Open.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Open Processed')

    def test_signals_sent(self):
        """Test that the django open signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_open(
            self.open, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Open Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_open_created(self):
        """Test that the correct open was created"""
        Open.objects.all().delete()

        result = views.process_open(
            self.open, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Open Processed')
        self.assertTrue(Open.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2017-08-09T21:59:49.927Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='recipient@example.com',
            opened_time=clean_time('2017-08-09T22:00:19.652Z'),
            ip_address='127.0.0.1',
            useragent='Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_3 like Mac OS X) AppleWebKit/603.3.8 (KHTML, like Gecko) Mobile/14G60'
        ).exists())


class ProcessClickTest(BouncyTestCase):
    def setUp(self):
        self.click = loader('click')

    def test_click_created(self):
        """Test that the Click object was created"""
        original_count = Click.objects.count()
        result = views.process_click(
            self.click, self.notification)
        new_count = Click.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Click Processed')

    def test_signals_sent(self):
        """Test that the django click signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_click(
            self.click, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Click Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_click_created(self):
        """Test that the correct click was created"""
        Click.objects.all().delete()

        result = views.process_click(
            self.click, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Click Processed')
        self.assertTrue(Click.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2017-08-09T23:50:05.795Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='recipient@example.com',
            clicked_time=clean_time('2017-08-09T23:51:25.570Z'),
            ip_address='62.251.97.95',
            useragent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36',
            link='http://docs.aws.amazon.com/ses/latest/DeveloperGuide/send-email-smtp.html',
            link_tags=json.loads('{"samplekey0": ["samplevalue0"], "samplekey1": ["samplevalue1"]}')
        ).exists())


class ProcessRejectTest(BouncyTestCase):
    def setUp(self):
        self.reject = loader('reject')

    def test_reject_created(self):
        """Test that the Reject object was created"""
        original_count = Reject.objects.count()
        result = views.process_reject(
            self.reject, self.notification)
        new_count = Reject.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Reject Processed')

    def test_signals_sent(self):
        """Test that the django reject signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_reject(
            self.reject, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Reject Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_reject_created(self):
        """Test that the correct reject was created"""
        Reject.objects.all().delete()

        result = views.process_reject(
            self.reject, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Reject Processed')
        self.assertTrue(Reject.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2016-10-14T17:38:15.211Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='sender@example.com',
            reason='Bad content'
        ).exists())


class ProcessRenderingFailureTest(BouncyTestCase):
    def setUp(self):
        self.rendering_failure = loader('rendering_failure')

    def test_rendering_failure_created(self):
        """Test that the RenderingFailure object was created"""
        original_count = RenderingFailure.objects.count()
        result = views.process_rendering_failure(
            self.rendering_failure, self.notification)
        new_count = RenderingFailure.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Rendering Failure Processed')

    def test_signals_sent(self):
        """Test that the django rendering failure signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_rendering_failure(
            self.rendering_failure, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Rendering Failure Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_rendering_failure_created(self):
        """Test that the correct rendering failure was created"""
        RenderingFailure.objects.all().delete()

        result = views.process_rendering_failure(
            self.rendering_failure, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Rendering Failure Processed')
        self.assertTrue(RenderingFailure.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2018-01-22T18:43:06.197Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='recipient@example.com',
            template_name='MyTemplate',
            error_message="Attribute 'attributeName' is not present in the rendering data."
        ).exists())


class ProcessDeliveryDelayTest(BouncyTestCase):
    def setUp(self):
        self.delivery_delay = loader('delivery_delay')

    def test_delivery_delay_created(self):
        """Test that the DeliveryDelay object was created"""
        original_count = DeliveryDelay.objects.count()
        result = views.process_delivery_delay(
            self.delivery_delay, self.notification)
        new_count = DeliveryDelay.objects.count()

        self.assertEqual(new_count, original_count + 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Delay Processed')

    def test_signals_sent(self):
        """Test that the django delivery delay signal was sent"""
        # pylint: disable=attribute-defined-outside-init, unused-variable
        self.signal_count = 0

        @receiver(signals.feedback)
        def _signal_receiver(sender, **kwargs):
            """Test signal receiver"""
            # pylint: disable=unused-argument
            self.signal_count += 1
            self.signal_notification = kwargs['notification']
            self.signal_message = kwargs['message']

        result = views.process_delivery_delay(
            self.delivery_delay, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Delay Processed')
        self.assertEqual(self.signal_count, 1)
        self.assertEqual(self.signal_notification, self.notification)

    def test_correct_delivery_delay_created(self):
        """Test that the correct delivery delay was created"""
        DeliveryDelay.objects.all().delete()

        result = views.process_delivery_delay(
            self.delivery_delay, self.notification)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content.decode('ascii'), 'Delivery Delay Processed')
        self.assertTrue(DeliveryDelay.objects.filter(
            sns_topic='arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes',
            sns_messageid='f34c6922-c3a1-54a1-bd88-23f998b43978',
            mail_timestamp=clean_time('2020-06-16T00:15:40.641Z'),
            mail_id='EXAMPLE7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000',
            mail_from='sender@example.com',
            address='recipient@example.com',
            delayed_time=clean_time('2020-06-16T00:25:40.095Z'),
            delay_type='TransientCommunicationFailure',
            expiration_time=clean_time('2020-06-16T00:25:40.914Z'),
            status='4.4.1',
            diagnostic_code='smtp; 421 4.4.1 Unable to connect to remote host'
        ).exists())
