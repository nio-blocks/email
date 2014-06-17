import logging

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTP_SSL, SMTPServerDisconnected

from nio.common.discovery import Discoverable, DiscoverableType
from nio.common.block.base import Block
from nio.util import eval_signal
from nio.metadata.properties.list import ListProperty
from nio.metadata.properties.object import ObjectProperty
from nio.metadata.properties.timedelta import TimeDeltaProperty
from nio.metadata.properties.string import StringProperty
from nio.metadata.properties.int import IntProperty
from nio.metadata.properties.holder import PropertyHolder
from nio.modules.threading.imports import Lock, Thread
from nio.modules.scheduler.imports import Job


HTML_MSG_FORMAT = """\
<html>
  <head></head>
  <body>
    {0}
  </body>
</html>
"""


class Identity(PropertyHolder):
    name = StringProperty(default='John Doe')
    email = StringProperty(default='')


class SMTPConfig(PropertyHolder):
    host = StringProperty(default='localhost')
    port = IntProperty(default=0)
    account = StringProperty(default='')
    password = StringProperty(default='')
    timeout = IntProperty(default=10)


class Message(PropertyHolder):
    sender = StringProperty(default='')
    subject = StringProperty(default='')
    body = StringProperty(default='')


class SMTPConnection(object):
    
    def __init__(self, config, logger):
        self.host = config.host
        self.port = config.port
        self.account = config.account
        self.password = config.password
        self.timeout = config.timeout
        self._logger = logger
        self._conn = None
        self._conn_lock = Lock()
        self._send_lock = Lock()
        self._send_attempts = 0

    def connect(self):
        self._conn_lock.acquire()
        
        self._logger.debug(
            "Connecting to SMTP: %s:%d" % (self.host, self.port)
        )
        try:
            self._conn = SMTP_SSL(
                host=self.host,
                port=self.port,
                timeout=self.timeout
            )
            self._authenticate()
        except Exception as e:
            self._logger.error("Error connecting to SMTP server: %s" % e)
            raise e
        finally:
            self._conn_lock.release()

    def _authenticate(self):
        self._logger.debug(
            "Logging into %s as %s" % (self.host, self.account)
        )
        self._conn.login(self.account, self.password)

    def sendmail(self, frm, to, msg):
        self._logger.debug("Sending mail to %s" % to)
        try:
            self._conn_lock.acquire()
            self._conn.sendmail(frm, to, msg)
            self._conn_lock.release()
            self._send_attempts = -1
        except SMTPServerDisconnected as e:
            self._logger.error(
                "SMTP server disconnected, reconnecting..."
            )
            self._conn_lock.release()
            self.connect()
            raise e
        except Exception as e:
            self._logger.error("Error while sending: %s" % e)

            # release the connection lock if it's taken
            if not self._conn_lock.acquire(False):
                self._conn_lock.release()

            # increment the send attempts and make sure we're still
            # willing to try again
            self._send_attempts += 1
            if self._send_attempts < self.max_send_retries:
                self.sendmail(frm, to, msg)
            else:
                raise e

    def disconnect(self):
        try:
            self._conn_lock.acquire()
            self._logger.debug("Disconnecting from %s" % self.host)
            self._conn.quit()
        except Exception as e:
            self._logger.error("Error while disconnecting: %s" % e)
        finally:
            self._conn_lock.release()

@Discoverable(DiscoverableType.block)
class Email(Block):
    
    to = ListProperty(Identity)
    server = ObjectProperty(SMTPConfig)
    message = ObjectProperty(Message)
    
    def __init__(self):
        super().__init__()
        self._smtp_conn = None
        self._retry_conn = None

    def configure(self, context):
        super().configure(context)
        self._smtp_conn = SMTPConnection(self.server, self._logger)

    def stop(self):
        super().stop()
        self._smtp_conn.disconnect()

    def process_signals(self, signals):

        # connect to the smtp server before we start sending
        self._smtp_conn.connect()

        # handle all the incoming signals
        for signal in signals:

            # TODO: eval_signal should not be so permissive. Returning True
            # as an error condition was a hack to accomodate the scheduler...
            subject = eval_signal(signal, self.message.subject, self._logger)
            body = eval_signal(signal, self.message.body, self._logger)
            self._send_to_all(subject, body)

        self._smtp_conn.disconnect()

    def _send_to_all(self, subject, body):
        sender = self.message.sender
        for rcp in self.to:
            msg = self._construct_msg(subject, body, rcp)
            Thread(
                target=self._smtp_conn.sendmail,
                args=(sender, rcp.email, msg.as_string())
            ).run()

    def _construct_msg(self, subject, body, recipient):
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.message.sender

        plain_part = MIMEText(body, 'plain')
        msg.attach(plain_part)

        html_part = MIMEText(HTML_MSG_FORMAT.format(body), 'html')
        msg.attach(html_part)

        return msg
