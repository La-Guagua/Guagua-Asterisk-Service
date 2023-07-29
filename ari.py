import uuid
import json
import time
import websocket
import requests
import config
import models
import logging
import traceback
from threading import Thread, Event
import xml.etree.ElementTree as ET

logging.basicConfig(filename='./storage/logs/error.log', level=logging.ERROR, format='%(asctime)s %(levelname)s %(name)s %(message)s')

class ARIREST:
    def __init__(self) -> None:
        self.req_base = f"http://{config.ARI_SERV}:{config.ARI_PORT}/ari"

    def get_application(self):
        url = f"{self.req_base}/applications/{config.APP_NAME}"
        res = requests.get(url, auth=(config.ARI_USER, config.ARI_PWD))
        if res.status_code == 200:
            return res.json()
        
        return False

    def create_channel(self, call: models.Call) -> object:
        """
        This function creates a channel using the given trunk, to_number, and from_number and stores it in a
        dictionary.
        
        :param trunk: The trunk parameter is a string that represents the name of the trunk that the call
        will be routed through. A trunk is a communication line that connects a PBX (Private Branch
        Exchange) to the PSTN (Public Switched Telephone Network) or to another PBX
        :param to_number: The phone number that the channel will be connected to
        :param from_number: The phone number that will be displayed as the caller ID for the outgoing call
        """
        url = f"{self.req_base}/channels/{call.id}?endpoint=PJSIP/{call.to_number}@{call.trunk}&app={config.APP_NAME}&appArgs={call.id}&callerId={call.from_number}&timeout=-1"
        res = requests.post(url, auth=(config.ARI_USER, config.ARI_PWD))
        if res.status_code == 200:
            return res.json()

        return False

    def destroy_channel(self, id) -> bool:
        """
        This function sends a DELETE request to the Asterisk API to destroy a channel with the given ID and
        prints the response if the request is successful.
        
        :param id: The ID of the channel that needs to be destroyed
        """
        url = f"{self.req_base}/channels/{id}"
        res = requests.delete(url, auth=(config.ARI_USER, config.ARI_PWD))
        return res.status_code == 204
    
    def channel_play(self, id, media_uri) -> bool:
        url = f"{self.req_base}/channels/{id}/play?media=sound:{media_uri}"
        res = requests.post(url, auth=(config.ARI_USER, config.ARI_PWD))
        return res.status_code == 201

class ARICHANNEL:
    data: models.Call
    running: bool = True
    duration: int = 0

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
        if hasattr(self.data, "id"):
            return self.__ari_rest.destroy_channel(self.data.id)
        return False
    
    def start(self):
        def duration_counter():
            self.duration_event = Event()
            while not self.duration_event.wait(timeout=1):
                if not self.running or self.duration > 180:
                    self.destroy()
                    break
                self.duration = self.duration + 1

        thread = Thread(target = duration_counter)
        thread.start()   
     
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

        def gather_timer():
            counter = 0
            self.gather_event = Event()
            while not self.gather_event.wait(timeout=1):
                counter = counter + 1
                if counter >= int(attrib["timeout"]):
                    self.destroy()
                    break


        thread = Thread(target = gather_timer)
        thread.start()

    def set_gather(self, digit):
        self.gather_digits.append(digit)
        if len(self.gather_digits) == self.gather_numDigits:
            self.waiting_gather = False
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
        self.event_thread = Thread(target=self.checking_interval)
        self.event_thread.start()

    def connect(self):
        self.ws.run_forever(reconnect=1)

    def destroy(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def start(self):
        self.running = True
        url = f"ws://{config.ARI_SERV}:{config.ARI_PORT}/ari/events?app={config.APP_NAME}&api_key={config.ARI_USER}:{config.ARI_PWD}"
        self.ws = websocket.WebSocketApp(url, on_message=self.on_message, on_open=self.on_open, on_error=self.on_error)
        self.wst = Thread(target=self.connect)
        self.wst.start()

    def reset(self):
        self.destroy()
        self.start()

    def checking_interval(self):
        while self.running:
            time.sleep(60)
            ari_rest = ARIREST()
            if not ari_rest.get_application():
                logging.info("Reseting")
                self.reset()

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

