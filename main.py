import requests
from fastapi import FastAPI, HTTPException

import models
import helper
from ari import ARIAPP, ARICHANNEL

current_calls = {}

ari_app = ARIAPP()
api = FastAPI()

def find_call(call_id) -> ARICHANNEL:
    return current_calls.get(call_id, False)

@api.on_event("shutdown")
async def shutdown():
    ari_app.destroy()

@api.post("/call")
async def create_call(call: models.Call):
    if call.from_number == '0':
        call.from_number = helper.generate_random_number(call.to_number)

    if call.id in current_calls:
        raise HTTPException(status_code=400, detail="Call already exists")

    channel = ARICHANNEL(call)
    current_calls[channel.data.id] = channel
    return channel.data

@api.delete("/call/{call_id}")
async def delete_call(call_id: str):
    call = find_call(call_id)
    if call:
        call.destroy()
    else:
        raise HTTPException(status_code=404, detail="Call not found")

    return "*ok*"

@ari_app.on_event("start")
def start(channel_id: str):
    call = find_call(channel_id)
    if call:
        call.start()

@ari_app.on_event("status_change")
def status_change(status: str, channel_id: str):
    call = find_call(channel_id)
    if call:
        if status == 'RINGING':
            return

        if status == 'PROGRESS':
            status = 'ringing'

        try:
            requests.get(call.data.status_callback, params={ "status": status })
        except requests.exceptions.RequestException as e:
            print(f"Exception occurred during status change callback: {e}")

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
        try:
            requests.get(call.data.status_callback, params={ "status": "COMPLETED", "CallDuration": call.duration })
        except requests.exceptions.RequestException as e:
            print(f"Exception occurred during channel destroy callback: {e}")
        del current_calls[channel_id]
