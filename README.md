# Casambi to MQTT bridge
![GitHub last commit](https://img.shields.io/github/last-commit/hellqvio86/casambimqttbridge) ![GitHub issues](https://img.shields.io/github/issues-raw/hellqvio86/casambimqttbridge) 

Python script for controlling lights, this script utilises casambi python library (https://github.com/olofhellqvist/casambi).

## Setup
1. Request developer api key from Casambi: https://developer.casambi.com/
2. Setup a site in Casambi app: http://support.casambi.com/support/solutions/articles/12000041325-how-to-create-a-site
3. Install necessary dependency: 
```
pip install casambi
pip install paho-mqtt
pip install setproctitle 
```
4. Create a casambi.yaml configuration file, example:
```yaml

api_key: '...'
email: 'replaceme@replaceme.com'
network_password:  'secret'
user_password: 'secret'
mqtt_server: '192.168.1.1'
mqtt_server_port: 1883
mqtt_user: 'casambi'
mqtt_password: '...'
```

5. Start server.py

6. Setup MQTT lights in home assistant, example configuration:

```
light:
  - platform: mqtt
    name: "Hus nummer"
    state_topic: "casambi/light/12/status"
    command_topic: "casambi/light/12/switch"
    payload_on: "ON"
    payload_off: "OFF"
    brightness_state_topic: 'casambi/light/12/brightness'
    brightness_command_topic: 'casambi/light/12/brightness/set'
    on_command_type: 'brightness'
  - platform: mqtt
    name: "Spottar bad"
    state_topic: "casambi/light/1/status"
    command_topic: "casambi/light/1/switch"
    payload_on: "ON"
    payload_off: "OFF"
    brightness_state_topic: 'casambi/light/1/brightness'
    brightness_command_topic: 'casambi/light/1/brightness/set'
    on_command_type: 'brightness'
```
Get the unit_ids either from casambi api or from the MQTT broker (topic casambi/light)

7. Enjoy your Casambi lights in home assistant

## Authors

* **Olof Hellqvist** - *Initial work*

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details

## Disclaimer
This project is neither affiliated with nor endorsed by Casambi.

This project is no longer activily developed, I have moved on to this  https://github.com/hellqvio86/home_assistant_casambi project.
