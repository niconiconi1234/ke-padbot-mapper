from config import MQTT_HOST, MQTT_PORT, CONFIG_MAP_PATH
import logging
import paho.mqtt.client as mqtt
from typing import Optional
import os
import json
from entities import DeviceProfiles, DeviceStateUpdate, DeviceTwinUpdate, MsgTwin, TwinValue, TypeMetadata
import time
import requests
from collections import defaultdict

PADBOT_STATUS_URL = os.environ['PADBOT_STATUS_URL']
DEVICE_NAME = os.environ['DEVICE_NAME']

s_batteryPercentage = "batteryPercentage"
s_batteryStatus = "batteryStatus"
s_actionStatus = "actionStatus"

DeviceETPrefix = "$hw/events/device/"
DeviceETStateUpdateSuffix = "/state/update"
TwinETGetSuffix = "/twin/get"
TwinETGetResultSuffix = "/twin/get/result"
TwinETCloudSyncSuffix = "/twin/update"


class PadBotMapper:

    device_id: Optional[str] = None

    def __init__(self) -> None:
        logging.info("Initialing PadBotMapper")
        self.client = mqtt.Client()  # create new instance of mqtt client
        # connect to mqtt broker at edge
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.read_config_map()

    def read_config_map(self):
        """
        Read deviceProfile.json
        """
        logging.info("Reading config map")

        with open(CONFIG_MAP_PATH) as f:
            data = json.load(f)
            device_profile = DeviceProfiles(**data)

        for device in device_profile.deviceInstances:
            if device.name == DEVICE_NAME:
                self.device_id = device.id
                logging.info("Device id: %s", self.device_id)
                break

    def change_device_state(self, state):
        """
        change device state
        """
        logging.info('Changing device state to %s', state)
        state_update_msg = DeviceStateUpdate(state=state)
        msg_json = state_update_msg.model_dump_json()

        state_update_url = DeviceETPrefix + str(self.device_id) + DeviceETStateUpdateSuffix
        self.client.publish(state_update_url, msg_json)

    def create_actual_update_msg(self,
                                 batteryPercentage,
                                 batteryStatus,
                                 actionStatus):
        """
        需要向云端更新机器人状态时，创建更新消息(包括电量百分比、电量状态、动作状态)
        """
        logging.info('Creating actual update message')
        actionStatus_update_msg = DeviceTwinUpdate(
            twin={
                s_actionStatus: MsgTwin(actual=TwinValue(value=actionStatus), metadata=TypeMetadata(type="Updated")),
            }
        )
        batteryPercentage_update_msg = DeviceTwinUpdate(
            twin={
                s_batteryPercentage: MsgTwin(actual=TwinValue(value=batteryPercentage), metadata=TypeMetadata(type="Updated")),
            }
        )
        batteryStatus_update_msg = DeviceTwinUpdate(
            twin={
                s_batteryStatus: MsgTwin(actual=TwinValue(value=batteryStatus), metadata=TypeMetadata(type="Updated"))
            }
        )

        return actionStatus_update_msg, batteryPercentage_update_msg, batteryStatus_update_msg

    def get_twin(self, updateMessage: DeviceTwinUpdate):
        get_twin_topic = DeviceETPrefix + str(self.device_id) + TwinETGetSuffix
        self.client.publish(get_twin_topic, updateMessage.model_dump_json())

    def loop_once(self):
        """
        向云端上报机器人状态
        首先调用请求PADBOT_STATUS_URL获取机器人状态, 再将状态上报到云端
        """
        rsp = requests.get(PADBOT_STATUS_URL)
        if rsp.status_code != 200:
            logging.error('Failed to get padbot status from %s, error code: %s', PADBOT_STATUS_URL, rsp.status_code)

        padbotStatus = rsp.json()
        padbotStatus = defaultdict(lambda: 'UNKNOWN', padbotStatus)

        batteryPercentage = str(padbotStatus['batteryPercentage'])
        batteryStatus = padbotStatus['batteryStatus']
        actionStatus = padbotStatus['actionStatus']

        logging.info('Got padbot status: batteryPercentage: %s, batteryStatus: %s, actionStatus: %s',
                     batteryPercentage, batteryStatus, actionStatus)

        update_msgs = self.create_actual_update_msg(batteryPercentage, batteryStatus, actionStatus)
        for msg in update_msgs:
            self.change_twin_value(msg)

        logging.info('Update message sent to cloud')

    def change_twin_value(self, updateMessage: DeviceTwinUpdate):
        topic = DeviceETPrefix + str(self.device_id) + TwinETCloudSyncSuffix
        self.client.publish(topic, updateMessage.model_dump_json())


def main():
    mapper = PadBotMapper()
    mapper.change_device_state("online")  # change device state to online
    while True:
        mapper.loop_once()
        time.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
