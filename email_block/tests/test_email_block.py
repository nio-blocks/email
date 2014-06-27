from unittest.mock import patch, MagicMock, ANY
from notification.email_block.email_block import Email
from nio.util.support.block_test_case import NIOBlockTestCase
from nio.modules.threading.imports import Event
from nio.common.signal.base import Signal


class EmailTestBlock(Email):
    
    def __init__(self, event):
        super().__init__()
        self._e = event

    def process_signals(self, signals):
        super().process_signals(signals)
        self._e.set()


class TestSignal(Signal):
    def __init__(self, data):
        super().__init__()
        self.data = data


class TestEmail(NIOBlockTestCase):

    def setUp(self):
        super().setUp()
        self.config = {
            "to": [
                {
                    "name": "Joe",
                    "email": "joe@mail.com"
                }
            ],
            "server": {
                "host": "smtp.mail.com",
                "account": "admin@mail.com",
                "password": "hansel"
            },
            "message": {
                "sender": "Anna Administrator",
                "subject": "Diagnostics",
                "body": "This is a test {{$data}}"
            }
        }

    def _add_recipients(self):
        self.config['to'].extend([                
            {
                "name": "Suzanne",
                "email": "suzy@mail.com"
            },
            {
                "name": "Jim",
                "email": "jimmy@mail.com"
            }
        ])
        
    @patch("notification.email_block.email_block.SMTPConnection.sendmail")
    @patch("notification.email_block.email_block.SMTPConnection.connect")
    def test_send_one_to_one(self, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(3)]
        blk = EmailTestBlock(process_event)
        self.configure_block(blk, self.config)
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        self.assertEqual(1, mock_send.call_count)
        mock_send.assert_called_once_with(
            self.config['message']['sender'],
            self.config['to'][0]['email'],
            ANY
        )
        blk.stop()

    @patch("notification.email_block.email_block.SMTPConnection.sendmail")
    @patch("notification.email_block.email_block.SMTPConnection.connect")
    def test_send_one_to_multiple(self, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(23)]
        self._add_recipients()
        blk = EmailTestBlock(process_event)
        self.configure_block(blk, self.config)
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        self.assertEqual(3, mock_send.call_count)
        blk.stop()

    @patch("notification.email_block.email_block.SMTPConnection.sendmail")
    @patch("notification.email_block.email_block.SMTPConnection.connect")
    def test_send_multiple_to_multiple(self, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(23), TestSignal(32), TestSignal(42)]
        self._add_recipients()
        blk = EmailTestBlock(process_event)
        self.configure_block(blk, self.config)
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        self.assertEqual(9, mock_send.call_count)
        blk.stop()
