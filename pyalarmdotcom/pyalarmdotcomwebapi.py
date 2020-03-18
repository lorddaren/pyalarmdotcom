import re
import logging
import aiohttp
import asyncio
import async_timeout
import sys
import json

from .stateful_browser import StatefulBrowser

_LOGGER = logging.getLogger(__name__)


class Alarmdotcom(object):
    """
    Access to alarm.com partners and accounts.

    This class is used to interface with the options available through
    alarm.com. The basic functions of checking system status and arming
    and disarming the system are possible.
    """

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
        self.sensor_status = None
        self.state = ""  # empty string instead of None so lower() in alarm_control_panel doesn't complain
        self.browser = None
        self.panel_id = None
        self.logged_in = False


    def _get_browser(self):
        if not self.browser:
            br = StatefulBrowser(
                soup_config={'features': 'lxml'},
                raise_on_404=True,
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.167 Safari/537.36'
            )
            # br.set_verbose(8)
            self.browser = br
        return self.browser


    def _get_panel(self):
        if not self.panel_id: 
            result = self.api_call('systems/availableSystemItems')
            user_id = result['data'][0]['id']
            _LOGGER.debug('user id is '+user_id)
            result = self.api_call('systems/systems/'+user_id)
            panel_id = result['data']['relationships']['partitions']['data'][0]['id']
            _LOGGER.debug('panel id is '+panel_id)
            self.panel_id = panel_id
        return self.panel_id


    def api_call(self, apiUrl, apiMethod='GET', apiBody=''):
        br = self._get_browser()
        if not self.logged_in:
            self._login()
        _LOGGER.debug('Logged In: '+str(self.logged_in)) # True
        cookiejar = br.get_cookiejar()
        ajaxkey = None
        for cookie in cookiejar:
            # _LOGGER.debug(cookie.name+': '+cookie.value)
            if 'afg' == cookie.name:
                ajaxkey = cookie.value
        _LOGGER.debug("ajaxkey is %s", ajaxkey)
        result = None
        try:
            apiCall = br.request(method=apiMethod,
                url='https://www.alarm.com/web/api/'+apiUrl,
                data=apiBody,
                headers={'ajaxrequestuniquekey': ajaxkey, 'Accept': 'application/vnd.api+json', 'Content-Type': 'application/json; charset=UTF-8'}
            )
            responsecontent = apiCall.content.decode("utf-8")
            _LOGGER.debug("Post command JSON is %s", responsecontent)
            result = json.loads(responsecontent)
            _LOGGER.debug(result)
        except:
            _LOGGER.debug('apiUrl: '+apiUrl)
            _LOGGER.debug('apiBody: '+apiBody)
            e = sys.exc_info()[0]
            _LOGGER.debug("got an error %s", e)
        return result
        
        
    @asyncio.coroutine
    def async_login(self):
        """Login to Alarm.com."""
        _LOGGER.debug('Attempting to log into Alarm.com...')

        # Get the session key for future logins.
        response = None
        br = self._get_browser()
        with async_timeout.timeout(10, loop=self._loop):
            response = br.open( "https://www.alarm.com/login.aspx" )
           
        _LOGGER.debug(
            'Response status from Alarm.com: %s',
            response)
       
        location = br.get_url()
        content = br.get_current_page().decode("utf-8")
        session = re.search(r'\/(\(S[^\/]+)\/', location)
        if session:
            session = session.group(1)
        viewstate = re.search(r'name="__VIEWSTATE".*?value="([^"]*)"', content)
        if viewstate:
            viewstate = viewstate.group(1)
        _LOGGER.debug("VIEWSTATE is %s", viewstate)
        viewstategenerator = re.search(r'name="__VIEWSTATEGENERATOR".*?value="([^"]*)"', content)
        if viewstategenerator:
            viewstategenerator = viewstategenerator.group(1)
        _LOGGER.debug("VIEWSTATEGENERATOR is %s", viewstategenerator)
        eventval = re.search(r'name="__EVENTVALIDATION".*?value="([^"]*)"', content)
        if eventval:
            eventval = eventval.group(1)
        _LOGGER.debug("EVENTVALIDATION is %s", eventval)
        self.logged_in = None
        _LOGGER.info('Attempting login to Alarm.com')
        try:
            postresponse = br.post('https://www.alarm.com/web/Default.aspx',
                data={'__VIEWSTATE': viewstate, '__EVENTVALIDATION': eventval, '__VIEWSTATEGENERATOR': viewstategenerator, 'IsFromNewSite': '1', 'JavaScriptTest': '1', 'ctl00$ContentPlaceHolder1$loginform$hidLoginID': '', 'ctl00$ContentPlaceHolder1$loginform$txtUserName': self._username, 'ctl00$ContentPlaceHolder1$loginform$txtPassword': self._password, 'ctl00$ContentPlaceHolder1$loginform$signInButton': 'Logging In...', 'ctl00$bottom_footer3$ucCLS_ZIP$txtZip': 'Zip Code'})
            _LOGGER.debug("Post login URL is %s", postresponse.url)
            self.logged_in = True
            panel_id = self._get_panel()
        except:
            e = sys.exc_info()[0]
            _LOGGER.debug("got an error %s", e)
        return self.logged_in


    def command(self, command, forceBypass=False, noEntryDelay=False, silentArming=True):
        states = ['', 'disarmed', 'armed stay', 'armed away']
        commands = {'ARM+STAY': '/armStay', 'ARM+AWAY': '/armAway', 'DISARM': '/disarm', 'STATUS': ''}
        panel_id = self._get_panel()
        command = command.upper()

        apiUrl = 'devices/partitions/'+panel_id+commands[command]
        if('STATUS' == command):
            apiMethod = 'GET'
            apiBody = ''
        else:
            apiMethod = 'POST'
            apiBody = '{"forceBypass":'+str(forceBypass).lower()+',"noEntryDelay":'+str(noEntryDelay).lower()+',"silentArming":'+str(silentArming).lower()+',"statePollOnly":false}'

        result = self.api_call(apiUrl, apiMethod, apiBody)
        currentstate = result['data']['attributes']['state']
        self.state = states[currentstate]
        panel_id = result['data']['relationships']['stateInfo']['data']['id']
        _LOGGER.debug ("Current state is "+states[currentstate])
        _LOGGER.debug ("panel_id is "+panel_id)

        if('STATUS' == command):
            apiMethod = 'GET'
            apiBody = ''
            apiUrl = 'devices/sensors'
            result = self.api_call(apiUrl, apiMethod, apiBody)
            self.sensor_status = ''
            for sensor in result['data']:   
                if self.sensor_status:
                    self.sensor_status = self.sensor_status + ", "
                self.sensor_status = self.sensor_status + sensor['attributes']['description'] + " is " + sensor['attributes']['stateText']
        return self.state
        
    @asyncio.coroutine
    def async_update(self):
        """Fetch the latest state."""
        _LOGGER.debug('Calling update on Alarm.com')
        response = None
        if not self.logged_in:
            yield from self.async_login()
        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = self.command('STATUS')

            _LOGGER.debug('Response from Alarm.com: %s', response)
            
        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error("Can not load login page from Alarm.com")
            return False
        return response
    
    
    @asyncio.coroutine
    def _send(self, event):
        """Generic function for sending commands to Alarm.com

        :param event: Event command to send to alarm.com
        """
        _LOGGER.debug('Sending %s to Alarm.com', event)

        if not self.logged_in:
            yield from self.async_login()
        try:
            with async_timeout.timeout(10, loop=self._loop):
                response = self.command(event)

            _LOGGER.debug('Response from Alarm.com: %s', response)
            
        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error("Can not load login page from Alarm.com")
            return False
        return response

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

