from email.mime.multipart import MIMEMultiPart
from email.mime.text import MIMEText
from smtplib import SMTP_SSL

from nio.common.block.base import Block
from nio.util import eval_signal
from nio.metadata.properties.list import ListProperty
from nio.metadata.properties.object import ObjectProperty
from nio.metadata.properties.string import StringProperty
from nio.metadata.properties.int import IntProperty
from nio.metadata.properties.holder import PropertyHolder
from nio.modules.threading.imports import Lock, Thread


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


class Email(Block):
    
    to = ListProperty(Identity)
    server = ObjectProperty(SMTPConfig)
    message = ObjectProperty(Message)
    
    def __init__(self):
        super().__init__()
        self._smtp_conn = None
        self._conn_lock = Lock()

    def configure(self):
        super().configure()
        self._connect_to_smtp()

    def _connect_to_smtp(self):
        self._conn_lock.acquire()
        self._smtp_conn = SMTP_SSL(
            host=self.server.host,
            port=self.server.port,
            timeout=server.timeout
        )
        self._conn_lock.release()

    def stop(self):
        super().stop()
        self._conn_lock.acquire()
        self._smtp_conn.quit()
        self._conn_lock.release()

    def process_signals(self, signals):
        for signal in signals:
            subject = eval_signal(signal, self.message.subject, self._logger)
            body = eval_signal(signal, self.message.body, self._logger)

            msg = self._construct_msg(subject, body)
            Thread(
                target=self._smtp_conn.sendmail,
                args=(self.message.sender,
                      [r.email for r in self.to],
                      msg.as_string)
            )

    def _construct_msg(self, subject, body):
        # for recipient in self.to:
        msg = MIMEMultiPart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.message.sender
        # msg['To'] = recipient.name

        plain_part = MIMETest(body, 'plain')
        msg.attach(plain_part)

        html_part = MIMEText(HTML_MSG_FORMAT.format(body), 'html')
        msg.attach(html_part)

        return msg
