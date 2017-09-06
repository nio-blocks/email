from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTP_SSL, SMTPServerDisconnected

from nio import TerminatorBlock
from nio.properties import ListProperty, ObjectProperty, PropertyHolder, \
    Property, StringProperty, IntProperty, VersionProperty


HTML_MSG_FORMAT = """\
<html>
  <head></head>
  <body>
    {0}
  </body>
</html>
"""


class Identity(PropertyHolder):
    name = StringProperty(title='Name', default='John Doe')
    email = StringProperty(title='Email Address', default='')


class SMTPConfig(PropertyHolder):
    host = StringProperty(title='SMTP Host', default='[[SMTP_HOST]]')
    port = IntProperty(title='SMTP Port', default='[[SMTP_PORT]]')
    account = StringProperty(title='Account', default='[[SMTP_ACCOUNT]]')
    password = StringProperty(title='Password', default='[[SMTP_PASSWORD]]')
    timeout = IntProperty(title='Timeout', default=10)


class Message(PropertyHolder):
    sender = StringProperty(title='Sender', default='')
    subject = Property(title='Subject', default='<No Value>')
    body = Property(title='Body', default='<No Value>')


class SMTPConnection(object):

    """ A class to manage the guts of the SMTP connection.

    Args:
        config (SMTPConfig): Email block property encapsulating
            SMTP configuration details.
        logger (Logger): NIO logger from the enclosing block.

    """

    def __init__(self, config, logger):
        self.host = config.host
        self.port = config.port
        self.account = config.account
        self.password = config.password
        self.timeout = config.timeout
        self.logger = logger
        self._conn = None
        self._send_attempts = 0
        self.max_send_retries = 1

    def connect(self):
        """ Connects to the configured SMTP server.

        """
        self.logger.debug(
            "Connecting to SMTP: %s:%d" % (self.host(), self.port())
        )

        # attempt to connect to the SMTP server and authenticate.
        try:
            self._conn = SMTP_SSL(
                host=self.host(),
                port=self.port(),
                timeout=self.timeout()
            )
            self._authenticate()
        except Exception as e:
            self.logger.error("Error connecting to SMTP server: %s" % e)
            raise e

    def _authenticate(self):
        """ Log in an existing SMTP connection.

        """
        self.logger.debug(
            "Logging into %s as %s" % (self.host(), self.account())
        )
        self._conn.login(self.account(), self.password())

    def sendmail(self, frm, to, msg):
        """ Send a message via SMTP.

        Args:
            frm (str): The 'from' email address.
            to (str): The 'to' email address.
            msg (str): The message.

        Returns:
            None

        """
        self.logger.debug("Sending mail to %s" % to)
        try:

            # acquire the connection lock and send the message
            self._conn.sendmail(frm, to, msg)
            self._send_attempts = 0
        except SMTPServerDisconnected as e:
            # if our connection is dead when we send, release the
            # connection lock and attempt to reconnect.
            self.logger.error(
                "SMTP server disconnected, reconnecting..."
            )
            self.connect()

            # we reraise the exception so we can do some generic
            # bookkeeping.
            raise e
        except Exception as e:
            self.logger.error("Error while sending: %s" % e)

            # increment the send attempts and make sure we're still
            # willing to try again. If not, abort.
            self._send_attempts += 1
            if self._send_attempts <= self.max_send_retries:
                self.sendmail(frm, to, msg)
            else:
                self._send_attempts = 0
                raise e

    def disconnect(self):
        """ Drop the connection to the configured SMTP server.

        """
        try:
            self.logger.debug("Disconnecting from %s" % self.host())
            self._conn.quit()
        except Exception as e:
            self.logger.error("Error while disconnecting: %s" % e)


class Email(TerminatorBlock):
    """ A block for sending email.

    Properties:
        to (list(Identity)): A list of recipient identities (name/email).
        server (SMTPConfig): host, port, account, etc. for SMTP server.
        message (Message): The message contents and sender name.

    """
    version = VersionProperty('0.1.0')
    to = ListProperty(Identity, title='Receiver', default=[])
    server = ObjectProperty(SMTPConfig, title='Server', allow_none=False)
    message = ObjectProperty(Message, title='Message', allow_none=True)

    def __init__(self):
        super().__init__()
        self._retry_conn = None

    def process_signals(self, signals):
        """ For each signal object, build the configured message and send
        it to each recipient.

        Note that this method does not return until all of the messages are
        successfully sent (i.e. all the sendmail threads have exited). This
        avoids dropped messages in the event that the disconnect thread gets
        scheduled before all sendmail threads are complete.

        Args:
            signals (list(Signal)): The signals to process.

        Returns:
            None

        """
        # make a new connection to the SMTP server each time we get a new
        # batch of signals.
        smtp_conn = SMTPConnection(self.server(), self.logger)
        try:
            smtp_conn.connect()
        except:
            self.logger.error(
                'Aborting sending emails. '
                '{} signals discarded'.format(len(signals))
            )
            return

        # handle each incoming signal
        for signal in signals:
            try:
                subject = self.message().subject(signal)
            except Exception as e:
                subject = self.get_defaults()['message'].subject()
                self.logger.error(
                    "Email subject evaluation failed: {0}: {1}".format(
                        type(e).__name__, str(e))
                )

            try:
                body = self.message().body(signal)
            except Exception as e:
                body = self.get_defaults()['message'].body()
                self.logger.error(
                    "Email body evaluation failed: {0}: {1}".format(
                        type(e).__name__, str(e))
                )

            self._send_to_all(smtp_conn, subject, body)

        # drop the SMTP connection after each round of signals
        smtp_conn.disconnect()

    def _send_to_all(self, conn, subject, body):
        """ Build a message based on the provided content and send it to
        each of the configured recipients.

        Args:
            conn (SMTPConnection): The connection over which to send
                the message.
            subject (str): The desired subject line of the message.
            body (str): The desired message body.

        Returns:
            None

        """
        sender = self.message().sender()
        msg = self._construct_msg(subject, body)
        for rcp in self.to():
            # customize the message to each recipient
            msg['To'] = rcp.name()
            try:
                conn.sendmail(sender, rcp.email(), msg.as_string())
                self.logger.debug("Sent mail to: {}".format(rcp.email))
            except Exception as e:
                self.logger.error("Failed to send mail: {}".format(e))

    def _construct_msg(self, subject, body):
        """ Construct the multipart message. Mail clients unable to
        render HTML will default to plaintext.

        Args:
            subject (str): The subject line.
            body (str): The message body.

        Returns:
            msg (MIMEMultipart): A message containing generic
                headers, and HTML version, and a plaintext version.

        """
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.message().sender()

        plain_part = MIMEText(body, 'plain')
        msg.attach(plain_part)

        html_part = MIMEText(HTML_MSG_FORMAT.format(body), 'html')
        msg.attach(html_part)

        return msg
