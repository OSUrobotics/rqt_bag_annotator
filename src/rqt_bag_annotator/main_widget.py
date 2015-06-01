from python_qt_binding import loadUi
from python_qt_binding.QtGui import QWidget, QTreeWidgetItem,\
    QFileDialog
from python_qt_binding.QtCore import Qt, QTimer, QAbstractListModel,\
    QModelIndex

import rosgraph
import rospkg
import rospy
import rosbag
from std_msgs.msg import String, Duration, Empty

import genpy.message

import os
import re

from .utils import annotation_path, sort_bags, MonitorPublisher

nan = float('nan')
inf = float('inf')


class Monitor(object):

    def __init__(self, topic_name, topic_type):
        self.topic_name = topic_name
        self.topic_type = topic_type
        self.msg_cls = genpy.message.get_message_class(topic_type)
        self.last_msg = None

    def subscribe(self):
        self._subscriber = rospy.Subscriber(
            self.topic_name, self.msg_cls, self._callback, queue_size=1)

    def _callback(self, msg):
        self.last_msg = msg

    def unsubscribe(self):
        self._subscriber.unregister()


class TopicMonitor(QAbstractListModel):

    def __init__(self, *args, **kwargs):
        super(TopicMonitor, self).__init__(*args, **kwargs)
        self.monitors = {}

    def add_monitor(self, topic_name, topic_type):
        return self.add_item(Monitor(topic_name, topic_type))

    def add_item(self, item):
        if item.topic_name not in self.monitors:
            self.beginInsertRows(
                QModelIndex(), self.rowCount(), self.rowCount() + 1)
            self.monitors[item.topic_name] = item
            self.insertRows(self.rowCount(), 1)
            self.endInsertRows()
        return item

    def _delete_monitor(self, topic_name):
        if topic_name in self.monitors:
            monitor = self.monitors[topic_name]
            monitor.unsubscribe()
            del self.monitors[topic_name]

    def remove_row(self, row):
        self.beginRemoveRows(QModelIndex(), row.row(), row.row())
        self._delete_monitor(self.data(row))
        self.endRemoveRows()

    def __getitem__(self, key):
        return self.monitors[key]

    # for QAbstractListModel
    def rowCount(self, parent=QModelIndex()):
        return len(self.monitors)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if index.row() > self.rowCount() or index.row() < 0:
            return None

        if role == Qt.DisplayRole:
            return sorted(self.monitors.items())[index.row()][0]

        return None


class SimpleMessageItem(QTreeWidgetItem):
    def updateChanged(self):
        exec('self.setData(3, Qt.UserRole, %s)' % self.text(3))


class MessageItem(QTreeWidgetItem):
    _types = set([genpy.message.Message, genpy.rostime.TVal])

    def __init__(self, msg, name, stamp, toplevel=True):
        super(MessageItem, self).__init__()
        if toplevel:
            self.setText(0, str(stamp.to_sec()))
            self.setData(0, Qt.UserRole, stamp)
            self.setFlags(self.flags() | Qt.ItemIsEditable)
        self.setText(1, name)
        self.setData(1, Qt.UserRole, name)
        if hasattr(msg, '_type'):
            self.setText(2, msg._type)
        else:
            self.setText(2, type(msg).__name__)
        self.setData(2, Qt.UserRole, type(msg))
        self.stamp = stamp
        self._topic = name
        self.msg = msg
        self._add_msgs(msg)
        self.toplevel = toplevel
        self.setExpanded(True)
        # self.itemChanged.connect(self._itemChanged)

    @property
    def topic(self):
        return self.text(1)

    def _add_msgs(self, msg):
        for attr in dir(msg):
            try:
                obj = getattr(msg, attr)
                if not attr.startswith('_') and not callable(obj):
                    # is it a ROS message?
                    if len(self._types.intersection(type(obj).__bases__)) > 0:
                        self.addChild(MessageItem(obj, attr, None, toplevel=False))
                    # it is not
                    else:
                        child_item = SimpleMessageItem(self)
                        child_item.setText(1, attr)

                        child_item.setText(2, type(obj).__name__)
                        child_item.setData(2, Qt.UserRole, type(obj))

                        child_item.setText(3, str(obj))
                        child_item.setData(3, Qt.UserRole, obj)

                        child_item.setFlags(child_item.flags() | Qt.ItemIsEditable)
                        self.addChild(child_item)
            except AttributeError:
                continue

    def to_msg(self):
        msg = self.data(2, Qt.UserRole)()
        for i in range(self.childCount()):
            child_item = self.child(i)
            name = child_item.text(1)
            data = child_item.data(3, Qt.UserRole)
            is_msg = child_item.childCount() > 0
            child_obj = None
            if is_msg:
                child_obj = child_item.to_msg()[1]
            else:
                dtype = child_item.data(2, Qt.UserRole)
                child_obj = dtype(data)
            setattr(msg, name, child_obj)

        return self.topic, msg, self.stamp

    def selfupdate(self, col):
        dtype = type(self.data(col, Qt.UserRole))
        if self.toplevel and col == 0:
            self.stamp = dtype(float(self.text(col)))

        elif not isinstance(None, dtype):
            self.setData(col, Qt.UserRole, dtype(self.text(col)))


class MainWidget(QWidget):

    def __init__(self, bag_dir=None):
        super(MainWidget, self).__init__()
        ui_file = os.path.join(
            rospkg.RosPack().get_path('rqt_bag_annotator'),
            'resource',
            'annotator_widget.ui'
        )

        self.allTopicsMonitor = TopicMonitor()
        self.monitor = TopicMonitor()

        loadUi(ui_file, self)

        self.master = rosgraph.Master('/bag_annotator')
        self.update_topics()
        self.topic_timer = QTimer(self)
        self.topic_timer.timeout.connect(self.update_topics)
        self.topic_timer.start(1000)

        self.monitorTopicButton.clicked.connect(self._monitor_topic)
        self.addMessageButton.clicked.connect(self._add_message)
        self.writeMessagesButton.clicked.connect(self._write_messages)

        self.startIntervalButton.clicked.connect(self._start_interval)
        self.endIntervalButton.clicked.connect(self._end_interval)
        self.newIntervalButton.clicked.connect(self._new_interval)
        self.loadFolderButton.clicked.connect(self._load_folder_click)
        self.prevBagButton.clicked.connect(self._prev_bag)
        self.nextBagButton.clicked.connect(self._next_bag)
        self.globalLocButton.clicked.connect(self._add_global_localization)
        self.publishAnnotations.clicked[bool].connect(self._publish_annotations)

        self.whichBagInput.returnPressed.connect(self._set_bag)

        self.monitoredTopicListView.setModel(self.monitor)
        self.topicListView.setModel(self.allTopicsMonitor)
        self.topicListView.doubleClicked.connect(self._monitor_topic)
        self.monitoredTopicListView.doubleClicked.connect(self._add_message)

        # self.topicListView.keyPressEvent = self._key_pressed
        self.monitoredTopicListView.keyPressEvent = self._monitored_key_pressed
        self.addedMessagesTable.keyPressEvent = self._added_key_pressed

        self.addedMessagesTable.setHeaderLabels(['Time', 'Name', 'Type', 'Data'])

        self.splitter.setStretchFactor(2, 1)

        self.addedMessagesTable.itemChanged.connect(self._message_table_item_changed)

        self.current_bag = 0

        self.load_bag_pub = rospy.Publisher('load_bag', String, latch=True)
        if bag_dir:
            self._load_folder(bag_dir)

        self._annotation_publisher = MonitorPublisher()

    def update_topics(self):
        topics = self.master.getPublishedTopics('/')

        for topic, topic_type in sorted(topics):
            if topic not in ('/bag_path',):
                self.allTopicsMonitor.add_monitor(topic, topic_type)

    def _monitor_topic(self, _):
        for i in self.topicListView.selectedIndexes():
            topic = self.allTopicsMonitor.data(i)
            item = self.allTopicsMonitor[topic]
            item.subscribe()
            self.monitor.add_item(item)

    def _add_message(self, _):
        selected_index = self.monitoredTopicListView.selectedIndexes()[0]
        selected_topic = self.monitor.data(selected_index)
        selected_monitor = self.monitor[selected_topic]
        if selected_monitor.last_msg:
            self._add_annotation(selected_monitor.last_msg, selected_topic, rospy.Time.now())

    def _write_messages(self, _):
        bag_path = rospy.wait_for_message('bag_path', String).data
        out_bag_path = annotation_path(bag_path)
        print 'writing to', out_bag_path
        with open(out_bag_path, 'w') as out_bag_file:
            out_bag = rosbag.Bag(out_bag_file, mode='w')
            for i in range(self.addedMessagesTable.topLevelItemCount()):
                item = self.addedMessagesTable.topLevelItem(i)
                topic, msg, time = item.to_msg()
                try:
                    out_bag.write(*item.to_msg())
                except Exception, e:
                    import pdb; pdb.set_trace()  # breakpoint cd6d14e3 //
            out_bag.close()

    def _monitored_key_pressed(self, event):
        if event.key() == Qt.Key_Delete:
            indexes = set(self.monitoredTopicListView.selectedIndexes())
            for index in indexes:
                self.monitor.remove_row(QModelIndex(index))

    def _added_key_pressed(self, event):
        if event.key() == Qt.Key_Delete:
            indexes = set(i.row() for i in self.addedMessagesTable.selectedIndexes())
            for index in indexes:
                self.addedMessagesTable.takeTopLevelItem(index)
        self.updateAnnotationPublisher()

    def _message_table_item_changed(self, item, column):
        if column == 3 and isinstance(item, SimpleMessageItem):
            item.updateChanged()
        else: item.selfupdate(column)
        self.updateAnnotationPublisher()

    def _current_interval(self):
        for item in self.addedMessagesTable.selectedItems():
            if item.topic == '/bag_interval':
                return item
        return MessageItem(Duration(), '/bag_interval', rospy.Time.now())

    def _new_interval(self):
        current = self._add_annotation(Duration(), '/bag_interval', rospy.Time.now())

        for i in range(self.addedMessagesTable.topLevelItemCount()):
            self.addedMessagesTable.setItemSelected(self.addedMessagesTable.topLevelItem(i), False)

        current.setSelected(True)

    def _start_interval(self):
        current = self._current_interval()
        end_time = current.stamp + current.msg

        current.stamp = rospy.Time.now()
        duration = end_time - current.stamp
        current.msg = duration
        current.setText(0, str(current.stamp.to_sec()))

        current.child(0).child(0).setText(3, str(duration.nsecs))
        current.child(0).child(0).setData(3, Qt.UserRole, duration.nsecs)

        current.child(0).child(1).setText(3, str(duration.secs))
        current.child(0).child(1).setData(3, Qt.UserRole, duration.secs)

    def _end_interval(self):
        current = self._current_interval()
        duration = rospy.Time.now() - current.stamp

        current.child(0).child(0).setText(3, str(duration.nsecs))
        current.child(0).child(0).setData(3, Qt.UserRole, duration.nsecs)

        current.child(0).child(1).setText(3, str(duration.secs))
        current.child(0).child(1).setData(3, Qt.UserRole, duration.secs)

        current.msg = duration

    def _load_folder_click(self):
        dir_path = QFileDialog.getExistingDirectory(self, 'Load from directory')
        self._load_folder(dir_path)

    def _load_current_bag(self):
        bag = self.bags[self.current_bag]
        self.load_bag_pub.publish(bag)
        self._update_which_bag_label()

        # If there are any annotations, save them
        if self.addedMessagesTable.topLevelItemCount() > 0:
            self._write_messages(None)
            self.addedMessagesTable.clear()

        # Now load the next annotations
        annotation_bag_path = annotation_path(bag)
        if os.path.exists(annotation_bag_path):
            self._load_annotations(annotation_bag_path)

        if self.current_bag == 0:
            self.prevBagButton.setEnabled(False)
        else:
            self.prevBagButton.setEnabled(True)
        if self.current_bag == len(self.bags) - 1:
            self.nextBagButton.setEnabled(False)
        else:
            self.nextBagButton.setEnabled(True)

    def _load_folder(self, dir_path):
        paths = os.listdir(dir_path)
        self.bags = [os.path.join(dir_path, p) for p in paths if re.search(r'compressed_wheelchair_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_\d{2,3}.bag', p)]
        # self.bags = glob(os.path.join(dir_path, 'compressed_wheelchair_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_{[0-9][0-9][0-9],[0-9][0-9]}.bag'))
        self.bags = sort_bags(self.bags)
        bags = []
        if self.croppedButton.isChecked():
            for bag in self.bags:
                bag_parts = bag.split('.')
                bag_parts.insert(-1, 'cropped')
                bag = '.'.join(bag_parts)
                if os.path.exists(bag):
                    bags.append(bag)
            self.bags = bags
        self.current_bag = 0
        self._load_current_bag()

    def _prev_bag(self):
        if self.current_bag - 1 >= 0:
            self.current_bag -= 1
            self._load_current_bag()

    def _next_bag(self):
        if self.current_bag + 1 < len(self.bags):
            self.current_bag += 1
            self._load_current_bag()

    def _set_bag(self):
        num = int(self.whichBagInput.text()) - 1
        if 0 <= num <= len(self.bags):
            self.current_bag = num
            self._load_current_bag()
        else:
            self.whichBagInput.setText(str(self.current_bag + 1))

    def _update_which_bag_label(self):
        self.whichBagLabel.setText('%s' % len(self.bags))
        self.whichBagInput.setText('%s' % (self.current_bag+1))

    def _add_global_localization(self):
        self._add_annotation(Empty(), '/global_localization', rospy.Time.now())

    def _load_annotations(self, annotation_path):
        bag = rosbag.Bag(annotation_path, 'r')
        del self._annotation_publisher
        self._annotation_publisher = MonitorPublisher()
        if self.publishAnnotations.isChecked():
            self._annotation_publisher.start()
        for topic, msg, stamp in bag.read_messages():
            self._add_annotation(msg, topic, stamp)
        bag.close()

    def _add_annotation(self, msg, topic, time):
        item = MessageItem(
            msg,
            topic,
            time,
            toplevel=True
        )
        self.addedMessagesTable.addTopLevelItem(item)
        self.updateAnnotationPublisher()

        return item

    def updateAnnotationPublisher(self):
        times = []
        messages = []
        for i in range(self.addedMessagesTable.topLevelItemCount()):
            item = self.addedMessagesTable.topLevelItem(i)
            topic, msg, time = item.to_msg()
            times.append(time)
            messages.append((topic, msg))
        self._annotation_publisher.update_msgs(times, messages)

    def _publish_annotations(self, status):
        if status:
            self._annotation_publisher.start()
        else:
            self._annotation_publisher.stop()

    def shutdown(self):
        for monitor in self.monitor.monitors.values():
            monitor.unsubscribe()
        self.load_bag_pub.unregister()
