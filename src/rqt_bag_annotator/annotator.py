import rospy
from qt_gui.plugin import Plugin
from .main_widget import MainWidget
from argparse import ArgumentParser


class Annotator(Plugin):

    def __init__(self, context):
        super(Annotator, self).__init__(context)
        self.setObjectName('AnnotatorPlugin')
        args = self._parse_args(context.argv())

        # Create QWidget
        self._widget = MainWidget()

        # Give QObjects reasonable names
        self._widget.setObjectName('AnnotatorPlugin')

        if context.serial_number() > 1:
            self._widget.setWindowTitle(
                self._widget.windowTitle() + (' (%d)' % context.serial_number()))
        # Add widget to the user interface
        context.add_widget(self._widget)
        rospy.set_param('use_sim_time', True)

    def save_settings(self, plugin_settings, instance_settings):
        # TODO save intrinsic configuration, usually using:
        # instance_settings.set_value(k, v)
        pass

    def restore_settings(self, plugin_settings, instance_settings):
        # TODO restore intrinsic configuration, usually using:
        # v = instance_settings.value(k)
        pass

    # def trigger_configuration(self):
        # Comment in to signal that the plugin has a way to configure
        # This will enable a setting button (gear icon) in each dock widget title bar
        # Usually used to open a modal configuration dialog

    def _parse_args(self, argv):
        parser = ArgumentParser(prog='rqt_bag_annotator', add_help=False)
        Annotator.add_arguments(parser)
        return parser.parse_args(argv)

    @staticmethod
    def add_arguments(parser):
        # parser.add_argument('bag_path', type=str, nargs='?', default='')
        parser.add_argument("-q", "--quiet", action="store_true",
                            dest="quiet",
                            help="Put plugin in silent mode")

    def shutdown_plugin(self):
        self._widget.shutdown()
