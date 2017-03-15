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
    
    def __init__(self, username, password, websession, hass):
        """
        Use aiohttp to make a request to alarm.com

        :param username: Alarm.com username
        :param password: Alarm.com password
        :param websession: Websession from HASS
        :param hass: Homeassitant core
        """
        self._username = username
        self._password = password
        self._websession = websession
        self._hass = hass
        self._login_info = None
        slef._state = None
        

    @asyncio.coroutine
    def async_login(username, password, session):
       """Login to Alarm.com."""
        _LOGGER.debug('Attempting to log into Alarm.com...')

        # Get the session key for future logins.
        response = None
        try:
            with async_timeout.timeout(10, loop=self._hass.loop):
                response = yield from self._websession.get(
                    ALARMDOTCOM_URL + '/Default.aspx')

            _LOGGER.debug(
                'Response status from Alarm.com: %s',
                response.status)
            text = yield from response.text()
            _LOGGER.debug(text)
            tree = BeautifulSoup(text, 'html.parser')
            self._login_info = {
                'sessionkey': SESSION_KEY_RE.match(
                    response.url).groupdict()['sessionKey'],
                VIEWSTATE: tree.select(
                    '#{}'.format(VIEWSTATE))[0].attrs.get('value'),
                VIEWSTATEGENERATOR: tree.select(
                    '#{}'.format(VIEWSTATEGENERATOR))[0].attrs.get('value'),
                EVENTVALIDATION: tree.select(
                    '#{}'.format(EVENTVALIDATION))[0].attrs.get('value')
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
            USERNAME: self._username,
            PASSWORD: self._password,
            VIEWSTATE: self._login_info[VIEWSTATE],
            VIEWSTATEGENERATOR: self._login_info[VIEWSTATEGENERATOR],
            EVENTVALIDATION: self._login_info[EVENTVALIDATION]
        }

        try:
            # Make an attempt to log in.
            with async_timeout.timeout(10, loop=self._hass.loop):
                response = yield from self._websession.post(
                    ALARMDOTCOM_URL + '{}/Default.aspx'.format(
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
                self._state = tree.select(ALARM_STATE)[0].get_text()
                _LOGGER.debug(
                    'Current alarm state: %s', self._state)
            except IndexError:
                try:
                    error_control = tree.select(
                        '#{}'.format(ERROR_CONTROL))[0].attrs.get('value')
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
        from bs4 import BeautifulSoup
        response = None
        if not self._login_info:
            yield from self.async_login()
        try:
            with async_timeout.timeout(10, loop=self._hass.loop):
                response = yield from self._websession.get(
                    ALARMDOTCOM_URL + '{}/main.aspx'.format(
                        self._login_info['sessionkey']))

            _LOGGER.debug('Response from Alarm.com: %s', response.status)
            text = yield from response.text()
            _LOGGER.debug(text)
            tree = BeautifulSoup(text, 'html.parser')
            try:
                self._state = tree.select(ALARM_STATE)[0].get_text()
                _LOGGER.debug(
                    'Current alarm state: %s', self._state)
            except IndexError:
                # We may have timed out. Re-login again
                self._state = None
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
        _LOGGER.debug('Sending %s to Alarm.com', event)

        with async_timeout.timeout(10, loop=self._hass.loop):
            try:
                response = yield from self._websession.post(
                    ALARMDOTCOM_URL + '{}/main.aspx'.format(
                        self._login_info['sessionkey']),
                    data={
                        VIEWSTATE: '',
                        VIEWSTATEENCRYPTED: '',
                        EVENTVALIDATION:
                            COMMAND_LIST[event]['eventvalidation'],
                        COMMAND_LIST[event]['command']: event})

                _LOGGER.debug(
                    'Response from Alarm.com %s', response.status)
                text = yield from response.text()
                tree = BeautifulSoup(text, 'html.parser')
                try:
                    message = tree.select(
                        '#{}'.format(MESSAGE_CONTROL))[0].get_text()
                    if 'command' in message:
                        _LOGGER.debug(message)
                        # Update alarm.com status after calling state change.
                        yield from self.async_update()
                except IndexError:
                    # May have been logged out
                    self.async_login()
                    if event == 'Disarm':
                        yield from self.async_alarm_disarm()
                    elif event == 'Arm+Stay':
                        yield from self.async_alarm_arm_away()
                    elif event == 'Arm+Away':
                        yield from self.async_alarm_arm_away()

            except (asyncio.TimeoutError, aiohttp.errors.ClientError):
                _LOGGER.error('Error while trying to disarm Alarm.com system')

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
