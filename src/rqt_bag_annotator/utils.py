import os
import re
from rosgraph_msgs.msg import Clock
import genpy.message
import numpy as np
import rospy

date_re = re.compile('.+_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})_(\d{2,3})\.bag')

def annotation_path(bag_path, extra='annotations'):
    path_parts = bag_path.split('.')
    if len(path_parts) >= 3 and path_parts[-2] == 'cropped':
        path_parts.pop(-2)

    path_parts.insert(-1, extra)
    return '.'.join(path_parts)

def bag_sort_fn(a, b):
    na = os.path.split(a)[-1]
    nb = os.path.split(b)[-1]

    date_a = int(''.join(date_re.match(na).groups()))
    date_b = int(''.join(date_re.match(nb).groups()))
    return cmp(date_a, date_b)

def sort_bags(bags):
    return sorted(bags, cmp=bag_sort_fn)

class MonitorPublisher(object):
    def __init__(self, times=[], messages=[]):
        self.update_msgs(times, messages)
        self.last_time = rospy.Time(0)
        self.publishers = {}
        self.clock_sub = None

    def start(self):
        self.clock_sub = rospy.Subscriber('/clock', Clock, self.tick)

    def stop(self):
        if self.clock_sub:
            self.clock_sub.unregister()

    def update_msgs(self, times, messages):
        self.msgs = messages
        self.times = np.asarray(times)

    def msgs_to_publish(self, time):
        elems = (self.last_time < self.times) & (self.times <= time)
        return [msg for idx, msg in enumerate(self.msgs) if elems[idx]]

    def tick(self, clock_msg):
        for topic, msg in self.msgs_to_publish(clock_msg.clock):
            if topic not in self.publishers:
                self.publishers[topic] = rospy.Publisher(topic, genpy.message.get_message_class(msg._type))
            self.publishers[topic].publish(msg)
        self.last_time = clock_msg.clock

    def __del__(self):
        self.stop()
        for pub in self.publishers.values():
            pub.unregister()
