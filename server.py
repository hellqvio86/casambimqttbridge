#!/usr/bin/python3

import casambi
import yaml
import logging
import logging.handlers
import json
import time
import websocket
import paho.mqtt.client as mqtt
import queue
import multiprocessing
import socket
import re
from time import sleep
from setproctitle import setproctitle

def parse_config(config_file='casambi.yaml'):
    config = None

    with open(config_file, 'r') as stream:
        config = yaml.safe_load(stream)

    if 'api_key' not in config:
        raise casambi.ConfigException('api_key is not present in configuration')

    if 'email' not in config:
        raise casambi.ConfigException('email is not present in configuration')

    if 'network_password' not in config:
        raise casambi.ConfigException('api_key is not present in configuration')

    if 'user_password' not in config:
        raise casambi.ConfigException('api_key is not present in configuration')

    return config


def set_unit_value(api_key, email, network_password, user_password, unit_id):
    user_session_id = casambi.create_user_session(email=email, api_key=api_key, user_password=user_password)
    network_ids = casambi.create_network_session(api_key=api_key, email=email, network_password=network_password)
    wire_id = 1

    network_id = list(network_ids)[0]

    network_information = casambi.get_network_information(user_session_id=user_session_id, network_id=network_id, api_key=api_key)

    web_sock = casambi.ws_open_message(user_session_id=user_session_id, network_id=network_id, api_key=api_key)
    casambi.turn_unit_on(unit_id=unit_id, web_sock=web_sock, wire_id=wire_id)

    casambi.ws_close_message(web_sock=web_sock, wire_id=wire_id)


def casambi_worker(write_queue, command_queue, logger_queue, api_key, email, network_password, user_password):
    setproctitle('casambi_worker')

    worker_configurer(logger_queue)
    innerlogger = logging.getLogger('worker')

    user_session_id = casambi.create_user_session(email=email, api_key=api_key, user_password=user_password)
    network_ids = casambi.create_network_session(api_key=api_key, email=email, network_password=network_password)
    wire_id = 1

    network_id = list(network_ids)[0]

    units = {}

    while(True):
        network_information = casambi.get_network_information(user_session_id=user_session_id, network_id=network_id, api_key=api_key)
        network_units = network_information['units']

        for key, value in network_units.items():
            unit_id = "{}".format(key)

            if unit_id in units:
                continue #already known

            unit = {}

            unit['name'] = (value['name']).strip()
            unit['value'] = 0 # Lets guess the unit is off

            units[unit_id] = unit

        innerlogger.debug("casambi_worker: units: {}".format(units))

        write_queue.put(units)

        web_sock = casambi.ws_open_message(user_session_id=user_session_id, network_id=network_id, api_key=api_key, wire_id=wire_id)
        web_sock.settimeout(0.1)

        while(True):
            casambi_msg = None
            command_msgs = None

            try:
                casambi_msg = web_sock.recv()
            except websocket._exceptions.WebSocketConnectionClosedException:
                innerlogger.debug("casambi_worker: Socket closed, reopening")

                break
            except socket.timeout:
                pass
            except websocket._exceptions.WebSocketTimeoutException:
                pass
            except TimeoutError:
                innerlogger.debug("casambi_worker: Socket closed, reopening")

                break


            try:
                command_msgs = command_queue.get(block=False)
            except queue.Empty:
                pass

            if command_msgs:
                for message in command_msgs:
                    value = message['value']
                    unit_id = message['id']
                    name = units[unit_id]['name']

                    innerlogger.debug("casambi_worker: recieved command message: \"{}\"".format(message))

                    #set_unit_value(api_key, email, network_password, user_password, unit_id)

                    #casambi.set_unit_value(web_sock=web_sock, unit_id=unit_id, value=value, wire_id=wire_id)

                    target_controls = { 'Dimmer': {'value': value }}

                    casambi_message = {
                        "wire": wire_id,
                        "method": 'controlUnit',
                        "id": int(unit_id),
                        "targetControls": target_controls
                    }

                    json_msg = json.dumps(casambi_message)
                    web_sock.send(json_msg)

                    innerlogger.debug("casambi_worker: target_controls: {} casambi_message: {} json_msg {}".format(target_controls, casambi_message, json_msg))

            if (casambi_msg == '') or not casambi_msg:
                continue


            #result = __clean_up_json(msg=result)
            data = None


            try:
                data = json.loads(casambi_msg)
            except json.decoder.JSONDecodeError as err:
                innerlogger.error("casambi_worker: Caught exception, data: \"\n\n{}\n\n\", exception: {}".format(data, err))
                continue

            innerlogger.debug("casambi_worker: recieved data: {}".format(data))

            #  'controls': [{'type': 'Overheat', 'status': 'ok'}, {'type': 'Dimmer', 'value': 0.0}], 'sensors': [], 'method': 'unitChanged', 'online': False, 'id': 12, 'on': True, 'status': 'ok'}
            dimmer_value = 0
            unit_id = -1

            if 'controls' in data:
                controls = data['controls']
                for control in controls:
                    if control['type'] == 'Dimmer':
                        dimmer_value = control['value']

            if 'id' in data:
                unit_id = "{}".format(data['id'])

            if unit_id != -1:
                if (unit_id in units):
                    units[unit_id]['id'] = unit_id
                    units[unit_id]['value'] = dimmer_value

                    write_queue.put(units)
                else:
                    innerlogger.debug("casambi_worker: unknown data: {}".format(data))

            innerlogger.debug("casambi_worker: units: {}".format(units))


def mqtt_worker(casambi_reader_queue, mqtt_request_queue, logger_queue, mqtt_server, mqtt_server_port, mqtt_user, mqtt_password):
    '''
    - platform: mqtt
    name: "Spot köksö"
    state_topic: "casambi/light/7/status"
    command_topic: "casambi/light/7/switch"
    payload_off: "0"
    brightness_state_topic: 'casambi/light/7/brightness'
    brightness_command_topic: 'casambi/light/7/brightness/set'
    on_command_type: 'brightness'
    '''
    setproctitle('casambi_mqtt_worker')

    worker_configurer(logger_queue)
    innerlogger = logging.getLogger('worker')


    client = mqtt.Client()
    client.username_pw_set(mqtt_user, password=mqtt_password)

    topics = []

    client.on_connect = on_connect
    client.on_message = on_message

    client.user_data_set((topics, mqtt_request_queue, innerlogger))

    innerlogger.debug("mqtt_worker: Connecting to MQTT server {}:{}".format(mqtt_server, mqtt_server_port))

    client.connect(mqtt_server, 1883, 60)

    # Blocking call that processes network traffic, dispatches callbacks and
    # handles reconnecting.
    # Other loop*() functions are available that give a threaded interface and a
    # manual interface.
    #client.loop_forever()

    while(True):
        client.loop(.1)

        casambi_read_msg = None

        try:
            casambi_read_msg = casambi_reader_queue.get(block=True, timeout=.1)
        except queue.Empty:
            pass

        if casambi_read_msg:
            innerlogger.debug("mqtt_worker: Read following from Casambi queue: {}".format(casambi_read_msg))


        if isinstance(casambi_read_msg, dict):
            for id, item in casambi_read_msg.items():
                payload = None
                topic_change = False
                brigness = 0
                name = item['name']

                status_topic = "casambi/light/{}/status".format(id)
                command_topic = "casambi/light/{}/switch".format(id)
                brightness_state_topic = "casambi/light/{}/brightness".format(id)
                brightness_command_topic = "casambi/light/{}/brightness/set".format(id)
                name_topic = "casambi/light/{}/name".format(id)

                if item['value'] == 0:
                    payload = 'OFF'
                else:
                    payload = 'ON'
                    brigness = round(item['value'] * 255)
                innerlogger.debug("mqtt_worker: Sending topic=\"{}\" payload=\"{}\" (light name: {})".format(status_topic, payload, name))
                client.publish(topic=status_topic, payload=payload)
                client.publish(topic=brightness_state_topic, payload=brigness)
                client.publish(topic=name_topic, payload=name)


                if not (command_topic in topics):
                    topics.append(command_topic)
                    innerlogger.debug("mqtt_worker: subscribing on topic=\"{}\"".format(command_topic))
                    client.subscribe(command_topic, qos=0)
                    topic_change = True

                if not (brightness_command_topic in topics):
                    topics.append(brightness_command_topic)
                    innerlogger.debug("mqtt_worker: subscribing on topic=\"{}\"".format(brightness_command_topic))
                    client.subscribe(brightness_command_topic, qos=0)
                    topic_change = True

                if topic_change:
                    client.user_data_set((topics, mqtt_request_queue, innerlogger))


def on_message(client, userdata, message):
    digit_regexp = re.compile('\d+')
    payload = (message.payload).decode('UTF-8')

    (topics, mqtt_request_queue, innerlogger) = userdata

    # Off message:
    # Received message 'b'0'' on topic 'casambi/light/1/switch' with QoS 0
    # on_message: Received message 'b'255'' on topic 'casambi/light/12/brightness/set' with QoS 0
    # worker   DEBUG    on_message: Received message 'b'OFF'' on topic 'casambi/light/12/switch' with QoS 0

    innerlogger.debug("on_message: Received message '" + payload + "' on topic '"
        + message.topic + "' with QoS " + str(message.qos))

    parts = (message.topic).split('/')
    unit_id = parts[2]

    messages = []

    if parts[-1] == 'switch' and (digit_regexp.match(payload)):
        messages = []

        unit = {}
        unit['value'] = round(float(payload)/255, 1)
        unit['id'] = unit_id

        if unit['value'] == '1':
            unit['value'] = 1
        elif unit['value'] == '0':
            unit['value'] = 0

        messages.append(unit)

    elif parts[-1] == 'switch' and payload == "OFF":
        unit = {}
        unit['value'] = 0
        unit['id'] = unit_id

        messages.append(unit)
    elif parts[-1] == 'switch' and payload == "ON":
        unit = {}
        unit['value'] = 1
        unit['id'] = unit_id

        messages.append(unit)
    elif parts[-1] == 'set' and parts[-2] == 'brightness':
        messages = []

        unit = {}
        unit['value'] = round(float(payload)/255, 1)
        unit['id'] = unit_id

        if unit['value'] == 1:
            unit['value'] = 1
        elif unit['value'] == 0:
            unit['value'] = 0

        messages.append(unit)
    else:
        innerlogger.debug("on_message: unhandled message '" + payload + "' on topic '"
            + message.topic + "' with QoS " + str(message.qos))

    innerlogger.debug("on_message: unit_id: {} parts: {} messages: {}".format(unit_id, parts, messages))

    if len(messages) != 0:
        innerlogger.debug("on_message: putting following messages on queue: {}".format(messages))
        mqtt_request_queue.put(messages)


def on_connect(client, userdata, flags, rc):
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.


    (topics, mqtt_request_queue, innerlogger) = userdata

    innerlogger.debug("on_connect: Connected with result code " + str(rc))

    client.subscribe('casambi', qos=0)

    for topic in topics:
        _LOGGER.debug("on_connect: subscribing on topic=\"{}\"".format(topic))
        client.subscribe(topic, qos=0)


def worker_configurer(queue):
    h = logging.handlers.QueueHandler(queue)  # Just the one handler needed
    root = logging.getLogger()
    root.addHandler(h)
    # send all messages, for demo; no other level or filter logic applied.
    root.setLevel(logging.DEBUG)


def listener_configurer():
    root = logging.getLogger()
    #file_handler = logging.handlers.RotatingFileHandler('mptest.log', 'a', 300, 10)
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(process)d %(processName)-10s %(name)-8s %(levelname)-8s %(message)s')
    #file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    #root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG)



def logger_worker(queue, verbose):
    setproctitle('casambi_logger')

    listener_configurer()
    while True:
        while not queue.empty():
            record = queue.get()
            logger = logging.getLogger(record.name)
            logger.handle(record)  # No level or filter logic applied - just do it!
        sleep(0.5)


def main():
    verbose = True
    config = parse_config()

    api_key = config['api_key']
    email = config['email']
    network_password = config['network_password']
    user_password = config['user_password']
    mqtt_password = config['mqtt_password']
    mqtt_server = config['mqtt_server']
    mqtt_server_port = config['mqtt_server_port']
    mqtt_user = config['mqtt_user']

    casambi_reader_queue = multiprocessing.Queue()
    mqtt_request_queue = multiprocessing.Queue()
    logger_queue = multiprocessing.Queue()

    casambi_process = multiprocessing.Process(target=casambi_worker, args=(casambi_reader_queue, mqtt_request_queue, logger_queue, api_key, email, network_password, user_password), name='Casambi')
    #casambi_process.daemon=True
    casambi_process.start()

    mqtt_process = multiprocessing.Process(target=mqtt_worker, args=(casambi_reader_queue, mqtt_request_queue, logger_queue, mqtt_server, mqtt_server_port, mqtt_user, mqtt_password), name='MQTT')
    #mqtt_process.daemon=True
    mqtt_process.start()

    logger_process = multiprocessing.Process(target=logger_worker, args=(logger_queue, verbose), name='Logger')
    #logger_process.daemon=True
    logger_process.start()


if __name__ == "__main__":
    main()
