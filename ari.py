import uuid
import json
import time
import websocket
import requests
import config
import models
import logging
import traceback
import random
from datetime import datetime
from requests.auth import HTTPBasicAuth
from threading import Thread, Timer
import xml.etree.ElementTree as ET

logging.basicConfig(filename='./storage/logs/error.log', level=logging.ERROR, format='%(asctime)s %(levelname)s %(name)s %(message)s')

config.APP_NAME = config.APP_NAME+str( random.randint(1, 100) )

class ARIREST:
    def __init__(self) -> None:
        self.req_base = f"http://{config.ARI_SERV}:{config.ARI_PORT}/ari"
        self.session = requests.Session()  # Create a Session instance
        self.session.auth = HTTPBasicAuth(config.ARI_USER, config.ARI_PWD)  # Set up basic authentication

    def get_application(self):
        url = f"{self.req_base}/applications/{config.APP_NAME}"
        try:
            res = self.session.get(url)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Exception occurred during get application: {e}")
            return False

    def create_channel(self, call: models.Call) -> object:
        url = f"{self.req_base}/channels/{call.id}?endpoint=PJSIP/{call.to_number}@{call.trunk}&app={config.APP_NAME}&appArgs={call.id}&callerId={call.from_number}&timeout=-1"
        try:
            res = self.session.post(url)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Exception occurred during create channel: {e}")
            return False

    def destroy_channel(self, id) -> bool:
        url = f"{self.req_base}/channels/{id}"
        try:
            res = self.session.delete(url)
            res.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Exception occurred during destroy channel: {e}")
            return False
    
    def channel_play(self, id, media_uri) -> bool:
        url = f"{self.req_base}/channels/{id}/play?media=sound:{media_uri}"
        try:
            res = self.session.post(url)
            res.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Exception occurred during channel play: {e}")
            return False

class ARICHANNEL:
    data: models.Call
    running: bool = True
    duration: int = 0

    answer_datetime: datetime = False
    hangout_datetime: datetime = False

    gather_timer: Timer = None
    waiting_gather = False
    gather_action = ""
    gather_numDigits = 1
    gather_digits = []
    
    remaining_actions = []

    def __init__(self, data: models.Call) -> None:
        self.data = data
        self.data.id = str(uuid.uuid4())

        self.__ari_rest = ARIREST()
        self.create()

    def create(self):
        return self.__ari_rest.create_channel(self.data)

    def destroy(self) -> bool:
        self.running = False
        self.hangout_datetime = datetime.now()
        if self.answer_datetime:
            duration = (self.hangout_datetime - self.answer_datetime).total_seconds()
            self.duration = int( duration + 1 )

        if hasattr(self.data, "id"):
            return self.__ari_rest.destroy_channel(self.data.id)
        return False
    
    def start(self):     
        self.answer_datetime = datetime.now()
        self.get_actions(self.data.action_url)
        self.run_action()                

    def play(self, media_uri, attrib):
        self.__ari_rest.channel_play(self.data.id, media_uri)

    def say(self, text, attrib):
        self.run_action()

    def gather(self, text, attrib):
        self.waiting_gather = True
        self.gather_action = attrib["action"]
        self.gather_numDigits = int(attrib["numDigits"])
        self.gather_digits = []

        def gather_timeout():
            self.destroy()

        self.gather_timer = Timer( int(attrib["timeout"]), gather_timeout )
        self.gather_timer.start()

    def set_gather(self, digit):
        self.gather_digits.append(digit)
        if len(self.gather_digits) == self.gather_numDigits:
            self.gather_timer.cancel()
            digits = "".join(self.gather_digits)
            self.redirect(self.gather_action, { "Digits": digits })
            self.gather_action = ""
            self.gather_numDigits = 1
            self.gather_digits = []

    def redirect(self, action_url, attrib={}): 
        self.get_actions(action_url, attrib)
        self.run_action()
    
    def get_actions(self, action_url, params={}):
        try:
            res = requests.get(action_url, params=params)
            if not res.status_code == 200:
                return False

            root = ET.fromstring(res.text)
            self.remaining_actions = []
            for child in root:
                self.remaining_actions.append(child)
        except Exception as e:
            logging.error(f"Exception occurred during get actions: {e}\n{traceback.format_exc()}")

    def run_action(self):
        if len(self.remaining_actions) > 0:
            self.current_action = self.remaining_actions.pop(0)
            getattr(self, self.current_action.tag.lower())( self.current_action.text, self.current_action.attrib )
        else:
            self.destroy()

class ARIAPP:
    events = {}
    ws = False
    running: bool = True
    event_thread: Thread

    def __init__(self) -> None:
        self.start()

    def connect(self):
        self.ws.run_forever(reconnect=1)

    def destroy(self):
        self.running = False
        if self.ws:
            self.ws.close()
            self.wst.join()

    def start(self):
        self.running = True
        print("Stasis App Started ", config.APP_NAME)
        url = f"ws://{config.ARI_SERV}:{config.ARI_PORT}/ari/events?app={config.APP_NAME}&api_key={config.ARI_USER}:{config.ARI_PWD}"
        self.ws = websocket.WebSocketApp(url, on_message=self.on_message, on_open=self.on_open, on_error=self.on_error)
        self.wst = Thread(target=self.connect)
        self.wst.start()

    def reset(self):
        self.destroy()

    def on_close(self, ws):
        logging.info("Websocket was closed")

    def on_error(self, ws, err):
        logging.error(err)

    def on_open(self, ws):
        logging.info("STASIS APP STARTED")

    def on_message(self, ws, message):
        try:
            def get_channel_event(event):
                for key in ['peer', 'channel', 'args', 'playback']:
                    if key in event:
                        if key == 'peer' or key == 'channel':
                            return event[key].get("id")
                        elif key == 'args':
                            return event.get("args")[0]
                        elif key == 'playback':
                            return event["playback"]["target_uri"].split("channel:")[1]
                return None

            event = json.loads(message)
            channel_id = get_channel_event(event)

            if "dialstatus" in event:
                self.run_event("status_change", event["dialstatus"], channel_id)

            if event['type'] == 'StasisStart':
                self.run_event("start", channel_id)
            
            elif event['type'] == 'ChannelDtmfReceived':
                self.run_event("dtmf_received", channel_id, event["digit"])

            elif event['type'] == 'PlaybackFinished':
                self.run_event("payback_finished", channel_id)
                
            elif event['type'] == 'ChannelDestroyed':
                self.run_event("channel_destroyed", channel_id)

        except Exception as e:
            if not self.running:
                return

            logging.error(f"Exception occurred: {e}\n{traceback.format_exc()}")


    def on_event(self, event_name):
        def decorator_event(func):
            self.events[event_name] = func
        return decorator_event
    
    def run_event(self, event_name, *args):
        try:
            if event_name in self.events:
                self.events[event_name](*args)
        except Exception as err:
            logging.error(f"Error in event '{event_name}': {err}\n{traceback.format_exc()}")

