import re
import logging
import aiohttp
import asyncio
import async_timeout
from bs4 import BeautifulSoup


_LOGGER = logging.getLogger(__name__)


class Alarmdotcom(object):
    """
    Access to alarm.com partners and accounts.

    This class is used to interface with the options available through
    alarm.com. The basic functions of checking system status and arming
    and disarming the system are possible.
    """

    # Page elements on alarm.com that are needed
    # Using a dict for the attributes to set whether it is a name or id for locating the field
    LOGIN_URL = 'https://www.alarm.com/pda/Default.aspx'
    LOGIN_USERNAME = ('name', 'ctl00$ContentPlaceHolder1$txtLogin')
    LOGIN_PASSWORD = ('name', 'ctl00$ContentPlaceHolder1$txtPassword')
    LOGIN_BUTTON = ('name', 'ctl00$ContentPlaceHolder1$btnLogin')

    STATUS_IMG = ('id', 'ctl00_phBody_lblArmingState')
    
    BTN_DISARM = ('id', 'ctl00_phBody_butDisarm')
    BTN_ARM_STAY = ('id', 'ctl00_phBody_butArmStay', 'ctl00_phBody_ArmingStateWidget_btnArmOptionStay')
    BTN_ARM_AWAY = ('id', 'ctl00_phBody_butArmAway', 'ctl00_phBody_ArmingStateWidget_btnArmOptionAway')

    # Image to check if hidden or not while the system performs it's action.
    STATUS_UPDATING = {'id': 'ctl00_phBody_ArmingStateWidget_imgArmingUpdating'}

    # Alarm.com constants

    # Alarm.com baseURL
    ALARMDOTCOM_URL = 'https://www.alarm.com/pda/'
    
    # Session key regex to extract the current session
    SESSION_KEY_RE = re.compile(
        '{url}(?P<sessionKey>.*)/Default.aspx'.format(url=ALARMDOTCOM_URL))
    
    # ALARM.COM CSS MAPPINGS
    USERNAME = 'ctl00$ContentPlaceHolder1$txtLogin'
    PASSWORD = 'ctl00$ContentPlaceHolder1$txtPassword'
    
    LOGIN_CONST = 'ctl00$ContentPlaceHolder1$btnLogin'
    
    ERROR_CONTROL = 'ctl00_ContentPlaceHolder1_ErrorControl1'
    MESSAGE_CONTROL = 'ctl00_ErrorControl1'
    
    VIEWSTATE = '__VIEWSTATE'
    VIEWSTATEGENERATOR = '__VIEWSTATEGENERATOR'
    VIEWSTATEENCRYPTED = '__VIEWSTATEENCRYPTED'
    
    # Event validation
    EVENTVALIDATION = '__EVENTVALIDATION'
    DISARM_EVENT_VALIDATION = \
        'MnXvTutfO7KZZ1zZ7QR19E0sfvOVCpK7SV' \
        'yeJ0IkUkbXpfEqLa4fa9PzFK2ydqxNal'
    ARM_STAY_EVENT_VALIDATION = \
        '/CwyHTpKH4aUp/pqo5gRwFJmKGubsvmx3RI6n' \
        'IFcyrtacuqXSy5dMoqBPX3aV2ruxZBTUVxenQ' \
        '7luwjnNdcsxQW/p+YvHjN9ialbwACZfQsFt2o5'
    ARM_AWAY_EVENT_VALIDATION = '3ciB9sbTGyjfsnXn7J4LjfBvdGlkqiHoeh1vPjc5'
    
    DISARM_COMMAND = 'ctl00$phBody$butDisarm'
    ARM_STAY_COMMAND = 'ctl00$phBody$butArmStay'
    ARM_AWAY_COMMAND = 'ctl00$phBody$butArmAway'
    
    ARMING_PANEL = '#ctl00_phBody_pnlArming'
    ALARM_STATE = '#ctl00_phBody_lblArmingState'

    COMMAND_LIST = {'Disarm': {'command': DISARM_COMMAND,
                           'eventvalidation': DISARM_EVENT_VALIDATION},
                'Arm+Stay': {'command': ARM_STAY_COMMAND,
                             'eventvalidation': ARM_STAY_EVENT_VALIDATION},
                'Arm+Away': {'command': ARM_AWAY_COMMAND,
                             'eventvalidation': ARM_AWAY_EVENT_VALIDATION}}
    
    def __init__(self, username, password, websession, loop):
        """
        Use aiohttp to make a request to alarm.com

        :param username: Alarm.com username
        :param password: Alarm.com password
        :param websession: AIOHttp Websession
        :param loop: Async loop.
        """
        self._username = username
        self._password = password
        self._websession = websession
        self._loop = loop
        self._login_info = None
        self.state = None

    @asyncio.coroutine
    def async_login(self):
       """Login to Alarm.com."""
       _LOGGER.debug('Attempting to log into Alarm.com...')

       # Get the session key for future logins.
       response = None
       try:
           with async_timeout.timeout(10, loop=self._loop):
               response = yield from self._websession.get(
                   self.ALARMDOTCOM_URL + '/Default.aspx')

           _LOGGER.debug(
               'Response status from Alarm.com: %s',
               response.status)
           text = yield from response.text()
           _LOGGER.debug(text)
           tree = BeautifulSoup(text, 'html.parser')
           self._login_info = {
               'sessionkey': self.SESSION_KEY_RE.match(
                   response.url).groupdict()['sessionKey'],
               self.VIEWSTATE: tree.select(
                   '#{}'.format(self.VIEWSTATE))[0].attrs.get('value'),
               self.VIEWSTATEGENERATOR: tree.select(
                   '#{}'.format(self.VIEWSTATEGENERATOR))[0].attrs.get('value'),
               self.EVENTVALIDATION: tree.select(
                   '#{}'.format(self.EVENTVALIDATION))[0].attrs.get('value')
           }

           _LOGGER.debug(self._login_info)
           _LOGGER.info('Successful login to Alarm.com')

       except (asyncio.TimeoutError, aiohttp.errors.ClientError):
           _LOGGER.error('Can not get login page from Alarm.com')
           return False
       except AttributeError:
           _LOGGER.error('Unable to get sessionKey from Alarm.com')
           raise

        # Login params to pass during the post
       params = {
           self.USERNAME: self._username,
           self.PASSWORD: self._password,
           self.VIEWSTATE: self._login_info[self.VIEWSTATE],
           self.VIEWSTATEGENERATOR: self._login_info[self.VIEWSTATEGENERATOR],
           self.EVENTVALIDATION: self._login_info[self.EVENTVALIDATION]
       }

       try:
           # Make an attempt to log in.
           with async_timeout.timeout(10, loop=self._loop):
               response = yield from self._websession.post(
                   self.ALARMDOTCOM_URL + '{}/Default.aspx'.format(
                       self._login_info['sessionkey']),
                   data=params)
           _LOGGER.debug(
               'Status from Alarm.com login %s', response.status)

           # Get the text from the login to ensure that we are logged in.
           text = yield from response.text()
           _LOGGER.debug(text)
           tree = BeautifulSoup(text, 'html.parser')
           try:
               # Get the initial state.
               self.state = tree.select(self.ALARM_STATE)[0].get_text()
               _LOGGER.debug(
                   'Current alarm state: %s', self.state)
           except IndexError:
               try:
                   error_control = tree.select(
                       '#{}'.format(self.ERROR_CONTROL))[0].attrs.get('value')
                   if 'Login failure: Bad Credentials' in error_control:
                       _LOGGER.error(error_control)
                       return False
               except AttributeError:
                   _LOGGER.error('Error while trying to log into Alarm.com')
                   return False
       except (asyncio.TimeoutError, aiohttp.errors.ClientError):
           _LOGGER.error("Can not load login page from Alarm.com")
           return False

    @asyncio.coroutine
    def async_update(self):
        """Fetch the latest state."""
        _LOGGER.debug('Calling update on Alarm.com')
        response = None
        if not self._login_info:
            yield from self.async_login()
        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.get(
                    self.ALARMDOTCOM_URL + '{}/main.aspx'.format(
                        self._login_info['sessionkey']))

            _LOGGER.debug('Response from Alarm.com: %s', response.status)
            text = yield from response.text()
            _LOGGER.debug(text)
            tree = BeautifulSoup(text, 'html.parser')
            try:
                self.state = tree.select(self.ALARM_STATE)[0].get_text()
                _LOGGER.debug(
                    'Current alarm state: %s', self.state)
            except IndexError:
                # We may have timed out. Re-login again
                self.state = None
                self._login_info = None
                yield from self.async_update()
        except (asyncio.TimeoutError, aiohttp.errors.ClientError):
            _LOGGER.error("Can not load login page from Alarm.com")
            return False
        finally:
            if response is not None:
                yield from response.release()

    @asyncio.coroutine
    def _send(self, event):
        """Generic function for sending commands to Alarm.com

        :param event: Event command to send to alarm.com
        """
        _LOGGER.debug('Sending %s to Alarm.com', event)

        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = yield from self._websession.post(
                    self.ALARMDOTCOM_URL + '{}/main.aspx'.format(
                        self._login_info['sessionkey']),
                    data={
                        self.VIEWSTATE: '',
                        self.VIEWSTATEENCRYPTED: '',
                        self.EVENTVALIDATION:
                            self.COMMAND_LIST[event]['eventvalidation'],
                        self.COMMAND_LIST[event]['command']: event})

                _LOGGER.debug(
                    'Response from Alarm.com %s', response.status)
                text = yield from response.text()
                tree = BeautifulSoup(text, 'html.parser')
                try:
                    message = tree.select(
                        '#{}'.format(self.MESSAGE_CONTROL))[0].get_text()
                    if 'command' in message:
                        _LOGGER.debug(message)
                        # Update alarm.com status after calling state change.
                        yield from self.async_update()
                except IndexError:
                    # May have been logged out
                    yield from self.async_login()
                    if event == 'Disarm':
                        yield from self.async_alarm_disarm()
                    elif event == 'Arm+Stay':
                        yield from self.async_alarm_arm_away()
                    elif event == 'Arm+Away':
                        yield from self.async_alarm_arm_away()

        except (asyncio.TimeoutError, aiohttp.errors.ClientError):
            _LOGGER.error('Error while trying to disarm Alarm.com system')
        finally:
            if response is not None:
                yield from response.release()

    @asyncio.coroutine
    def async_alarm_disarm(self):
        """Send disarm command."""
        yield from self._send('Disarm')

    @asyncio.coroutine
    def async_alarm_arm_home(self):
        """Send arm hom command."""
        yield from self._send('Arm+Stay')

    @asyncio.coroutine
    def async_alarm_arm_away(self):
        """Send arm away command."""
        yield from self._send('Arm+Away')
