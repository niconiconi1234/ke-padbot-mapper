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
from concurrent.futures import ThreadPoolExecutor
from paho.mqtt import subscribe
from threading import Thread
import time

PADBOT_STATUS_URL = os.environ['PADBOT_STATUS_URL']
PADBOT_NAVIGATION_URL = os.environ['PADBOT_NAVIGATION_URL']
DEVICE_NAME = os.environ['DEVICE_NAME']

s_batteryPercentage = "batteryPercentage"
s_batteryStatus = "batteryStatus"
s_actionStatus = "actionStatus"
s_navigationStatus = "navigationStatus"
s_robotLocation = "robotLocation"

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

    def subscribe(self):
        topic = DeviceETPrefix + str(self.device_id) + TwinETGetResultSuffix
        msg = subscribe.simple(topic, hostname=MQTT_HOST, port=MQTT_PORT)
        return DeviceTwinUpdate(**json.loads(msg.payload))

    def create_actual_update_msg(self,
                                 batteryPercentage,
                                 batteryStatus,
                                 actionStatus,
                                 navigationStatus,
                                 robotLocation):
        logging.info('Creating actual update message')
        msg = DeviceTwinUpdate(
            twin={
                s_actionStatus: MsgTwin(actual=TwinValue(value=actionStatus), metadata=TypeMetadata(type="Updated")),
                s_batteryPercentage: MsgTwin(actual=TwinValue(value=batteryPercentage), metadata=TypeMetadata(type="Updated")),
                s_batteryStatus: MsgTwin(actual=TwinValue(value=batteryStatus), metadata=TypeMetadata(type="Updated")),
                s_robotLocation: MsgTwin(actual=TwinValue(value=robotLocation), metadata=TypeMetadata(type="Updated")),
                s_navigationStatus: MsgTwin(actual=TwinValue(value=navigationStatus), metadata=TypeMetadata(type="Updated"))
            }
        )

        return msg

    def get_twin(self, updateMessage: DeviceTwinUpdate):
        get_twin_topic = DeviceETPrefix + str(self.device_id) + TwinETGetSuffix
        self.client.publish(get_twin_topic, updateMessage.model_dump_json())

    def loop_once(self, updateMessage: DeviceTwinUpdate):
        """
        从云端获取期望值, 并操作派宝机器人导航
        再从机器人获取实际值, 并更新到云端
        """
        with ThreadPoolExecutor(max_workers=3) as executor:
            future = executor.submit(self.subscribe)  # subscribe expected value from cloud
            time.sleep(1)  # to ensure when we send request to get expected value on the next line, we have subscribed the mqtt topic to get expected value
            self.get_twin(updateMessage)  # send request to get expected value from cloud
            device_twin_result = future.result()  # get expected value from cloud

        # 根据期望的位置值操作派宝机器人导航，首先获得期望位置和实际位置
        expected = device_twin_result.twin[s_robotLocation].expected
        expectedLocation = expected.value if expected else None
        rsp = requests.get(PADBOT_STATUS_URL)
        if rsp.status_code != 200:
            logging.error('Failed to get padbot status from %s, error code: %s', PADBOT_STATUS_URL, rsp.status_code)
            return
        actualLocation = rsp.json().get('robotLocation', None)

        # 如果actualLocation和expectedLocation不一致, 且机器人不在移动中, 且expectedLocation不为未知, 则开始导航
        if expectedLocation and expectedLocation != actualLocation and actualLocation != 'MOVING' and expectedLocation != 'UNKNOWN':
            # 开始导航，因为这个http请求会阻塞，直到导航结束，所以我们开一个新的线程来发送请求
            t = Thread(target=requests.post, args=(PADBOT_NAVIGATION_URL, ), kwargs={'json': {'targetPoint': expectedLocation}})
            t.start()

        rsp = requests.get(PADBOT_STATUS_URL)
        if rsp.status_code != 200:
            logging.error('Failed to get padbot status from %s, error code: %s', PADBOT_STATUS_URL, rsp.status_code)
            return

        padbotStatus = rsp.json()
        padbotStatus = defaultdict(lambda: 'UNKNOWN', padbotStatus)

        batteryPercentage = str(padbotStatus['batteryPercentage'])
        batteryStatus = padbotStatus['batteryStatus']
        actionStatus = padbotStatus['actionStatus']
        navigationStatus = padbotStatus['navigationStatus']
        robotLocation = padbotStatus['robotLocation']

        logging.info('Got padbot status: batteryPercentage: %s, batteryStatus: %s, actionStatus: %s, navigationStatus: %s, robotLocation: %s',
                     batteryPercentage, batteryStatus, actionStatus, navigationStatus, robotLocation)

        update_msgs = self.create_actual_update_msg(batteryPercentage, batteryStatus, actionStatus, navigationStatus, robotLocation)
        self.change_twin_value(update_msgs)  # send actual value to cloud
        logging.info('Update message sent to cloud')

    def change_twin_value(self, updateMessage: DeviceTwinUpdate):
        topic = DeviceETPrefix + str(self.device_id) + TwinETCloudSyncSuffix
        self.client.publish(topic, updateMessage.model_dump_json())


def main():
    mapper = PadBotMapper()
    mapper.change_device_state("online")  # change device state to online
    msg = mapper.create_actual_update_msg('Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown')
    while True:
        mapper.loop_once(msg)
        time.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    main()
