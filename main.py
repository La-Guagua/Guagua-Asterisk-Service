import requests
from fastapi import FastAPI

import models
from ari import ARIAPP, ARICHANNEL

current_calls = {}

ari_app = ARIAPP()
api = FastAPI()

def find_call(call_id) -> ARICHANNEL:
    if call_id in current_calls:
        return current_calls[call_id]
    return False

@api.on_event("shutdown")
async def shutdown():
    ari_app.destroy()

@api.post("/call")
async def create_call(call: models.Call):
    channel = ARICHANNEL(call)
    current_calls[ channel.data.id ] = channel
    return channel.data

@api.delete("/call/{call_id}")
async def delete_call(call_id):
    call = find_call(call_id)
    if call:
        call.destroy()

    return "*ok*"

@ari_app.on_event("start")
def start( channel_id: str ):
    call = find_call(channel_id)
    if call:
        call.start()

@ari_app.on_event("status_change")
def status_change(status: str, channel_id: str):
    call = find_call(channel_id)
    if call:
        if status == 'PROGRESS':
            status = 'ringing'

        requests.get(call.data.status_callback, params={ "status": status })

@ari_app.on_event("dtmf_received")
def dtmf_received(channel_id: str, digit: str):
    call = find_call(channel_id)
    if call:    
        call.set_gather(digit)

@ari_app.on_event("payback_finished")
def payback_finished(channel_id: str):
    call = find_call(channel_id)
    if call:
        call.run_action()

@ari_app.on_event("channel_destroyed")
def channel_destroyed(channel_id: str):
    call = find_call(channel_id)
    if call:
        call.destroy()
        requests.get(call.data.status_callback, params={ "status": "COMPLETED", "CallDuration": call.duration })
        del current_calls[channel_id]