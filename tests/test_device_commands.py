import unittest
from cloud.device_commands import camera_command


class DeviceCommandTests(unittest.TestCase):
    def test_explicit_english_and_bangla_commands(self):
        self.assertEqual(camera_command('Hey Deskter, open camera!'),'camera_open')
        self.assertEqual(camera_command('Close the camera.'),'camera_close')
        self.assertEqual(camera_command('ক্যামেরা চালু করো'),'camera_open')
        self.assertEqual(camera_command('ক্যামেরা বন্ধ করো'),'camera_close')

    def test_other_conversation_does_not_trigger_a_device_action(self):
        for text in ('How do I open the camera?', 'Do not open camera', 'The camera is closed.', 'Open the door', ''):
            self.assertIsNone(camera_command(text))
