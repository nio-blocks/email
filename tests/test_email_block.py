from unittest.mock import patch, MagicMock, ANY
from ..email_block import Email, SMTPConnection, SMTPConfig
from threading import Event

from nio.testing.block_test_case import NIOBlockTestCase
from nio.util.discovery import not_discoverable
from nio.signal.base import Signal


@not_discoverable
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

    @patch.object(SMTPConnection, 'sendmail')
    @patch.object(SMTPConnection, "connect")
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

    @patch.object(SMTPConnection, 'sendmail')
    @patch.object(
        SMTPConnection,
        "connect", side_effect=Exception('mock connection fail')
    )
    def test_conn_error(self, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(3)]
        blk = EmailTestBlock(process_event)
        self.configure_block(blk, self.config)
        blk.logger.error = MagicMock()
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        self.assertEqual(0, mock_send.call_count)
        self.assertEqual(1, blk.logger.error.call_count)
        blk.stop()

    @patch.object(
        SMTPConnection,
        'sendmail', side_effect=Exception('mock connection fail')
    )
    @patch.object(SMTPConnection, "connect")
    @patch.object(SMTPConnection, 'disconnect')
    def test_sendmail_error(self, mock_disconnect, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(3)]
        blk = EmailTestBlock(process_event)
        self.configure_block(blk, self.config)
        blk.logger.error = MagicMock()
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        self.assertEqual(1, mock_send.call_count)
        self.assertEqual(1, blk.logger.error.call_count)
        blk.stop()

    @patch.object(SMTPConnection, 'sendmail')
    @patch.object(SMTPConnection, "connect")
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

    @patch.object(SMTPConnection, 'sendmail')
    @patch.object(SMTPConnection, "connect")
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

    @patch.object(Email, '_send_to_all')
    @patch.object(SMTPConnection, "connect")
    def test_body_syntax_err(self, mock_connect, mock_send):
        process_event = Event()
        signals = [TestSignal(23)]
        self._add_recipients()
        blk = EmailTestBlock(process_event)
        self.config['message']['subject'] = "{{$data + 'astring'}}"
        self.config['message']['body'] = "{{dict($data)}}"
        self.configure_block(blk, self.config)
        blk.start()
        blk.process_signals(signals)
        process_event.wait(1)
        mock_send.assert_called_once_with(ANY, '<No Value>', '<No Value>')
        blk.stop()

    def test_sendmail_retry(self):
        cfg = SMTPConfig()
        smtp = SMTPConnection(cfg, None)
        smtp.logger = MagicMock()
        smtp._conn = MagicMock(side_effect=Exception('error'))
        smtp._conn.sendmail = MagicMock(side_effect=Exception('error'))
        self.assertRaises(Exception, smtp.sendmail,
                          ('from', 'to', 'message'))
        try:
            smtp.sendmail('from', 'to', 'message')
        except:
            self.assertEqual(2, smtp._conn.sendmail.call_count)
